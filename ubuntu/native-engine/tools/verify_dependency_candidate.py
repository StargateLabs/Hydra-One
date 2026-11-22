import json,time
from pathlib import Path
from serve.update_center import UpdateCenter
root=Path.cwd();center=UpdateCenter(root);center.operational_idle=lambda:not(root/'data/.gpu-campaign.lock').exists()
center.dependency_plan('Strata')
while center.job['state']=='resolving':time.sleep(.5)
print('Resolver:',center.job['state'],flush=True)
if center.job['state']=='resolved':
    center.install_dependencies()
    while center.job['state']=='installing_candidate':time.sleep(.5)
    print('Candidate:',center.job['state'],flush=True)
(root/'output/verification/dependency-candidate-real.json').write_text(json.dumps(center.status(),indent=2),encoding='utf-8')
if center.job.get('error'):print(center.job['error'])
