"""Persist targeted CPU checks with immutable per-run reports and logs."""
import json,os,subprocess,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=ROOT/'output/verification'/('implementation-checks-'+uuid.uuid4().hex);folder.mkdir(parents=True)
    log=folder/'checks.log';started=time.monotonic()
    env={**os.environ,'CUDA_VISIBLE_DEVICES':'-1','HIP_VISIBLE_DEVICES':'-1','ROCR_VISIBLE_DEVICES':'-1'}
    modules=['serve.test_update_center','serve.test_verification_history','serve.test_benchmark_lab','serve.test_whisper_pairing','serve.test_native_libraries','serve.test_benchmark_state','serve.test_optional_workflow','serve.test_optional_http']
    with log.open('w',encoding='utf-8') as output:
        result=subprocess.run([sys.executable,'-m','unittest',*modules],cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,timeout=60)
    report=dict(scope='CPU software checks: updates, verification history, benchmark persistence and native library pairing; no model throughput',modules=modules,log=str(log),exit_code=result.returncode,seconds=time.monotonic()-started,completed_at=time.time())
    (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (ROOT/'output/verification/implementation-checks-current.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(log.read_text(encoding='utf-8'));raise SystemExit(result.returncode)
if __name__=='__main__':main()
