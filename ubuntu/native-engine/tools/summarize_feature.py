"""Validate complete one-switch ABBA trials and independently rescore paired tasks."""
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from feature_plans import FEATURES,PARAMETERS,ENV_VALUES
ROOT=Path(__file__).resolve().parents[1]
def require(condition,message):
    if not condition:raise RuntimeError(message)
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def configs_match(configs,flag,values=('0','1')):
    first=configs[0]
    for index,cfg in enumerate(configs):
        require(cfg['exe']==first['exe'] and cfg['args']==first['args'],'Changed executable or arguments')
        enabled=index in (1,2) if len(configs)==4 else index==1
        require(cfg['env'][flag]==values[int(enabled)],'Switch not applied')
        require({k:v for k,v in cfg['env'].items() if k!=flag}=={k:v for k,v in first['env'].items() if k!=flag},'Other environment changed')
def configs_match_for_feature(configs,feature):
    if feature in FEATURES:return configs_match(configs,FEATURES[feature],ENV_VALUES.get(feature,('0','1')))
    flag,control,candidate=PARAMETERS[feature]
    normalized=[]
    for index,cfg in enumerate(configs):
        args=list(cfg['args']);require(args.count(flag)==1,'Missing or duplicate parameter')
        i=args.index(flag);enabled=index in (1,2) if len(configs)==4 else index==1
        require(args[i+1]==(candidate if enabled else control),'Wrong parameter value')
        del args[i:i+2];normalized.append((cfg['exe'],args,cfg['env']))
    require(all(item==normalized[0] for item in normalized),'Other configuration changed')

def feature_flag(feature):
    return FEATURES[feature] if feature in FEATURES else PARAMETERS[feature][0]

