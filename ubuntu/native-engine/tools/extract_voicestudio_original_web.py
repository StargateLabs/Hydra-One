"""Extract the installed original renderer for VoiceStudio's supported SPA mount.

Copies bytes unchanged from app.asar. Validates ASAR SHA256 integrity on every
file, refuses existing files with different bytes, and saves source manifest.
No replacement UI, desktop package modification, or process restart.
"""
import hashlib
import json
import os
from pathlib import Path
import struct

def main():
    resources=Path(os.environ['LOCALAPPDATA'])/'Programs/VoiceStudio/resources'
    archive=resources/'app.asar'
    target=resources/'frontend/dist'
    manifest=[]
    with archive.open('rb') as stream:
        fields=struct.unpack('<4I',stream.read(16))
        header=json.loads(stream.read(fields[3]))
        base=8+fields[1]
        renderer=header['files']['out']['files']['renderer']
        def extract(tree, relative=Path()):
            for name,entry in tree.get('files',{}).items():
                current=relative/name
                if 'files' in entry:
                    extract(entry,current);continue
                if entry.get('link') or entry.get('unpacked'): raise RuntimeError('Unexpected renderer link/unpacked file')
                destination=(target/current).resolve()
                if not destination.is_relative_to(target.resolve()): raise RuntimeError('Unsafe renderer path')
                stream.seek(base+int(entry['offset']))
                raw=stream.read(entry['size'])
                integrity=entry.get('integrity',{})
                digest=hashlib.sha256(raw).hexdigest()
                if len(raw)!=entry['size'] or integrity.get('algorithm')!='SHA256' or integrity.get('hash')!=digest:
                    raise RuntimeError('Original renderer integrity mismatch: '+str(current))
                if destination.exists() and destination.read_bytes()!=raw:
                    raise RuntimeError('Existing frontend differs: '+str(destination))
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(raw)
                manifest.append({'path':current.as_posix(),'bytes':len(raw),'sha256':digest})
        extract(renderer)
    result={'source':str(archive),'source_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
            'target':str(target),'files':manifest,'original_bytes_preserved':True,'restart_required':True}
    output=Path(__file__).resolve().parents[1]/'output/voicestudio/original-web-manifest.json'
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'files':len(manifest),'bytes':sum(m['bytes'] for m in manifest),'target':str(target)},indent=2))

if __name__=='__main__':main()
