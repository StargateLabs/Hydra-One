"""Measure installed IQ3_XXS memory paths on an isolated local server.

Keeps the operational configuration untouched. Reports include five warmups,
five measured requests, fixed paired prompts and engine timing diagnostics.
"""
import datetime
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import threading
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from serve.configuration import atomic_json
from benchmark_guard import require_startup_vram_margin

OUT = ROOT / 'output/verification'
PORT = 8089
URL = f'http://127.0.0.1:{PORT}'

def pcie55_arms(plan):
    return pcie_arms(plan,55)

def pcie_arms(plan,percent):
    if percent not in (20,55):raise ValueError('Unsupported PCIe candidate')
    prefix=f'pcie{percent}'
    baseline = ['--resident-budget-gib','16','--prefill','512','--expert-cache','6500','--vram-reserve-mib','2560']
    candidate = baseline+['--pcie-frac',f'{percent/100:.2f}']
    if plan == f'{prefix}-check':return [(f'{prefix}-check',candidate)]
    if plan == f'{prefix}-abba':return [('pcie-auto-a1',baseline),(f'{prefix}-b1',candidate),(f'{prefix}-b2',candidate),('pcie-auto-a2',baseline)]
    if plan == f'quality-{prefix}-paired':return [(f'quality-{prefix}-base',baseline),(f'quality-{prefix}-candidate',candidate)]
    raise ValueError('Unknown PCIe plan')

def publish_monitor(stop, label):
    latest = None
    path = ROOT/'data/benchmark-live.json'
    while not stop.is_set():
        try:
            latest = get(URL+'/metrics')
            latest.pop('benchmark', None)  # snapshots must not recursively embed the previous snapshot
            atomic_json(path, {'label':label,'source_port':PORT,'updated_at':time.time(),'active':True,'metrics':latest})
        except (OSError, ValueError):
            pass
        stop.wait(1)
    if latest is not None:
        try:
            latest = get(URL+'/metrics')
            latest.pop('benchmark', None)
        except (OSError, ValueError):
            latest['live'] = {**latest.get('live', {}), 'state':'unloaded', 'queued':0}
        atomic_json(path, {'label':label,'source_port':PORT,'updated_at':time.time(),'active':False,'metrics':latest})

def validate_matrix(path, expected):
    rows = json.loads(path.read_text(encoding='utf-8'))
    if len(rows) != expected or any(
        not isinstance(r.get('completion_tokens'), int) or r['completion_tokens'] <= 0
        or not r.get('answer_head') or not isinstance(r.get('engine_decode_tps'), (int, float))
        or r['engine_decode_tps'] <= 0 for r in rows
    ):
        raise RuntimeError('Incomplete corpus benchmark: missing answers or engine measurements')
    return rows

