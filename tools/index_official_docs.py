"""Create a reproducible inventory of every archived official text document."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT/'output/research/official-docs-main'
BASE = ROOT/'output/research/source-v0.1.40.3/Strata-d5ea7133741e67743c0e886bb426c0ce8d69cf6c'

def main():
    manifest = json.loads((ARCHIVE/'manifest.json').read_text(encoding='utf-8'))
    current = ARCHIVE/manifest['commit']
    records = []
    for entry in manifest['documents']:
        path = current/entry['path']
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise RuntimeError(f'Archive differs: {path}')
        content = raw.decode('utf-8', errors='replace')
        baseline = BASE/entry['path']
        change = 'new' if not baseline.is_file() else 'unchanged' if baseline.read_bytes() == raw else 'changed'
        headings = [{'line':i,'text':line} for i,line in enumerate(content.splitlines(),1)
                    if re.match(r'^#{1,4} ',line)]
        flags = sorted(set(re.findall(r'\bSTRATA_[A-Z0-9_]+\b|--[a-z][a-z0-9-]+', content)))
        evidence = [{'line':i,'text':line} for i,line in enumerate(content.splitlines(),1)
                    if re.search(r'Windows|HIP|gfx1100|unvalidated|not.*tested|not.*measured|off by default|regression|corrupt',line,re.I)]
        records.append({**entry,'change_since_release':change,'lines':len(content.splitlines()),
                        'headings':headings,'flags':flags,'platform_and_limits':evidence})
    result = {'commit':manifest['commit'],'release_reference':'v0.1.40.3',
              'method':'Complete text indexing; manual applicability review is documented separately.',
              'documents':records}
    (ARCHIVE/'index.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    primary = [r for r in records if r['path'].startswith('docs/') and r['path'].endswith('.md')]
    table = ['# Inventario della documentazione ufficiale', '',
             f"Revisione: `{manifest['commit']}`. {len(records)} documenti testuali indicizzati; {len(primary)} pagine Markdown in docs.", '',
             'Indicizzazione completa: hash, titoli, opzioni, riferimenti alle piattaforme e limiti in `output/research/official-docs-main/index.json`.', '',
             '| Pagina | Righe | Rispetto alla release 0.1.40.3 |', '|---|---:|---|']
    for item in primary:
        url = f"https://github.com/Niko1221/Strata/blob/{manifest['commit']}/{item['path']}"
        table.append(f"| [{item['path']}]({url}) | {item['lines']} | {item['change_since_release']} |")
    (ROOT/'docs/INVENTARIO-DOC-UFFICIALE-20261009.md').write_text('\n'.join(table)+'\n',encoding='utf-8')
    print(json.dumps({'documents':len(records),'primary_pages':len(primary),
                      'changed_primary':[r['path'] for r in primary if r['change_since_release']!='unchanged']}))

if __name__ == '__main__':
    main()
