"""Build and exercise the real persistent worker helper without loading a model."""
import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
cache={}
for line in (ROOT/'build-hip-control-01403/CMakeCache.txt').read_text().splitlines():
 if ':' in line and '=' in line and not line.startswith(('#','//')):
  key,rest=line.split(':',1);cache[key]=rest.split('=',1)[1]
exe=ROOT/'output/verification/fill-workers-parity.exe'
cmd=[cache['CMAKE_CXX_COMPILER'],'-std=c++17','-O2',str(ROOT/'tools/native/persistent_fill_workers_test.cpp'),'-o',str(exe)]
r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=120)
(ROOT/'output/verification/fill-workers-build.log').write_text(r.stdout+r.stderr,encoding='utf-8')
if r.returncode:raise RuntimeError('Worker helper compile failed')
r=subprocess.run([str(exe)],cwd=ROOT,capture_output=True,text=True,timeout=30)
(ROOT/'output/verification/fill-workers-parity.log').write_text(r.stdout+r.stderr,encoding='utf-8')
if r.returncode:raise RuntimeError('Worker helper parity failed')
data=json.loads(r.stdout)
if data.get('passed') is not True or data.get('cases')!=2808:raise RuntimeError('Incomplete helper parity')
(ROOT/'output/verification/fill-workers-parity.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
print('2808 worker helper cases passed; no model tested')
