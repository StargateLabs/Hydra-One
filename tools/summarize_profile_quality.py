"""Independently validate task scores for the learned-cache candidate."""
import hashlib
import json
from pathlib import Path
import sys
from learn_expert_profile import validate_profile
from verify_iq3_tasks import CASES,evaluate

ROOT=Path(__file__).resolve().parents[1]

def summarize(stamp):
    reports,configs,sources=[],[],[]
    for arm in ('base','candidate'):
        label=f'{stamp}-iq3-memory-quality-profile-{arm}'
        path=ROOT/f'output/verification/{label}-tasks.json'
        report=json.loads(path.read_text(encoding='utf-8'))
        config=json.loads((ROOT/f'output/verification/{label}.json').read_text())
        assert report['status']=='complete' and report['total']==len(report['cases'])==len(CASES)==12
        for row,(name,_,expected) in zip(report['cases'],CASES):
            assert row['case']==name and row['expected']==expected
            assert row['passed'] is evaluate(row['answer'],expected)
        assert report['correct']==sum(row['passed'] for row in report['cases'])
        reports.append(report);configs.append(config);sources.append(path.relative_to(ROOT).as_posix())
    a,b=reports;ca,cb=configs
    assert a['model']==b['model'] and ca['env']==cb['env'] and ca['exe']==cb['exe']
    candidate_args=list(cb['args']);i=candidate_args.index('--expert-profile')+1
    details,_=validate_profile(candidate_args[i]);candidate_args[i]=ca['args'][ca['args'].index('--expert-profile')+1]
    assert candidate_args==ca['args']
    result=dict(status='complete',model=a['model'],candidate_sha256=details['sha256'],total=12,
        binary_sha256=hashlib.sha256(Path(ca['exe']).read_bytes()).hexdigest(),
        control_correct=a['correct'],candidate_correct=b['correct'],
        regressed_cases=[x['case'] for x,y in zip(a['cases'],b['cases']) if x['passed'] and not y['passed']],
        improved_cases=[x['case'] for x,y in zip(a['cases'],b['cases']) if not x['passed'] and y['passed']],
        sources=sources,promotion=False,limitations='One paired set of twelve tasks; no general quality or endurance claim')
    (ROOT/f'output/verification/{stamp}-profile-quality-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2));return result

if __name__=='__main__':summarize(sys.argv[1])
