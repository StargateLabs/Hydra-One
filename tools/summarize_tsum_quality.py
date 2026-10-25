"""Independently rescore paired TSUM tasks and record case regressions."""
import json
from pathlib import Path
import sys
from verify_iq3_tasks import CASES, evaluate

ROOT = Path(__file__).resolve().parents[1]

def summarize(stamp):
    reports, configs, sources = [], [], []
    for index, arm in enumerate(('base','it')):
        label = f'{stamp}-iq3-memory-quality-tsum-{arm}'
        path = ROOT/f'output/verification/{label}-tasks.json'
        report = json.loads(path.read_text(encoding='utf-8'))
        config = json.loads((ROOT/f'output/verification/{label}.json').read_text())
        assert config['env']['STRATA_TSUM'] == str(index)
        assert report['status'] == 'complete' and report['total'] == len(CASES) == len(report['cases']) == 12
        for row, (name,_,expected) in zip(report['cases'],CASES):
            assert row['case'] == name and row['expected'] == expected
            assert row['passed'] is evaluate(row['answer'],expected)
        assert report['correct'] == sum(row['passed'] for row in report['cases'])
        reports.append(report);configs.append(config);sources.append(path.relative_to(ROOT).as_posix())
    assert configs[0]['args'] == configs[1]['args'] and configs[0]['exe'] == configs[1]['exe']
    assert {k:v for k,v in configs[0]['env'].items() if k!='STRATA_TSUM'} == {k:v for k,v in configs[1]['env'].items() if k!='STRATA_TSUM'}
    a,b = reports
    assert a['model'] == b['model']
    result = dict(status='complete',optimization='STRATA_TSUM',model=a['model'],total=12,
        control_correct=a['correct'],candidate_correct=b['correct'],
        regressed_cases=[x['case'] for x,y in zip(a['cases'],b['cases']) if x['passed'] and not y['passed']],
        improved_cases=[x['case'] for x,y in zip(a['cases'],b['cases']) if not x['passed'] and y['passed']],
        sources=sources,promotion=False,limitations='One pair of twelve tasks; no general quality or endurance claim')
    (ROOT/f'output/verification/{stamp}-tsum-quality-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2));return result

if __name__ == '__main__':
    summarize(sys.argv[1])
