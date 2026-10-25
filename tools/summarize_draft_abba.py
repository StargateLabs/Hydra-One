"""Validate and summarize the fixed-cache Italian draft ABBA campaign."""
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('draft-base-a1','draft-it-b1','draft-it-b2','draft-base-a2')

def summarize(stamp):
    reports = [json.loads((ROOT/'data/benchmarks'/f'{stamp}-iq3-memory-{name}.json').read_text()) for name in NAMES]
    configs = [json.loads((ROOT/'output/verification'/f'{stamp}-iq3-memory-{name}.json').read_text()) for name in NAMES]
    expected_args = None
    groups = []
    for index, (report, config) in enumerate(zip(reports, configs)):
        assert report['status'] == 'complete' and len(report['rows']) == 10, 'Incomplete arm'
        assert report['protocol'] == reports[0]['protocol'], 'Different protocol'
        assert report['binary_sha256'] == reports[0]['binary_sha256'], 'Different binary'
        assert report['engine']['expert_slots'] == reports[0]['engine']['expert_slots'], 'Different actual cache size'
        assert report['engine']['vram_free_mib'] >= 1536, 'Insufficient startup VRAM margin'
        args = list(config['args'])
        if index in (1, 2):
            position = args.index('--mtp-draft-vocab')
            assert Path(args[position+1]).resolve() == (ROOT/'data/draft_vocab_it_candidate.bin').resolve()
            del args[position:position+2]
        if expected_args is None: expected_args = args
        assert args == expected_args and config['env'] == configs[0]['env'], 'Other settings changed'
        measured = [r for r in report['rows'] if r['warmup'] is False]
        assert len(measured) == 5
        assert all(r['output_tokens'] == 256 and r['reused'] == 0 for r in report['rows']), 'Output length or prompt reuse differs'
        assert all(math.isfinite(r[key]) and r[key] > 0 for r in measured for key in ('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s'))
        groups.append(measured)
    assert all([r['prompt_sha256'] for r in group] == [r['prompt_sha256'] for r in groups[0]] for group in groups), 'Unpaired prompts'
    metrics = ('decode_tok_s','prefill_tok_s','wall_tok_s','wall_s')
    pooled = {}
    for key in metrics:
        control = statistics.median(r[key] for i in (0, 3) for r in groups[i])
        candidate = statistics.median(r[key] for i in (1, 2) for r in groups[i])
        pooled[key] = {'control': control, 'candidate': candidate, 'change_percent': (candidate/control-1)*100}
    result = {'status': 'complete', 'stamp': stamp, 'model': reports[0]['engine']['model'],
              'measured_at': reports[0]['started_at'], 'binary_sha256': reports[0]['binary_sha256'],
              'draft_candidate_sha256': hashlib.sha256((ROOT/'data/draft_vocab_it_candidate.bin').read_bytes()).hexdigest(),
              'expert_slots': reports[0]['engine']['expert_slots'], 'uniform_blob_budget': 6500, 'protocol': reports[0]['protocol'], 'pooled': pooled,
              'arm_medians': {name: {key: statistics.median(r[key] for r in group) for key in metrics} for name, group in zip(NAMES, groups)},
              'measured_requests': 20, 'warmup_requests': 20,
              'limitations': ['One ABBA cycle, no statistical significance claim', 'Static technical Italian task; quality and other workloads require separate checks']}
    result['control_drift_percent']={key:100*(result['arm_medians'][NAMES[3]][key]/result['arm_medians'][NAMES[0]][key]-1) for key in ('decode_tok_s','prefill_tok_s')}
    result['confounded']=abs(result['control_drift_percent']['decode_tok_s'])>5
    result['promotion']=False
    if result['confounded']:result['limitations'].append('Control decode drift exceeds 5%; pooled gain is descriptive, not a stable causal improvement')
    (ROOT/'output/verification'/f'{stamp}-draft-it-abba-summary.json').write_text(json.dumps(result, indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result, indent=2))
    return result

if __name__ == '__main__':
    summarize(sys.argv[1])