def get(url):
    with urllib.request.urlopen(url, timeout=3) as r:
        return json.load(r)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    plan_argument = parser.add_argument('--plan', choices=('memory','refine','compatibility','resident28','prefill-diagnostic','kv-dma','short-diagnostic','recovery-prefill','recovery-memory','recovery-nosync','stability','chunk512','chunk-abba','memory20-check','memory20-measure','decode-profile','pcore7-check','pcore7-measure','gr4-check','gr4-measure','spec3-check','spec3-measure','static-check','static-measure','tasks17-check','tasks17-measure','quality-ab','quality-memory-only','ram-only-check','ram-only-measure','context8-check','context16-check','context32-check','source-control-check','source-control-measure','full-resident-check','full-resident-measure','full-resident-abba','quality-full-resident'),default='memory')
    plan_argument.choices += ('host-last-check','host-last-measure','adapt-lag2-check','adapt-lag2-measure','adapt-async-check','adapt-async-measure','draft-it-check','draft-it-measure','draft-it-abba','quality-draft-paired','head-profile','tsum-check','tsum-abba')
    plan_argument.choices += ('quality-tsum-paired',)
    plan_argument.choices += ('profile-learn','profile-learn-abba','quality-profile-paired')
    plan_argument.choices += ('pcie55-check','pcie55-abba','quality-pcie55-paired')
    plan_argument.choices += ('pcie20-check','pcie20-abba','quality-pcie20-paired')
    plan_argument.choices += ('qfuse-check','qfuse-abba','quality-qfuse-paired')
    plan_argument.choices += ('qfuse-pcie20-check','qfuse-pcie20-abba','quality-qfuse-pcie20-paired')
    plan_argument.choices += ('kv-experts-check',)
    plan_argument.choices += ('lfuse-check','lfuse-abba','quality-lfuse-paired','device-plan-check','device-plan-abba','quality-device-plan-paired','quality-hip-batch-paired','hip-batch-check','hip-batch-abba')
    plan_argument.choices += ('minp70-check','minp70-abba','quality-minp70-paired','quality-fill-workers-paired','quality-fetch4-paired','quality-hybrid','quality-hybrid-it-paired','quality-hybrid-minp03-paired','quality-hybrid-spec3-paired')
    plan_argument.choices += ('minp70-interleaved','fill-workers-check','fill-workers-abba','quality-fill-workers-paired','quality-fetch4-paired','quality-hybrid','quality-hybrid-it-paired','quality-hybrid-minp03-paired','quality-hybrid-spec3-paired')
    plan_argument.choices += ('fetch4-check','fetch4-abba','quality-fetch4-paired','quality-hybrid','quality-hybrid-it-paired','quality-hybrid-minp03-paired','quality-hybrid-spec3-paired')
    plan_argument.choices += ('hybrid-check','hybrid-measure','quality-hybrid','hybrid-it-check','hybrid-it-abba','quality-hybrid-it-paired','hybrid-minp03-check','hybrid-minp03-abba','quality-hybrid-minp03-paired','hybrid-spec3-check','hybrid-spec3-abba','quality-hybrid-spec3-paired')
    plan_argument.choices += ('hybrid-it-check','hybrid-it-abba','quality-hybrid-it-paired','hybrid-minp03-check','hybrid-minp03-abba','quality-hybrid-minp03-paired','hybrid-spec3-check','hybrid-spec3-abba','quality-hybrid-spec3-paired')
    plan_argument.choices += ('hybrid-minp03-check','hybrid-minp03-abba','quality-hybrid-minp03-paired','hybrid-spec3-check','hybrid-spec3-abba','quality-hybrid-spec3-paired')
    plan_argument.choices += ('iq3-spec3-abba','quality-iq3-spec3-paired','phase-profile-check')
    plan_argument.choices += ('qfuse-draft-abba','quality-qfuse-draft-paired')
    plan_argument.choices += ('tsum-draft-abba','quality-tsum-draft-paired')
    plan_argument.choices += ('hc-small-check','hc-small-abba','quality-hc-small-paired')
    plan_argument.choices += ('recovery-clock-check',)
    parser.add_argument('--recovery-expert-cache',type=int,choices=(5000,5500,6500),default=5000,
                        help='Cache limit for the isolated recovery check only')
    parser.add_argument('--recovery-repeats',type=int,choices=(1,3,5),default=1,
                        help='Sequential guarded short requests for recovery only')
    options = parser.parse_args()
    plan = options.plan
    from feature_plans import require_applicable_plan
    require_applicable_plan(plan)
    if (ROOT/'data/benchmarks/.benchmark.lock').exists():
        raise RuntimeError('Benchmark lock exists: verify its owner before starting GPU preflight or loading a model')
    from feature_plans import feature_plan,feature_enabled,FEATURES,ENV_VALUES
    selected_feature=feature_plan(plan)
    if selected_feature and selected_feature[0]=='hc-small':
        parity=json.loads((OUT/'hc-small-window-parity.json').read_text())
        identity=json.loads((OUT/'hc-small-window-source.json').read_text())
        import hashlib
        binary=ROOT/'build-hc-small-window-01403/strata.exe'
        if parity.get('passed') is not True or identity.get('numerical_validated') is not True or not binary.is_file() or hashlib.sha256(binary.read_bytes()).hexdigest()!=identity.get('binary_sha256'):
            raise RuntimeError('HC small-window model gate not passed; no GPU load permitted')
    catalogue_job=get('http://127.0.0.1:8088/catalogue').get('job',{})
    if catalogue_job.get('state') in ('starting','downloading','verifying','packing','registering'):
        raise RuntimeError('Dashboard catalogue preparation is active; no GPU test started')
    live = get('http://127.0.0.1:8088/metrics')['live']
    if live['state'] != 'unloaded' or live.get('queued'):
        raise RuntimeError('Operational engine must be unloaded and idle before GPU preflight')
    # A detected adapter can still be unusable after a driver reset. Never load
    # tens of GiB or repeat a corpus when the runtime's small selftest fails.
    probe_exe = ROOT/('build-hip-control-01403/strata-device.exe' if plan.startswith('source-control-') else 'engine/strata-device.exe')
    probe = subprocess.run([str(probe_exe),'--selftest'],
        cwd=ROOT,capture_output=True,text=True,timeout=60)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'iq3-gpu-preflight.log').write_text(probe.stdout+probe.stderr,encoding='utf-8')
    atomic_json(OUT/'iq3-gpu-preflight.json', {
        'exe': str(probe_exe), 'returncode': probe.returncode,
        'windows_status': f'0x{probe.returncode & 0xffffffff:08x}',
        'completed_at': time.time(), 'model_loaded': False,
    })
    if probe.returncode:
        raise RuntimeError(f'Preflight failed ({probe.returncode & 0xffffffff:#010x}): no model loaded; inspect iq3-gpu-preflight.json and .log')
    cfg = json.loads((ROOT/('strata-hf_85a248b2_q2_0.json' if plan in ('hybrid-check','hybrid-measure','quality-hybrid','hybrid-it-check','hybrid-it-abba','quality-hybrid-it-paired','hybrid-minp03-check','hybrid-minp03-abba','quality-hybrid-minp03-paired','hybrid-spec3-check','hybrid-spec3-abba','quality-hybrid-spec3-paired') else 'strata-iq3_xxs.json')).read_text())
    if selected_feature and selected_feature[0]=='hc-small':
        cfg['exe']=str(ROOT/'build-hc-small-window-01403/strata.exe')
        cfg['lib_dirs']=list(dict.fromkeys([str(ROOT/'engine')]+cfg.get('lib_dirs',[])))
    if selected_feature and selected_feature[0] in ('hip-batch','fill-workers'):
        cfg['exe']=str(ROOT/('build-hip-batch-01403/strata.exe' if selected_feature[0]=='hip-batch' else 'build-fill-workers-01403/strata.exe'))
        cfg['lib_dirs']=list(dict.fromkeys([str(ROOT/'engine')]+cfg.get('lib_dirs',[])))
    if plan.startswith('source-control-'):
        cfg['exe'] = str(ROOT/'build-hip-control-01403/strata.exe')
    if plan not in ('hybrid-check','hybrid-measure','quality-hybrid','hybrid-it-check','hybrid-it-abba','quality-hybrid-it-paired','hybrid-minp03-check','hybrid-minp03-abba','quality-hybrid-minp03-paired','hybrid-spec3-check','hybrid-spec3-abba','quality-hybrid-spec3-paired') and 'iq3_xxs' not in cfg['model_name'].lower():
        raise RuntimeError('Requires IQ3_XXS')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', PORT)) == 0:
            raise RuntimeError('Isolated port already occupied')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')
    resident = ['--pcie-frac','0','--resident-budget-gib','16']
    arms = [('baseline', []), ('dma', ['--pcie-frac','0']),
            ('resident16-dma', resident), ('baseline-confirm', [])] if plan == 'memory' else [
            ('resident16-pool8',resident+['--pool-workers','8']),
            ('resident16-minp03',resident+['--spec-min-p','0.3']),
            ('resident16-confirm',resident)]
    if plan == 'compatibility':
        arms = [('resident16-code-corpus',resident)]
    if plan == 'resident28':
        full = ['--pcie-frac','0','--resident-budget-gib','28']
        arms = [('resident28',full),('resident28-confirm',full)]
    if plan in ('prefill-diagnostic','kv-dma'):
        arms = [(plan,resident + (['--prefill','512'] if plan == 'prefill-diagnostic' else []))]
    if plan == 'short-diagnostic':
        arms = [(plan,['--prefill','256'])]
    if plan == 'recovery-prefill':
        arms = [(plan,['--prefill','256'])]
    if plan == 'recovery-memory':
        arms = [(plan,resident+['--prefill','256'])]
    if plan == 'recovery-clock-check':
        arms = [(plan,resident+['--prefill','128','--expert-cache',str(options.recovery_expert_cache),
                              '--vram-reserve-mib','4096','--max-context','4096',
                              '--kv-resident','4096'])]
    if plan in ('recovery-nosync','stability','chunk512','memory20-check','decode-profile','pcore7-check','gr4-check','spec3-check','static-check','tasks17-check','ram-only-check','context8-check','context16-check','context32-check','source-control-check','full-resident-check'):
        arms = [(plan,resident+['--prefill','256'])]
    if plan == 'chunk512':
        arms = [(plan,resident+['--prefill','512'])]
    if plan == 'chunk-abba':
        arms = [('chunk256-a1',resident+['--prefill','256']),
                ('chunk512-b1',resident+['--prefill','512']),
                ('chunk512-b2',resident+['--prefill','512']),
                ('chunk256-a2',resident+['--prefill','256'])]
    if plan in ('memory20-check','memory20-measure'):
        arms = [(plan,['--pcie-frac','0','--resident-budget-gib','20','--prefill','512'])]
    if plan == 'decode-profile':
        arms = [(plan,resident+['--prefill','512'])]
    if plan in ('pcore7-check','pcore7-measure','gr4-measure','spec3-measure','static-measure','tasks17-measure','ram-only-measure','source-control-measure','full-resident-measure'):
        arms = [(plan,resident+['--prefill','512','--pool-workers','7','--pool-affinity','p-cores'])]
    if plan in ('gr4-check','gr4-measure'):
        arms = [(plan,resident+['--prefill','512'])]
    if plan in ('spec3-check','spec3-measure'):
        arms = [(plan,resident+['--prefill','512','--spec','3'])]
    if plan in ('static-check','static-measure'):
        arms = [(plan,resident+['--prefill','512','--adapt-every','0'])]
    if plan in ('tasks17-check','tasks17-measure'):
        arms = [(plan,resident+['--prefill','512','--pool-tasks','17'])]
    if plan == 'quality-ab':
        arms = [('quality-control',['--prefill','512']),('quality-ram16',resident+['--prefill','512'])]
    if plan == 'quality-memory-only':
        arms = [('quality-pcie-auto-control',['--prefill','512']),('quality-pcie-auto-ram16',['--resident-budget-gib','16','--prefill','512'])]
    if plan in ('ram-only-check','ram-only-measure'):
        arms = [(plan,['--resident-budget-gib','16','--prefill','512'])]
    context_plans = {'context8-check':'8k','context16-check':'16k','context32-check':'32k'}
    if plan in context_plans:
        arms = [(plan,['--resident-budget-gib','16','--prefill','512'])]
    if selected_feature and selected_feature[0] in ('hip-batch','fill-workers'):
        cfg['exe']=str(ROOT/('build-hip-batch-01403/strata.exe' if selected_feature[0]=='hip-batch' else 'build-fill-workers-01403/strata.exe'))
        cfg['lib_dirs']=list(dict.fromkeys([str(ROOT/'engine')]+cfg.get('lib_dirs',[])))
    if plan.startswith('source-control-'):
        arms = [(plan,['--resident-budget-gib','16','--prefill','512'])]
    if plan in ('full-resident-check','full-resident-measure'):
        arms = [(plan,['--prefill','512'])]
    if plan == 'full-resident-abba':
        arms = [('ram16-auto-a1',['--resident-budget-gib','16','--prefill','512']),
                ('full-resident-b1',['--prefill','512']),
                ('full-resident-b2',['--prefill','512']),
                ('ram16-auto-a2',['--resident-budget-gib','16','--prefill','512'])]
    if plan == 'quality-full-resident':
        arms = [('quality-full-ram16',['--resident-budget-gib','16','--prefill','512']),
                ('quality-full-resident',['--prefill','512'])]
    if plan in ('host-last-check','host-last-measure'):
        arms = [(plan,['--resident-budget-gib','16','--prefill','512','--host-core','last'])]
    if plan in ('adapt-lag2-check','adapt-lag2-measure'):
        arms = [(plan,['--resident-budget-gib','16','--prefill','512'])]
    if plan in ('adapt-async-check','adapt-async-measure'):
        arms = [(plan,['--resident-budget-gib','16','--prefill','512','--adapt-async','1'])]
    if plan in ('draft-it-check','draft-it-measure'):
        vocab = ROOT/'data/draft_vocab_it_candidate.bin'
        if not vocab.is_file(): raise RuntimeError('Italian draft candidate missing')
        arms = [(plan,['--resident-budget-gib','16','--prefill','512','--mtp-draft-vocab',str(vocab)])]
    if plan == 'draft-it-abba':
        baseline = ['--resident-budget-gib','16','--prefill','512','--expert-cache','6500','--vram-reserve-mib','2560']
        candidate = baseline + ['--mtp-draft-vocab',str(ROOT/'data/draft_vocab_it_candidate.bin')]
        arms = [('draft-base-a1',baseline),('draft-it-b1',candidate),('draft-it-b2',candidate),('draft-base-a2',baseline)]
    if plan in ('head-profile','tsum-check','tsum-abba'):
        baseline = ['--resident-budget-gib','16','--prefill','512','--expert-cache','6500','--vram-reserve-mib','2560']
        arms = [(plan,baseline)] if plan != 'tsum-abba' else [(name,baseline) for name in ('tsum-base-a1','tsum-b1','tsum-b2','tsum-base-a2')]
    if plan == 'quality-tsum-paired':
        baseline = ['--resident-budget-gib','16','--prefill','512','--expert-cache','6500','--vram-reserve-mib','2560']
        arms = [('quality-tsum-base',baseline),('quality-tsum-it',baseline)]
    if plan == 'quality-draft-paired':
        baseline = ['--resident-budget-gib','16','--prefill','512','--expert-cache','6500','--vram-reserve-mib','2560']
        arms = [('quality-draft-base',baseline),('quality-draft-it',baseline+['--mtp-draft-vocab',str(ROOT/'data/draft_vocab_it_candidate.bin')])]
    if plan in ('profile-learn','profile-learn-abba','quality-profile-paired'):
        baseline = ['--resident-budget-gib','16','--prefill','512','--expert-cache','6500','--vram-reserve-mib','2560']
        learned_path = ROOT/f'data/candidates/expert-profile-{stamp}.bin'
        if plan == 'profile-learn':
            arms = [('profile-learn',baseline+['--expert-profile-save',str(learned_path),'--expert-profile-save-every','0'])]
        else:
            from learn_expert_profile import validate_profile
            reports = sorted(OUT.glob('*-iq3-memory-profile-learn-training.json'))
            if not reports:raise RuntimeError('No learned candidate')
            training = json.loads(reports[-1].read_text())
            if training['status'] != 'complete':raise RuntimeError('Training incomplete')
            learned_path = Path(training['profile_path'])
            details,_ = validate_profile(learned_path)
            if details != training['candidate']:raise RuntimeError('Learned profile changed')
            candidate = baseline+['--expert-profile',str(learned_path)]
            arms = [('profile-base-a1',baseline),('profile-learn-b1',candidate),('profile-learn-b2',candidate),('profile-base-a2',baseline)] if plan == 'profile-learn-abba' else [('quality-profile-base',baseline),('quality-profile-candidate',candidate)]
    OUT.mkdir(parents=True,exist_ok=True)
    if plan in ('pcie55-check','pcie55-abba','quality-pcie55-paired','pcie20-check','pcie20-abba','quality-pcie20-paired'):
        arms = pcie_arms(plan,20 if 'pcie20' in plan else 55)
    if selected_feature:arms=selected_feature[1]
    if plan=='kv-experts-check':
        arms=[('kv-experts-check',['--resident-budget-gib','16','--prefill','512','--expert-cache','7200','--vram-reserve-mib','2560','--kv-resident','8192','--pcie-frac','0.20'])]
    if plan=='minp70-interleaved':
        from feature_plans import BASE
        arms=[('minp70-interleaved',BASE+['--prompt-cache','0','--conversation-cache-mib','0'])]
    if plan in ('hybrid-check','hybrid-measure','quality-hybrid'):
        if cfg.get('catalogue',{}).get('repo')!='shefowl/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-Hybrid-GGUF':raise RuntimeError('Unexpected Hybrid source')
        arms=[(plan,[])]
    campaign_path=ROOT/'data/optimization-campaign.json'
    campaign=dict(id=stamp,plan=plan,model=cfg['model_name'],status='running',completed_arms=0,total_arms=len(arms),started_at=time.time())
    atomic_json(campaign_path,campaign)
    for arm_index,(name, flags) in enumerate(arms):
        campaign.update(variant=name,completed_arms=arm_index,updated_at=time.time())
        atomic_json(campaign_path,campaign)
        live = get('http://127.0.0.1:8088/metrics')['live']
        if live['state'] != 'unloaded' or live.get('queued'):
            raise RuntimeError('Operational engine must be unloaded and idle')
        label = f'{stamp}-iq3-memory-{name}'
        arm = json.loads(json.dumps(cfg))
        from feature_plans import apply_flags
        arm['args']=apply_flags(arm['args'],flags)
        if plan in ('full-resident-check','full-resident-measure') or name in ('full-resident-b1','full-resident-b2','quality-full-resident'):
            arm['args'] += ['--resident-experts']
            arm.setdefault('env',{})['STRATA_RESIDENT_HEADROOM_GIB'] = '8'
        arm.setdefault('env',{}).update(STRATA_DECODE_TIMING='1',STRATA_SPLIT_TIMING='1')
        if plan in ('prefill-diagnostic','short-diagnostic','recovery-prefill','recovery-memory'):
            arm['env']['STRATA_PF_STEP_SYNC'] = '1'
        if plan in ('gr4-check','gr4-measure'):
            arm['env']['STRATA_GR_DOWN_MAX4'] = '1'
        if plan == 'decode-profile':
            arm['env']['STRATA_VERIFY_PROFILE'] = '1'
        if plan == 'head-profile':
            arm['env']['STRATA_VERIFY_PROFILE'] = '1'
        if plan == 'tsum-check' or name in ('tsum-b1','tsum-b2','quality-tsum-it'):
            arm['env']['STRATA_TSUM'] = '1'
        elif plan in ('tsum-abba','quality-tsum-paired'):
            arm['env']['STRATA_TSUM'] = '0'
        if plan in ('adapt-lag2-check','adapt-lag2-measure'):
            arm['env']['STRATA_ADAPT_LAG'] = '2'
        if plan == 'kv-dma':
            arm['env']['STRATA_KV_HOST_DMA'] = '1'
        if selected_feature and selected_feature[0] in FEATURES:arm['env'][FEATURES[selected_feature[0]]]=ENV_VALUES.get(selected_feature[0],('0','1'))[int(feature_enabled(name,selected_feature[0]))]
        if selected_feature and selected_feature[0] in ('lfuse','device-plan','hip-batch','fill-workers','hc-small'):arm['env']['STRATA_QFUSE']='0'
        if plan=='kv-experts-check':arm['env']['STRATA_QFUSE']='0'
        arm['log'] = str(OUT/f'{label}-engine.log')
        path = OUT/f'{label}.json'
        atomic_json(path,arm)
        with (OUT/f'{label}-server.log').open('w',encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable,'serve/server.py','--engine','strata','--config',str(path),
                '--port',str(PORT),'--lazy','--api-monitor','--idle-unload','900'],cwd=ROOT,
                stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                monitor_stop = threading.Event()
                monitor_thread = None
                deadline = time.monotonic()+45
                while True:
                    if server.poll() is not None:
                        raise RuntimeError('Isolated server exited')
                    try:
                        get(URL+'/health')
                        break
                    except OSError:
                        if time.monotonic()>deadline: raise RuntimeError('Readiness timeout')
                        time.sleep(.25)
                monitor_thread = threading.Thread(target=publish_monitor,args=(monitor_stop,label),daemon=True)
                monitor_thread.start()
                if plan == 'recovery-clock-check' or selected_feature or plan in ('kv-experts-check','minp70-interleaved','hybrid-check','hybrid-measure','quality-hybrid') or plan in ('draft-it-abba','quality-draft-paired','head-profile','tsum-check','tsum-abba','quality-tsum-paired','profile-learn','profile-learn-abba','quality-profile-paired','pcie55-check','pcie55-abba','quality-pcie55-paired','pcie20-check','pcie20-abba','quality-pcie20-paired','quality-qfuse-paired','quality-qfuse-pcie20-paired','quality-lfuse-paired','quality-device-plan-paired','quality-hip-batch-paired','quality-minp70-paired','quality-fill-workers-paired','quality-fetch4-paired','quality-hybrid','quality-hybrid-it-paired','quality-hybrid-minp03-paired','quality-hybrid-spec3-paired'):
                    load = urllib.request.Request(URL+'/load',data=b'{}',headers={'Content-Type':'application/json'})
                    with urllib.request.urlopen(load,timeout=1200) as loaded_response:
                        json.load(loaded_response)
                    engine = get(URL+'/metrics')['engine']
                    free_mib = engine.get('vram_free_mib')
                    atomic_json(OUT/f'{label}-startup-margin.json', {
                        'vram_free_mib':free_mib, 'minimum_mib':4096 if plan == 'recovery-clock-check' else 1536,
                        'actual_expert_slots':engine.get('expert_slots'), 'before_prompts':True,
                        'pcie_frac':engine.get('pcie_frac'),
                    })
                    require_startup_vram_margin(engine,4096 if plan == 'recovery-clock-check' else 1536)
                    if selected_feature and selected_feature[0] in ('hip-batch','fill-workers','hc-small'):
                        import re,hashlib
                        log_text=Path(arm['log']).read_text(encoding='utf-8',errors='replace')
                        runtime_match=re.search(r'strata generate: HIP runtime (.+)',log_text)
                        runtime_path=Path(runtime_match.group(1).strip()) if runtime_match else None
                        if runtime_path is None or runtime_path.resolve()!=(Path(arm['exe']).parent/'amdhip64_7.dll').resolve():
                            raise RuntimeError('Experimental HIP runtime path differs; no benchmark permitted')
                        if hashlib.sha256(runtime_path.read_bytes()).digest()!=hashlib.sha256((ROOT/'engine/amdhip64_7.dll').read_bytes()).digest():
                            raise RuntimeError('Experimental HIP runtime identity differs; no benchmark permitted')
                print(f'{label}: measuring',flush=True)
                with (OUT/f'{label}-benchmark.log').open('w',encoding='utf-8') as bench:
                    command = [sys.executable,'tools/benchmark_local.py','--url',URL,'--config',str(path),
                        '--label',label,'--tokens','512','--prompt-set','iq3-memory-v1',
                        '--output',str(ROOT/f'data/benchmarks/{label}.json')]
                    if plan in ('chunk-abba','memory20-measure','pcore7-measure','gr4-measure','spec3-measure','static-measure','tasks17-measure','ram-only-measure','source-control-measure','full-resident-measure'):
                        command[command.index('--tokens')+1] = '256'
                        command[command.index('--prompt-set')+1] = 'iq3-chunk-v1'
                        command += ['--warmup','5','--runs','5']
                    if plan in ('full-resident-abba','draft-it-abba'):
                        command[command.index('--tokens')+1] = '256'
                        command[command.index('--prompt-set')+1] = 'iq3-chunk-v1'
                        command += ['--warmup','5','--runs','5']
                    if selected_feature and plan.endswith('-abba'):
                        command[command.index('--tokens')+1]='256'
                        command[command.index('--prompt-set')+1]='iq3-chunk-v1'
                        command+=['--warmup','5','--runs','5']
                    if plan=='phase-profile-check':
                        command[command.index('--tokens')+1]='256'
                        command[command.index('--prompt-set')+1]='iq3-chunk-v1'
                    if plan=='hybrid-measure':
                        command[command.index('--tokens')+1]='256'
                        command[command.index('--prompt-set')+1]='iq3-chunk-v1'
                        command+=['--warmup','5','--runs','5']
                    if plan=='minp70-interleaved':
                        command[command.index('--tokens')+1]='256'
                        command[command.index('--prompt-set')+1]='iq3-minp-interleaved-v1'
                        command+=['--warmup','5','--runs','6','--interleave-minp']
                        command[command.index('--output')+1]=str(OUT/f'{label}-results.json')
                    if plan == 'short-diagnostic':
                        command = [sys.executable,'tools/verify_iq3_single.py',URL,str(OUT/f'{label}-answer.json')]
                    if plan == 'recovery-clock-check':
                        command = [sys.executable,'tools/benchmark_corpus_guarded.py',
                            '--url',URL,'--model',cfg['model_name'],'--label',label,
                            '--contexts','1k','--repeats',str(options.recovery_repeats),'--max-tokens','128',
                            '--source-dir','src/core','--log',arm['log'],'--out',str(OUT/label)]
                    if plan in ('compatibility','prefill-diagnostic','kv-dma','recovery-prefill','recovery-memory','recovery-nosync','stability','chunk512','memory20-check','decode-profile','pcore7-check','gr4-check','spec3-check','static-check','tasks17-check','ram-only-check','context8-check','context16-check','context32-check','source-control-check','full-resident-check'):
                        command = [sys.executable,'tools/benchmark_corpus_guarded.py',
                            '--url',URL,'--model',cfg['model_name'],'--label',label,'--contexts',('1k' if plan == 'decode-profile' else '1k,4k' if plan in ('compatibility','recovery-prefill','recovery-memory','stability') else '4k'),
                            '--repeats',('10' if plan == 'compatibility' else '5' if plan == 'stability' else '1'),'--max-tokens','256','--source-dir','src/core',
                            '--log',arm['log'],'--out',str(OUT/label)]
                    if plan in context_plans:
                        command[command.index('--contexts')+1] = context_plans[plan]
                        command[command.index('--max-tokens')+1] = '128'
                    if (selected_feature and plan.startswith('quality-')) or plan in ('quality-ab','quality-memory-only','quality-full-resident','quality-draft-paired','quality-tsum-paired','quality-profile-paired','quality-pcie55-paired','quality-pcie20-paired','quality-qfuse-paired','quality-qfuse-pcie20-paired','quality-lfuse-paired','quality-device-plan-paired','quality-hip-batch-paired','quality-minp70-paired','quality-fill-workers-paired','quality-fetch4-paired','quality-hybrid','quality-hybrid-it-paired','quality-hybrid-minp03-paired','quality-hybrid-spec3-paired'):
                        command = [sys.executable,'tools/verify_iq3_tasks.py','--url',URL,'--output',str(OUT/f'{label}-tasks.json')]
                    if plan in ('host-last-measure','adapt-lag2-measure','adapt-async-measure','draft-it-measure'):
                        command[command.index('--tokens')+1] = '256'
                        command[command.index('--prompt-set')+1] = 'iq3-chunk-v1'
                        command += ['--warmup','5','--runs','5']
                    if plan in ('host-last-check','adapt-lag2-check','adapt-async-check','draft-it-check'):
                        command = [sys.executable,'tools/benchmark_corpus_guarded.py',
                            '--url',URL,'--model',cfg['model_name'],'--label',label,'--contexts','4k',
                            '--repeats','1','--max-tokens','256','--source-dir','src/core',
                            '--log',arm['log'],'--out',str(OUT/label)]
                    if plan in ('head-profile','tsum-check','pcie55-check','pcie20-check','qfuse-check','qfuse-pcie20-check','kv-experts-check','lfuse-check','device-plan-check','hip-batch-check','minp70-check','fill-workers-check','fetch4-check','hybrid-check','hybrid-it-check','hybrid-minp03-check','hybrid-spec3-check','hc-small-check'):
                        command = [sys.executable,'tools/benchmark_corpus_guarded.py',
                            '--url',URL,'--model',cfg['model_name'],'--label',label,'--contexts',('1k' if plan == 'head-profile' else '4k'),
                            '--repeats',('2' if plan == 'head-profile' else '1'),'--max-tokens','256','--source-dir','src/core',
                            '--log',arm['log'],'--out',str(OUT/label)]
                    if plan == 'tsum-abba':
                        command[command.index('--tokens')+1] = '256'
                        command[command.index('--prompt-set')+1] = 'iq3-chunk-v1'
                        command += ['--warmup','5','--runs','5']
                    if plan == 'profile-learn':
                        command = [sys.executable,'tools/learn_expert_profile.py','--url',URL,'--config',str(path),
                            '--profile',str(learned_path),'--output',str(OUT/f'{label}-training.json')]
                    if plan == 'profile-learn-abba':
                        command[command.index('--tokens')+1] = '256'
                        command[command.index('--prompt-set')+1] = 'iq3-chunk-v1'
                        command += ['--warmup','5','--runs','5']
                    if plan in ('pcie55-abba','pcie20-abba'):
                        command[command.index('--tokens')+1]='256'
                        command[command.index('--prompt-set')+1]='iq3-chunk-v1'
                        command += ['--warmup','5','--runs','5']
                    result = subprocess.run(command,cwd=ROOT,
                        stdout=bench,stderr=subprocess.STDOUT,timeout=1800)
                print(f'{label}: exit {result.returncode}',flush=True)
                if plan == 'recovery-clock-check' and result.returncode == 0:
                    validate_matrix(OUT/label/label/'matrix.json',options.recovery_repeats)
                if ((selected_feature and plan.startswith('quality-')) or plan in ('quality-ab','quality-memory-only','quality-full-resident','quality-draft-paired','quality-tsum-paired','quality-profile-paired','quality-pcie55-paired','quality-pcie20-paired','quality-qfuse-paired','quality-qfuse-pcie20-paired','quality-lfuse-paired','quality-device-plan-paired','quality-hip-batch-paired','quality-minp70-paired','quality-fill-workers-paired','quality-fetch4-paired','quality-hybrid','quality-hybrid-it-paired','quality-hybrid-minp03-paired','quality-hybrid-spec3-paired')) and result.returncode == 2:
                    task_report = json.loads((OUT/f'{label}-tasks.json').read_text(encoding='utf-8'))
                    if task_report.get('status') != 'complete' or task_report.get('total') != 12:
                        raise RuntimeError('Incomplete task evaluation')
                    print(f'{label}: task failures recorded; no promotion',flush=True)
                elif result.returncode:
                    raise RuntimeError(f'Benchmark subprocess failed: {result.returncode}')
                if plan in ('host-last-check','adapt-lag2-check','adapt-async-check','draft-it-check'):
                    validate_matrix(OUT/label/label/'matrix.json',1)
                    subprocess.run([sys.executable,'tools/verify_iq3_live.py','--url',URL,
                        '--output',str(OUT/f'{label}-quality.json')],cwd=ROOT,check=True,timeout=1200)
                if plan in ('head-profile','tsum-check','pcie55-check','pcie20-check','qfuse-check','qfuse-pcie20-check','kv-experts-check','lfuse-check','device-plan-check','hip-batch-check','minp70-check','fill-workers-check','fetch4-check','hybrid-check','hybrid-it-check','hybrid-minp03-check','hybrid-spec3-check','hc-small-check'):
                    validate_matrix(OUT/label/label/'matrix.json',2 if plan == 'head-profile' else 1)
                    if plan in ('tsum-check','pcie55-check','pcie20-check','qfuse-check','qfuse-pcie20-check','kv-experts-check','lfuse-check','device-plan-check','hip-batch-check','minp70-check','fill-workers-check','fetch4-check','hybrid-check','hybrid-it-check','hybrid-minp03-check','hybrid-spec3-check','hc-small-check'):
                        smoke=[sys.executable,'tools/verify_iq3_live.py','--url',URL,'--output',str(OUT/f'{label}-quality.json')]
                        if plan in ('hybrid-check','hybrid-it-check','hybrid-minp03-check','hybrid-spec3-check'):smoke+=['--expected-model',cfg['model_name']]
                        subprocess.run(smoke,cwd=ROOT,check=True,timeout=1200)
                if plan in ('compatibility','prefill-diagnostic','kv-dma','recovery-prefill','recovery-memory','recovery-nosync','stability','chunk512','memory20-check','decode-profile','pcore7-check','gr4-check','spec3-check','static-check','tasks17-check','ram-only-check','context8-check','context16-check','context32-check','source-control-check','full-resident-check'):
                    validate_matrix(OUT/label/label/'matrix.json',20 if plan == 'compatibility' else 10 if plan == 'stability' else 2 if plan in ('recovery-prefill','recovery-memory') else 1)
                if result.returncode == 0 and name in ('resident16-confirm','resident28-confirm','recovery-nosync','memory20-check','pcore7-check','gr4-check','spec3-check','static-check','tasks17-check','ram-only-check','context8-check','context16-check','context32-check','source-control-check','full-resident-check'):
                    subprocess.run([sys.executable,'tools/verify_iq3_live.py','--url',URL,
                        '--output',str(OUT/f'{label}-quality.json')],cwd=ROOT,check=True,timeout=1200)
            finally:
                monitor_stop.set()
                if monitor_thread is not None:
                    monitor_thread.join(timeout=5)
                # Stop this server and its engine descendants; never target the operational service.
                if server.poll() is None:
                    subprocess.run(['taskkill','/PID',str(server.pid),'/T','/F'],capture_output=True)
                    server.wait(timeout=15)
                time.sleep(2)
        campaign.update(completed_arms=arm_index+1,updated_at=time.time())
        atomic_json(campaign_path,campaign)

    if plan == 'full-resident-abba':
        # Publish only after all four arms succeeded and their raw reports pass
        # the paired-protocol validation. The operational config is unaffected.
        from summarize_full_resident_abba import summarize
        from publish_performance_evidence import main as publish_evidence
        summarize(stamp)
        publish_evidence()
    elif plan == 'draft-it-abba':
        from summarize_draft_abba import summarize
        from publish_performance_evidence import main as publish_evidence
        summarize(stamp)
        publish_evidence()
    elif plan == 'tsum-abba':
        from summarize_tsum_abba import summarize
        from publish_performance_evidence import main as publish_evidence
        summarize(stamp)
        publish_evidence()
    elif plan == 'profile-learn-abba':
        from summarize_learned_profile import summarize
        from publish_performance_evidence import main as publish_evidence
        summarize(stamp)
        publish_evidence()
    elif selected_feature and plan.endswith('-abba'):
        from summarize_feature import summarize_abba
        summarize_abba(stamp,selected_feature[0])
    elif selected_feature and plan.startswith('quality-'):
        from summarize_feature import summarize_quality
        summarize_quality(stamp,selected_feature[0])
    elif plan in ('pcie55-abba','pcie20-abba'):
        from summarize_pcie_abba import summarize
        summarize(stamp,20 if 'pcie20' in plan else 55)
    elif plan in ('quality-pcie55-paired','quality-pcie20-paired'):
        from summarize_pcie_quality import summarize
        summarize(stamp,20 if 'pcie20' in plan else 55)
    elif plan == 'quality-profile-paired':
        from summarize_profile_quality import summarize
        summarize(stamp)
    elif plan == 'head-profile':
        from summarize_head_profile import summarize
        summarize(stamp)
    elif plan == 'quality-tsum-paired':
        from summarize_tsum_quality import summarize
        summarize(stamp)
    elif plan == 'quality-draft-paired':
        from summarize_draft_quality import summarize
        from publish_performance_evidence import main as publish_evidence
        summarize(stamp)
        publish_evidence()
    elif plan in ('adapt-lag2-measure','adapt-async-measure','draft-it-measure'):
        from publish_performance_evidence import main as publish_evidence
        publish_evidence()

    from publish_performance_evidence import main as publish_evidence
    publish_evidence()
    campaign.update(status='complete',finished_at=time.time(),updated_at=time.time())
    atomic_json(campaign_path,campaign)

if __name__ == '__main__':
    from serve.gpu_lease import GpuLease
    with GpuLease(ROOT,'iq3-memory-cli'):
        try:main()
        except BaseException as error:
            path=ROOT/'data/optimization-campaign.json'
            if path.exists():
                row=json.loads(path.read_text())
                if row.get('status')=='running':
                    row.update(status='failed',error=str(error),updated_at=time.time())
                    atomic_json(path,row)
            raise
