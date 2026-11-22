"""Validate a one-variable TSUM comparison before publishing any gain."""
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('tsum-base-a1','tsum-b1','tsum-b2','tsum-base-a2')

def summarize(stamp):
    reports = []
    configurations = []
    groups = []
    for index, name in enumerate(NAMES):
        report = json.loads((ROOT/f'data/benchmarks/{stamp}-iq3-memory-{name}.json').read_text())
        config = json.loads((ROOT/f'output/verification/{stamp}-iq3-memory-{name}.json').read_text())
        assert report['status'] == 'complete' and len(report['rows']) == 10
        assert [r['warmup'] for r in report['rows']] == [True]*5+[False]*5
        assert len(report['binary_sha256']) == 64
        assert all(c in '0123456789abcdef' for c in report['binary_sha256'])
        assert report['engine']['vram_free_mib'] >= 1536
        assert config['env']['STRATA_TSUM'] == ('1' if index in (1,2) else '0')
        normalized = {'args':config['args'],'env':{k:v for k,v in config['env'].items() if k != 'STRATA_TSUM'}}
        if reports:
            assert normalized == configurations[0]
            for key in ('protocol','binary_sha256'):
                assert report[key] == reports[0][key]
            assert report['engine']['expert_slots'] == reports[0]['engine']['expert_slots']
            assert report['engine']['model'] == reports[0]['engine']['model']
            assert [r['prompt_sha256'] for r in report['rows']] == [r['prompt_sha256'] for r in reports[0]['rows']]
        assert all(r['output_tokens'] == 256 and r['reused'] == 0 for r in report['rows'])
        measured = [r for r in report['rows'] if r['warmup'] is False]
        assert len(measured) == 5
        assert all(math.isfinite(r[k]) and r[k] > 0 for r in measured for k in ('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s'))
        reports.append(report); configurations.append(normalized); groups.append(measured)
    assert all([r['prompt_sha256'] for r in g] == [r['prompt_sha256'] for r in groups[0]] for g in groups)
    metrics = ('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s')
    pooled = {}
    for key in metrics:
        control = statistics.median(r[key] for i in (0,3) for r in groups[i])
        candidate = statistics.median(r[key] for i in (1,2) for r in groups[i])
        pooled[key] = dict(control=control,candidate=candidate,change_percent=(candidate/control-1)*100)
    result = dict(status='complete',stamp=stamp,model=reports[0]['engine']['model'],
        binary_sha256=reports[0]['binary_sha256'],protocol=reports[0]['protocol'],
        expert_slots=reports[0]['engine']['expert_slots'],pooled=pooled,
        arm_medians={name:{k:statistics.median(r[k] for r in group) for k in metrics} for name,group in zip(NAMES,groups)},
        measured_requests=20,warmup_requests=20,promotion=False,
        limitations='One ABBA campaign; task quality and endurance require separate validation')
    (ROOT/f'output/verification/{stamp}-tsum-abba-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return result

if __name__ == '__main__':
    summarize(sys.argv[1])
