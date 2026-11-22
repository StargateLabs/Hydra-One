"""Run the production Soup update preparation against local idle dashboards."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serve.soup_update import prepare,VERSION
from tools.verify_audio_update_cpu import call
root=Path(__file__).resolve().parents[1]
assert call('/metrics')['live']['state']=='unloaded'
assert call('/inference-backends')['status']=='idle'
def progress(**state):print(json.dumps(state),flush=True)
result=prepare(root,VERSION,progress)
print(json.dumps(result),flush=True)
