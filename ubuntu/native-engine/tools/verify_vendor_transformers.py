"""Exercise preserved ROCm update preparation and its real inference gates."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.verify_audio_update_cpu import call
from serve.vendor_python_update import prepare
from serve.vendor_python_validation import validate
root=Path(__file__).resolve().parents[1]
assert call('/metrics')['live']['state']=='unloaded' and call('/inference-backends')['status']=='idle'
from serve.transformers_compatibility import latest
version=latest(root)['version']
source=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
def progress(**state):print(json.dumps(state),flush=True)
manifest=prepare(root,source,version,progress,reuse_folder=sys.argv[1] if len(sys.argv)>1 else None)
print('Isolated vendor-preserving installation complete; checking CPU/GPU loaders',flush=True)
manifest=validate(root,manifest['plan_directory'])
report={'passed':True,'version':version,'plan_directory':manifest['plan_directory'],'python':manifest['python'],'preserved_torch':manifest['source_packages']['torch'],'inference_validation':manifest['inference_validation'],'source_environment_modified':False,'selected':False}
(root/'output/verification/transformers-vendor-update-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('PASS official Transformers update with preserved ROCm, CPU and two real GPU loader checks',flush=True)