def summarize_abba(stamp,feature):
    flag=feature_flag(feature);names=[feature+'-base-a1',feature+'-b1',feature+'-b2',feature+'-base-a2'];reports=[];configs=[]
    for name in names:
        label=f'{stamp}-iq3-memory-{name}';r=read(ROOT/f'data/benchmarks/{label}.json');cfg=read(ROOT/f'output/verification/{label}.json');margin=read(ROOT/f'output/verification/{label}-startup-margin.json')
        if feature=='fetch4':
            text=(ROOT/f'output/verification/{label}-engine.log').read_text(encoding='utf-8',errors='replace')
            path_lines=[line for line in text.splitlines() if 'the file tier reads' in line]
            require(path_lines and 'through the file cache' in path_lines[-1],'Fetch thread candidate bypassed by direct I/O')
        if feature in ('hip-batch','fill-workers','hc-small'):
            marker={'hip-batch':'strata HIP batch active:','fill-workers':'strata persistent fetch active:','hc-small':'strata HC small-window active:'}[feature]
            active=marker in (ROOT/f'output/verification/{label}-engine.log').read_text(encoding='utf-8',errors='replace')
            require(active==(name in (feature+'-b1',feature+'-b2')),'Candidate runtime path not demonstrated')
        require(r['status']=='complete' and len(r['rows'])==10,'Incomplete benchmark')
        require(r['protocol']==dict(warmup=5,runs=5,tokens=256,paragraphs=24,prompt_set='iq3-chunk-v1'),'Wrong protocol')
        require(margin['before_prompts'] is True and margin['vram_free_mib']>=1536 and r['engine']['vram_free_mib']>=1536,'Insufficient VRAM margin')
        require(r['binary_sha256']==hashlib.sha256(Path(cfg['exe']).read_bytes()).hexdigest(),'Executable identity differs')
        for i,row in enumerate(r['rows']):
            require(row['warmup']==(i<5) and row['output_tokens']==256 and row['reused']==0,'Invalid output or reused prompt')
            require(all(type(row[k]) in (int,float) and math.isfinite(row[k]) and row[k]>0 for k in ('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s')),'Invalid timing')
            require(all(re.fullmatch('[a-f0-9]{64}',row[k]) for k in ('prompt_sha256','response_sha256')),'Missing prompt/response identity')
        if reports:
            require(r['engine']['model']==reports[0]['engine']['model'] and r['engine']['expert_slots']==reports[0]['engine']['expert_slots'],'Model or cache changed')
            require([x['prompt_sha256'] for x in r['rows']]==[x['prompt_sha256'] for x in reports[0]['rows']],'Unpaired prompts')
        reports.append(r);configs.append(cfg)
    configs_match_for_feature(configs,feature);metrics=('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s');groups=[r['rows'][5:] for r in reports];pooled={}
    for key in metrics:
        a=statistics.median(row[key] for i in (0,3) for row in groups[i]);b=statistics.median(row[key] for i in (1,2) for row in groups[i]);pooled[key]=dict(control=a,candidate=b,change_percent=(b/a-1)*100)
    result=dict(status='complete',stamp=stamp,optimization=flag,model=reports[0]['engine']['model'],measured_at=reports[0]['started_at'],binary_sha256=reports[0]['binary_sha256'],
        protocol=reports[0]['protocol'],expert_slots=reports[0]['engine']['expert_slots'],pooled=pooled,measured_requests=20,warmup_requests=20,
        arm_medians={n:{k:statistics.median(r[k] for r in group) for k in metrics} for n,group in zip(names,groups)},
        exact_response_pairs=sum(groups[a][i]['response_sha256']==groups[b][i]['response_sha256'] for a,b in ((0,1),(3,2)) for i in range(5)),
        response_pairs=10,promotion=False,limitations='One ABBA; independent quality and sustained stability required')
    if feature in PARAMETERS or feature in FEATURES:
        a1=result['arm_medians'][names[0]];a2=result['arm_medians'][names[3]]
        drift={key:(a2[key]/a1[key]-1)*100 for key in ('decode_tok_s','prefill_tok_s')}
        result['control_drift_percent']=drift
        result['confounded']=abs(drift['prefill_tok_s'])>5 or abs(drift['decode_tok_s'])>5
        if result['confounded']:
            result['limitations']='Control arms differ by more than 5%; pooled change is descriptive, not a stable causal gain. Independent confirmation, quality and sustained stability required.'
    (ROOT/f'output/verification/{stamp}-{feature}-abba-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2));return result
def summarize_quality(stamp,feature):
    from verify_iq3_tasks import CASES,evaluate
    reports=[];configs=[];sources=[]
    for arm in ('base','candidate'):
        label=f'{stamp}-iq3-memory-quality-{feature}-{arm}';path=ROOT/f'output/verification/{label}-tasks.json';r=read(path);cfg=read(ROOT/f'output/verification/{label}.json');margin=read(ROOT/f'output/verification/{label}-startup-margin.json')
        require(margin['before_prompts'] is True and margin['vram_free_mib']>=1536,'Insufficient margin')
        require(r['status']=='complete' and r['total']==len(r['cases'])==len(CASES)==12,'Incomplete task set')
        for row,(name,prompt,expected) in zip(r['cases'],CASES):
            require(row['case']==name and row['expected']==expected and row['passed'] is evaluate(row['answer'],expected),'Invalid task result')
        require(r['correct']==sum(row['passed'] for row in r['cases']),'Wrong task count');reports.append(r);configs.append(cfg);sources.append(path.relative_to(ROOT).as_posix())
    configs_match_for_feature(configs,feature);a,b=reports;require(a['model']==b['model'],'Different models')
    result=dict(status='complete',optimization=feature_flag(feature),model=a['model'],total=12,control_correct=a['correct'],candidate_correct=b['correct'],
        binary_sha256=hashlib.sha256(Path(configs[0]['exe']).read_bytes()).hexdigest(),regressed_cases=[x['case'] for x,y in zip(a['cases'],b['cases']) if x['passed'] and not y['passed']],
        improved_cases=[x['case'] for x,y in zip(a['cases'],b['cases']) if not x['passed'] and y['passed']],sources=sources,promotion=False,limitations='One paired task set; no overall quality claim')
    (ROOT/f'output/verification/{stamp}-{feature}-quality-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2));return result
