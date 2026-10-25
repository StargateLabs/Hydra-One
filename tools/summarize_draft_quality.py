"""Compare independently scored task reports; never infer quality from speed."""
import json
import sys
from pathlib import Path
from verify_iq3_tasks import CASES, evaluate

ROOT = Path(__file__).resolve().parents[1]

def summarize(stamp):
    reports = []
    sources = []
    for arm in ('base', 'it'):
        path = ROOT / f'output/verification/{stamp}-iq3-memory-quality-draft-{arm}-tasks.json'
        report = json.loads(path.read_text(encoding='utf-8'))
        assert report['status'] == 'complete' and report['total'] == 12
        assert len(report['cases']) == len(CASES) == 12
        for row, (name, _, expected) in zip(report['cases'], CASES):
            assert row['case'] == name and row['expected'] == expected
            assert row['passed'] is evaluate(row['answer'], expected)
        assert report['correct'] == sum(row['passed'] for row in report['cases'])
        reports.append(report)
        sources.append(path.relative_to(ROOT).as_posix())
    control, candidate = reports
    assert control['model'] == candidate['model']
    import hashlib
    result = dict(status='complete', model=control['model'], total=12,
        candidate_sha256=hashlib.sha256((ROOT/'data/draft_vocab_it_candidate.bin').read_bytes()).hexdigest(),
        control_correct=control['correct'], candidate_correct=candidate['correct'],
        regressed_cases=[a['case'] for a,b in zip(control['cases'],candidate['cases']) if a['passed'] and not b['passed']],
        improved_cases=[a['case'] for a,b in zip(control['cases'],candidate['cases']) if not a['passed'] and b['passed']],
        sources=sources, limitations='12 deterministic tasks, one paired run; not a general quality benchmark or endurance test',
        promotion=False)
    (ROOT/f'output/verification/{stamp}-draft-quality-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return result

if __name__ == '__main__':
    summarize(sys.argv[1])
