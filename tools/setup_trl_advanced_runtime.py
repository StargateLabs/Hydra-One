"""Create an isolated TRL overlay; existing validated environments are read-only."""
import json,subprocess,venv
from pathlib import Path
root=Path(__file__).resolve().parents[1];folder=root/'data/trl-advanced-runtime';venv.EnvBuilder(with_pip=True).create(folder)
proof=json.loads((root/'output/verification/open-plans-20261012/training-candidate-current.json').read_text())['cpu']
manifest=json.loads((Path(proof['report']).parents[2]/'environment-manifest.json').read_text())
source=Path(manifest['python']).parent.parent/'Lib/site-packages';site=folder/'Lib/site-packages'
if not source.is_dir():raise RuntimeError('Validated source dependency closure missing')
(site/'readonly-training-dependencies.pth').write_text(str(source)+'\n',encoding='utf-8')
python=folder/'Scripts/python.exe';flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
subprocess.run([str(python),'-m','pip','install','--no-deps','trl==0.29.1','datasets>=4.7,<5','Pillow==11.3.0'],check=True,creationflags=flags)
check=subprocess.run([str(python),'-m','pip','check'],capture_output=True,text=True,creationflags=flags)
print(check.stdout+check.stderr)
if check.returncode:raise RuntimeError('Advanced dependency compatibility failed')
subprocess.run([str(python),'-c','from trl import DPOTrainer,DPOConfig,GRPOTrainer,GRPOConfig;print("Advanced TRL imports OK")'],check=True,creationflags=flags)
(folder/'provenance.json').write_text(json.dumps({'source_site':str(source),'runtime':str(python),'trl':'0.29.1','source_modified':False,'dependency_health':'healthy'},indent=2))
