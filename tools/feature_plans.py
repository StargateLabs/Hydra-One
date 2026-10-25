from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
"""Isolated existing-kernel switches; never combine candidates implicitly."""
FEATURES={'qfuse':'STRATA_QFUSE','qfuse-pcie20':'STRATA_QFUSE','lfuse':'STRATA_LFUSE','device-plan':'STRATA_VERIFY_DEVICE_PLAN','hip-batch':'STRATA_DMA_BATCH','fill-workers':'STRATA_FETCH_PERSISTENT','fetch4':'STRATA_FETCH_THREADS'}
ENV_VALUES={'fetch4':('8','4')}
PARAMETERS={'hybrid-spec3':('--spec','4','3'),'hybrid-minp03':('--spec-min-p','0.5','0.3'),'minp70':('--spec-min-p','0.5','0.7'),'hybrid-it':('--mtp-draft-vocab',str(ROOT/'data/catalogue/hf_85a248b2_q2_0/mtp-rt/draft_vocab.bin'),str(ROOT/'data/draft_vocab_it_candidate.bin'))}
PARAMETERS['iq3-spec3']=('--spec','4','3')
FEATURES['phase-profile']='STRATA_VERIFY_PROFILE'
FEATURES['qfuse-draft']='STRATA_QFUSE'
FEATURES['tsum-draft']='STRATA_TSUM'
FEATURES['hc-small']='STRATA_HC_SMALL_WINDOW'
BASE=['--resident-budget-gib','16','--prefill','512','--expert-cache','6500','--vram-reserve-mib','2560']
def feature_plan(plan):
    feature=next((name for name in (*FEATURES,*PARAMETERS) if plan in (f'{name}-check',f'{name}-abba',f'quality-{name}-paired')),None)
    if not feature:return None
    if plan.endswith('-check'):names=[feature+'-check']
    elif plan.endswith('-abba'):names=[feature+'-base-a1',feature+'-b1',feature+'-b2',feature+'-base-a2']
    else:names=[f'quality-{feature}-base',f'quality-{feature}-candidate']
    baseline=list(BASE)+(['--pcie-frac','0.20'] if feature=='qfuse-pcie20' else [])
    if feature=='iq3-spec3':baseline+=['--spec-min-p','0.7']
    if feature in ('qfuse-draft','tsum-draft','hc-small'):baseline+=['--mtp-draft-vocab',str(ROOT/'data/draft_vocab_it_candidate.bin')]
    if feature in ('hybrid-it','hybrid-minp03','hybrid-spec3'):baseline[baseline.index('--expert-cache')+1]='10000'
    if feature in ('hybrid-minp03','hybrid-spec3'):baseline+=['--mtp-draft-vocab',str(ROOT/'data/draft_vocab_it_candidate.bin')]
    # Shared-expert LFUSE requires BF16 extra projections in both comparison arms.
    if feature=='lfuse':baseline+=['--native-bf16-extra']
    arms=[(name,list(baseline)) for name in names]
    if feature in PARAMETERS:
        flag,control,candidate=PARAMETERS[feature]
        arms=[(name,flags+[flag,candidate if feature_enabled(name,feature) else control]) for name,flags in arms]
    return feature,arms
def feature_enabled(name,feature):
    return name in (feature+'-check',feature+'-b1',feature+'-b2',f'quality-{feature}-candidate')

def apply_flags(args,flags):
    """Apply value options and the explicit BF16 switch without dropping odd tails."""
    result=list(args)
    index=0
    while index<len(flags):
        flag=flags[index]
        if flag=='--native-bf16-extra':
            if flag not in result:result.append(flag)
            index+=1
            continue
        if index+1>=len(flags):raise ValueError(f'Missing value for {flag}')
        value=flags[index+1]
        if flag in result:result[result.index(flag)+1]=value
        else:result.extend([flag,value])
        index+=2
    return result

def require_applicable_plan(plan):
    selected=feature_plan(plan)
    if selected and selected[0]=='hc-small':
        raise RuntimeError('HC small-window quarantined after GPU launch failure 719 in campaign 20261010-112443. No GPU test or model load permitted for this candidate.')
    if selected and selected[0]=='phase-profile' and plan!='phase-profile-check':
        raise RuntimeError('GPU phase stamps are diagnostic only; presence of the variable enables them, including value 0. No A/B promotion permitted.')
    if selected and selected[0]=='lfuse':
        raise RuntimeError('LFUSE requires 100% of experts in VRAM (ar_on); the partial-cache IQ3 benchmark profile cannot activate this fusion. No GPU test started.')
