"""One owned, serial software-suite process under the common HYDRA lab admission."""
import argparse, os, sys, time
from pathlib import Path
from serve.hydra_execution_v10 import Reservation, guarded_popen

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--log',required=True);parser.add_argument('modules',nargs='+');args=parser.parse_args()
 if os.environ.get('HYDRA_LAB_MODE')!='1':raise SystemExit('HYDRA_LAB_MODE=1 required')
 if not all(name.startswith('serve.test_hydra_') and name.replace('_','').replace('.','').isalnum() for name in args.modules):raise SystemExit('explicit laboratory software modules required')
 path=Path(args.log);path.parent.mkdir(parents=True,exist_ok=True)
 lease=Reservation({'run_id':'software-'+str(time.time_ns()),'backend':'DUMMY_CPU','profile':'serial-software-regression','workload':args.modules}).acquire()
 with path.open('xb') as output:
  child=guarded_popen([sys.executable,'-m','unittest',*args.modules],stdout=output,stderr=output)
  try:code=child.wait(timeout=60)
  except BaseException:
   child.terminate();child.wait(timeout=3);lease.transition('CLEANUP_BLOCKED');raise
 lease.release(persisted=path.is_file());print(path.read_text(encoding='utf8',errors='replace'));return code
if __name__=='__main__':raise SystemExit(main())
