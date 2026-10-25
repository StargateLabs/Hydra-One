"""Register the already reviewed bilingual optional-engine copy in the UI catalogue."""
import ast
import json
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
STRING=r"'(?:\\.|[^'\\])*'"

def pairs(source):
    identifiers=r'(?:backend|up|lab|ctrl|chat|generation|training|speech|audio|soup)-[a-z0-9-]+'
    for italian,english in raw_pairs(source):
        if re.fullmatch(identifiers,italian) and re.fullmatch(identifiers,english):continue
        yield italian,english

def raw_pairs(source):
    for _,a,b,c,d in re.findall(rf'\[\s*({STRING}),\s*({STRING}),\s*({STRING}),\s*({STRING}),\s*({STRING})\s*\]',source):
        if 'window.StrataToolCopy' in source:
            yield ast.literal_eval(a),ast.literal_eval(b)
            yield ast.literal_eval(c),ast.literal_eval(d)

    if 'const guides={' in source:
        guides=source.split('const guides={',1)[1].split('};',1)[0]
        for a,b,c,d in re.findall(rf':\[({STRING}),({STRING}),({STRING}),({STRING})\]',guides):
            yield ast.literal_eval(a),ast.literal_eval(b)
            yield ast.literal_eval(c),ast.literal_eval(d)
    if 'const sections=' in source:
        sections=source.split('const sections=',1)[1].split(';',1)[0]
        for _,__,a,b,c,d in re.findall(rf'\[({STRING}),({STRING}),({STRING}),({STRING}),({STRING}),({STRING})\]',sections):
            yield ast.literal_eval(a),ast.literal_eval(b)
            yield ast.literal_eval(c),ast.literal_eval(d)
    patterns=[rf'\b(?:text|t)\(\s*({STRING})\s*,\s*({STRING})',
              rf'\[\s*\'(?:backend|up)-[^\']+\'\s*,\s*({STRING})\s*,\s*({STRING})',
              rf':\s*\[\s*({STRING})\s*,\s*({STRING})\s*\]']
    if 'const label=(it,english)' in source:patterns.append(rf'\blabel\(\s*({STRING})\s*,\s*({STRING})')
    for pattern in patterns:
        for a,b in re.findall(pattern,source):
            try:
                italian,english=ast.literal_eval(a),ast.literal_eval(b)
                # Control ID lists are not bilingual user-facing copy.
                if re.fullmatch(r'(?:backend|up|lab|ctrl|chat|generation|training|speech|audio|soup)-[a-z0-9-]+',italian) and re.fullmatch(r'(?:backend|up|lab|ctrl|chat|generation|training|speech|audio|soup)-[a-z0-9-]+',english):continue
                yield italian,english
            except (ValueError,SyntaxError):continue
    if 'const options={' in source:
        options=source.split('const options={',1)[1].split('};',1)[0]
        for _,a,b in re.findall(rf'\[\s*({STRING})\s*,\s*({STRING})\s*,\s*({STRING})\s*\]',options):
            try:
                italian,english=ast.literal_eval(a),ast.literal_eval(b)
                # Control ID lists are not bilingual user-facing copy.
                if re.fullmatch(r'(?:backend|up|lab|ctrl|chat|generation|training|speech|audio|soup)-[a-z0-9-]+',italian) and re.fullmatch(r'(?:backend|up|lab|ctrl|chat|generation|training|speech|audio|soup)-[a-z0-9-]+',english):continue
                yield italian,english
            except (ValueError,SyntaxError):continue

def main():
    path=ROOT/'serve/locales/ui-it-en.json';data=json.loads(path.read_text(encoding='utf-8'));before=len(data['pairs'])
    for name in ('optional-backends.js','optional-catalogue.js','local-training.js','local-audio.js','local-speech.js','local-separation.js','ai-lab.js','lab-evidence.js','performance-spectrum.js','performance-workspace.js','chat-context.js','local-export.js','local-vision.js','local-generation.js','training-runtime.js','multimedia-studio.js','media-studio-design.js','update-center.js','control-section-headers.js'):
        for it,en in pairs((ROOT/'serve/web'/name).read_text(encoding='utf-8')):
            if it.strip() and en.strip():data['pairs'].setdefault(it,en)
    for name in ('function-identity.js','training-design.js','model-setup-guide.js','training-methods.js','training-native-app.js','configuration-assistant.js','update-notifications.js','local-model-picker.js','file-controls.js','about-capabilities.js'):
        for it,en in pairs((ROOT/'serve/web'/name).read_text(encoding='utf-8')):
            if it.strip() and en.strip():data['pairs'].setdefault(it,en)
    # Scan only scripts shipped by this page; data packs and backups are excluded.
    html=(ROOT/'serve/web/index.html').read_text(encoding='utf-8')
    for relative in re.findall(r'<script[^>]+src="(web/[^"?]+)',html):
        script=ROOT/'serve'/relative
        if script.name in ('language-data.js','language.js') or not script.is_file():continue
        for it,en in pairs(script.read_text(encoding='utf-8')):
            if it.strip() and en.strip():data['pairs'].setdefault(it,en)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"Added {len(data['pairs'])-before} bilingual entries; existing translations preserved")
    from build_language_assets import main as build
    build()

if __name__=='__main__':main()
