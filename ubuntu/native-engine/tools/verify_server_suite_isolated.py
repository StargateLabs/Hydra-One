"""Run server tests in a separate source copy, preserving the operational model."""
import hashlib,json,os,shutil,subprocess,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    target=ROOT/'output/verification'/('server-suite-isolated-'+uuid.uuid4().hex)
    target.mkdir()
    (target/'output/verification').mkdir(parents=True)
    (target/'output/verification/test-temp').mkdir()
    (target/'tmp').mkdir()
    for path in ROOT.glob('*.py'):shutil.copyfile(path,target/path.name)
    for name in ('serve','tools'):
        shutil.copytree(ROOT/name,target/name,ignore=shutil.ignore_patterns('__pycache__','*.bak','*.bak-*','node_modules','venv','.venv'))
    if (ROOT/'docs').is_dir():shutil.copytree(ROOT/'docs',target/'docs',ignore=shutil.ignore_patterns('*.pdf','paper'))
    metadata=ROOT/'output/research/hf-models-20261009'
    if metadata.is_dir():
        destination=target/'output/research/hf-models-20261009';destination.mkdir(parents=True)
        for path in metadata.glob('*.json'):
            if path.stat().st_size<=4*1024**2:shutil.copyfile(path,destination/path.name)
    env={**os.environ,'PYTHONPATH':str(target),'CUDA_VISIBLE_DEVICES':'-1','HIP_VISIBLE_DEVICES':'-1','ROCR_VISIBLE_DEVICES':'-1',
         'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1',
         'TEMP':str(target/'tmp'),'TMP':str(target/'tmp'),'TMPDIR':str(target/'tmp')}
    env.pop('STRATA_PYTHON_CANDIDATE_PROBE',None)
    fingerprint=hashlib.sha256()
    for path in sorted(target.rglob('*.py')):
        fingerprint.update(path.relative_to(target).as_posix().encode('utf-8'))
        fingerprint.update(b'\0');fingerprint.update(path.read_bytes())
    log=target/'server-suite.log';started=time.monotonic();error=None;exit_code=None
    with log.open('w',encoding='utf-8') as output:
        try:
            result=subprocess.run([sys.executable,'-m','unittest','discover','-s','serve','-p','test_*.py'],cwd=target,env=env,stdout=output,stderr=subprocess.STDOUT,timeout=240)
            exit_code=result.returncode
        except subprocess.TimeoutExpired:
            error='Suite exceeded the 240-second limit';exit_code=124
        except OSError as exc:
            error=str(exc);exit_code=1
    report={'scope':'Exact serve/tools source copies with separate project state, CPU-only environment; operational model untouched','directory':str(target),'source_sha256':fingerprint.hexdigest(),'python':sys.executable,'exit_code':exit_code,'error':error,'seconds':time.monotonic()-started,'log':str(log),'completed_at':time.time()}
    (target/'server-suite.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (ROOT/'output/verification/server-isolated-current.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Isolated suite exit:',exit_code,'log:',log)
    if exit_code:raise SystemExit(exit_code)
if __name__=='__main__':main()
