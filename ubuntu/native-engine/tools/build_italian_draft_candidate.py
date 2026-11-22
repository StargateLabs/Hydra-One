"""Extend the shipped MTP subset from local Italian docs; never replace the original."""
from array import array
import hashlib
import json
from pathlib import Path
from strata_tokenizer import Tokenizer
from audit_draft_vocab_it import TEXTS

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ('PIANO-AMD-HIP-20261009.md','MONITOR-DATI-20261009.md',
          'PIANO-POTENZIAMENTO-STRATA.md','AMD-MAX-PERFORMANCE-ANALYSIS.md',
          'PAGINE-PRESTAZIONI-20261009.md')

def main():
    cfg = json.loads((ROOT / 'strata-iq3_xxs.json').read_text())
    args = cfg['args']
    tok = Tokenizer.from_gguf(args[args.index('--native') + 1])
    base_path = Path(args[args.index('--mtp') + 1]) / 'draft_vocab.bin'
    base_raw = base_path.read_bytes()
    base = list(array('i', base_raw))
    if len(base) != len(set(base)) or any(i < 0 or i >= len(tok.tokens) for i in base):
        raise ValueError('Invalid original subset')
    wanted = set(base)
    sources = []
    for name in CORPUS:
        path = ROOT / 'docs' / name
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        archived = ROOT / 'output/research/draft-it-corpus' / f'{digest}.md'
        archived.parent.mkdir(parents=True, exist_ok=True)
        if archived.exists() and archived.read_bytes() != raw:
            raise RuntimeError('Corpus archive mismatch')
        archived.write_bytes(raw)
        wanted.update(tok.encode(raw.decode('utf-8')))
        sources.append({'file': path.relative_to(ROOT).as_posix(), 'sha256': digest, 'archive': archived.relative_to(ROOT).as_posix()})
    extra = sorted(wanted - set(base))
    candidate = array('i', base + extra).tobytes()
    target = ROOT / 'data/draft_vocab_it_candidate.bin'
    target.write_bytes(candidate)
    heldout = [i for text in TEXTS for i in tok.encode(text)]
    result = {'status': 'candidate', 'training': 'Local documentation token coverage, no benchmark answers or audit samples used',
              'sources': sources, 'base_sha256': hashlib.sha256(base_raw).hexdigest(),
              'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
              'base_tokens': len(base), 'candidate_tokens': len(base) + len(extra), 'added': len(extra),
              'draft_head_extra_mib_estimate': len(extra) * 1792 / 2**20,
              'heldout_sample_tokens': len(heldout),
              'heldout_coverage_percent': 100 * sum(i in wanted for i in heldout) / len(heldout),
              'limitations': 'Small static Italian audit; lexical overlap with technical docs. Not inference quality or draft acceptance.',
              'file': target.relative_to(ROOT).as_posix(), 'operational_subset_replaced': False}
    (ROOT / 'output/verification/italian-draft-candidate.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
