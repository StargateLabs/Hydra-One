"""Read-only format and source checks before proposing upstream-inspired kernels."""
import hashlib
import json
from pathlib import Path
from gguf_reader import GGUFFile

ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'ee9c077088623ad9996335aa1f187a56cf669035'

def main():
    archive = ROOT/'output/research'/f'unsloth-{COMMIT[:12]}'
    manifest = json.loads((archive/'manifest.json').read_text(encoding='utf-8'))
    if manifest['commit'] != COMMIT:
        raise ValueError('Upstream revision mismatch')
    for entry in manifest['files']:
        content = (archive/entry['path']).read_bytes()
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise ValueError('Archived source mismatch: '+entry['path'])
    config_path = ROOT/'strata-iq3_xxs.json'
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    args = config['args']
    gguf = GGUFFile(args[args.index('--native')+1])
    heads = [t for t in gguf.tensors if t.name == 'output.weight']
    if len(heads) != 1:
        raise ValueError('Expected one native output head')
    head = heads[0]
    result = dict(kind='Static source and model-format audit; no GPU timing',
        upstream_commit=COMMIT, source_files_verified=len(manifest['files']),
        model=config['model_name'], config_sha256=hashlib.sha256(config_bytes).hexdigest(),
        output_head=dict(format=head.type_name,shape=head.shape, type_id=head.type_id),
        q6_packed_applicable_to_output_head=head.type_id == 14,
        draft_head='Inherits native output-head format unless explicitly converted; current config has no draft conversion flag',
        changes_applied=False, gpu_work=False,
        candidates=['Q5_K packed head with exact reconstruction and measured VRAM budget',
                    'gfx1100 shape-specific dispatch for 1..8 token windows',
                    'Producer/activation quantization fusion on measured hot paths'],
        exclusions=['Unsloth NF4/INT4 kernels are different quantization formats',
                    'Marlin/tinygemm repack excludes HIP in the inspected Unsloth code',
                    'GGUF serving uses llama-server rather than the PyTorch Triton kernels'])
    target = ROOT/'output/verification/unsloth-applicability-20261009.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__ == '__main__':
    main()
