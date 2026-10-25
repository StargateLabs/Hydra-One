import json,time
from pathlib import Path
from serve.update_center import UpdateCenter
root=Path.cwd();center=UpdateCenter(root)
# CPU package exercises the updater without invoking the GPU runtime.
center.operational_idle=lambda: not (root/'data/.gpu-campaign.lock').exists()
asset=next(a for c in center.result['components'] if c['id']=='llama.cpp' for a in c['assets'] if a['name'].endswith('windows-x64-cpu.zip'))
center.stage('llama.cpp',asset['id'])
while center.job['state']=='downloading':time.sleep(.5)
if center.job['state']!='staged':raise RuntimeError(center.job)
center.prepare()
model=next(root.glob('output/model-exports/**/*.gguf'))
center.validate(str(model))
while center.job['state']=='validating':time.sleep(.5)
(root/'output/verification/update-real-candidate.json').write_text(json.dumps(center.status(),indent=2),encoding='utf-8')
if center.job['state']!='validated':raise RuntimeError(center.job.get('error'))
print('Official CPU candidate downloaded, extracted and answered:',center.job['result']['validation']['response'])
