"""Re-run the advanced TRL methods and refresh the validation manifest.

The manifest records the fingerprint of the sources that actually ran. Any change to
tools/train_trl_advanced.py, tools/train_local_lora.py or serve/training_options.py
invalidates the previous proof, so this tool re-runs every method and rewrites the
manifest from the fresh reports. Old reports are never reused.
"""
import hashlib,json,subprocess,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from serve.advanced_training_runtime import source_fingerprint
from serve.python_inference_update import environment_fingerprint
METHODS=('dpo','grpo','kto','reward')
FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0)
BASE=ROOT.parent/'Strata-data/models/optional/HuggingFaceTB--SmolLM2-135M-Instruct/12fd25f77366fa6b3b4b768ec3050bf629380bac'
DATASETS={
    'dpo':{'train':[{'prompt':'hello','chosen':' world','rejected':' goodbye'}],
           'validation':[{'prompt':'hi','chosen':' there','rejected':' never'}]},
    'reward':{'train':[{'prompt':'hello','chosen':' world','rejected':' goodbye'}],
              'validation':[{'prompt':'hi','chosen':' there','rejected':' never'}]},
    'grpo':{'train':[{'prompt':'hello','target':'world'}],
            'validation':[{'prompt':'hi','target':'there'}]},
    'kto':{'train':[{'prompt':'Hello','completion':'Hi there','label':True},
                    {'prompt':'Question','completion':'Never help','label':False}],
           'validation':[{'prompt':'Greetings','completion':'Welcome friend','label':True},
                         {'prompt':'Request','completion':'No answer','label':False}]},
}

def write_jsonl(path,rows):
    path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8')
    return path

def run(method,python):
    folder=ROOT/'output/verification/open-plans-20261012'/('advanced-'+method+'-'+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    rows=DATASETS[method]
    train=write_jsonl(folder/'train.jsonl',rows['train'])
    validation=write_jsonl(folder/'validation.jsonl',rows['validation'])
    report=folder/'result'/'workflow.json'
    command=[str(python),'-X','utf8','tools/train_trl_advanced.py','--method',method,
        '--model',str(BASE.resolve()),'--train',str(train),'--validation',str(validation),
        '--output',str(folder/'result'),'--steps','1','--length','32']
    completed=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=3600,creationflags=FLAGS)
    (folder/'stdout.log').write_text(completed.stdout,encoding='utf-8')
    (folder/'stderr.log').write_text(completed.stderr,encoding='utf-8')
    if completed.returncode or not report.is_file():
        raise RuntimeError(method+' failed: '+(completed.stderr or completed.stdout)[-2000:])
    return folder,report

def verify(report,method):
    workflow=json.loads(report.read_text(encoding='utf-8'))
    if workflow.get('status')!='complete':raise RuntimeError(method+' workflow not complete')
    if workflow.get('method')!=method:raise RuntimeError(method+' workflow method mismatch')
    if workflow.get('options',{}).get('device')!='cpu':raise RuntimeError(method+' ran off CPU')
    if workflow.get('parameter_update_detected') is not True:raise RuntimeError(method+' adapter parameters did not update')
    parity='export_scores_equal' if method=='reward' else 'export_greedy_tokens_equal'
    if workflow.get(parity) is not True:raise RuntimeError(method+' export parity not verified')
    if workflow.get('adopted') is not False:raise RuntimeError(method+' adopted a proof')
    export=Path(workflow['merged'])
    if not (export/'model.safetensors').is_file():raise RuntimeError(method+' merged export missing')
    return workflow

def main():
    python=(ROOT/'data/trl-advanced-runtime/Scripts/python.exe').resolve()
    if not python.is_file():raise RuntimeError('Isolated TRL runtime missing')
    if not BASE.is_dir():raise RuntimeError('Local 135M fixture model missing')
    metadata=json.loads((ROOT/'data/trl-advanced-runtime/provenance.json').read_text(encoding='utf-8'))
    source_python=(Path(metadata['source_site']).parent.parent/'Scripts/python.exe').resolve()
    if not source_python.is_file():raise RuntimeError('Shared training environment missing')
    source=source_fingerprint(ROOT)
    environment=environment_fingerprint(python);shared=environment_fingerprint(source_python)
    summary={}
    for method in METHODS:
        folder,report=run(method,python)
        workflow=verify(report,method)
        if workflow.get('source_sha256')!=source:raise RuntimeError(method+' ran with different sources')
        summary[method]={'report':str(report),'passed':True,
            'scope':'One CPU step on local trained 135M model; export parity only, no quality improvement claim'}
        print(method,'verified')
    manifest=dict(source_sha256=source,environment_sha256=environment,shared_environment_sha256=shared,
        methods={method:{'report':entry['report'],'sha256':hashlib.sha256(Path(entry['report']).read_bytes()).hexdigest()}
            for method,entry in summary.items()})
    (ROOT/'data/trl-advanced-runtime/validation.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    output=ROOT/'output/verification/open-plans-20261012/advanced-training-real.json'
    output.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print('Validation manifest refreshed for',len(METHODS),'methods')

if __name__=='__main__':main()
