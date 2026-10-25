"""Validate learned-profile ABBA without mistaking warmup for independent evaluation."""
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from learn_expert_profile import validate_profile

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('profile-base-a1','profile-learn-b1','profile-learn-b2','profile-base-a2')

def summarize(stamp):
    reports = [json.loads((ROOT/f'data/benchmarks/{stamp}-iq3-memory-{name}.json').read_text()) for name in NAMES]
    configs = [json.loads((ROOT/f'output/verification/{stamp}-iq3-memory-{name}.json').read_text()) for name in NAMES]
    candidate_path = Path(configs[1]['args'][configs[1]['args'].index('--expert-profile')+1])
    training_paths = sorted((ROOT/'output/verification').glob('*-iq3-memory-profile-learn-training.json'))
    training = None
    for path in training_paths:
        record = json.loads(path.read_text())
        if record.get('status') == 'complete' and Path(record.get('profile_path','')) == candidate_path:
            training = record
            break
    assert training and training['status'] == 'complete' and training['training_requests'] == 8
    details,_ = validate_profile(candidate_path)
    assert details == training['candidate']
    base_args = configs[0]['args'];base_path = Path(base_args[base_args.index('--expert-profile')+1])
    assert hashlib.sha256(base_path.read_bytes()).hexdigest() == training['original_profile_sha256']
    groups = []
    training_hashes = {row['prompt_sha256'] for row in training['rows']}
    for index,(report,config) in enumerate(zip(reports,configs)):
        assert report['status']=='complete' and len(report['rows'])==10
        assert report['binary_sha256']==training['binary_sha256']==reports[0]['binary_sha256']
        assert report['protocol']==reports[0]['protocol']
        assert report['protocol']['tokens']==256 and report['protocol']['warmup']==5 and report['protocol']['runs']==5
        assert report['engine']['model']==training['model']==reports[0]['engine']['model']
        assert report['engine']['vram_free_mib']>=1536
        args = list(config['args']);profile_index = args.index('--expert-profile')+1
        assert Path(args[profile_index]) == (candidate_path if index in (1,2) else base_path)
        args[profile_index] = base_args[base_args.index('--expert-profile')+1]
        assert args==base_args and config['env']==configs[0]['env']
        assert [r['warmup'] for r in report['rows']]==[True]*5+[False]*5
        assert all(r['output_tokens']==256 and r['reused']==0 and r['prompt_sha256'] not in training_hashes for r in report['rows'])
        assert [r['prompt_sha256'] for r in report['rows']]==[r['prompt_sha256'] for r in reports[0]['rows']]
        group = report['rows'][5:]
        assert all(math.isfinite(r[k]) and r[k]>0 for r in group for k in ('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s'))
        groups.append(group)
    metrics = ('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s');pooled={}
    for key in metrics:
        control=statistics.median(r[key] for i in (0,3) for r in groups[i]);candidate=statistics.median(r[key] for i in (1,2) for r in groups[i])
        pooled[key]=dict(control=control,candidate=candidate,change_percent=(candidate/control-1)*100)
    result=dict(status='complete',stamp=stamp,measured_at=reports[0]['started_at'],model=reports[0]['engine']['model'],binary_sha256=reports[0]['binary_sha256'],
        protocol=reports[0]['protocol'],candidate_sha256=details['sha256'],pooled=pooled,
        arm_medians={name:{k:statistics.median(r[k] for r in g) for k in metrics} for name,g in zip(NAMES,groups)},
        actual_expert_slots=[r['engine']['expert_slots'] for r in reports],uniform_blob_budget=6500,
        training_requests=8,measured_requests=20,warmup_requests=20,promotion=False,
        limitations='Small synthetic training corpus; independent evaluation prompts; one ABBA; quality and endurance pending')
    (ROOT/f'output/verification/{stamp}-learned-profile-abba-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2));return result

if __name__=='__main__':summarize(sys.argv[1])
