"""Official PyTorch releases and exact environment build provenance, without importing torch."""
import json
import re
import urllib.request


def torch_build(version):
    suffix=version.partition('+')[2].lower()
    flavor='cpu' if suffix=='cpu' else 'cuda' if re.match(r'^cu\d+',suffix) else 'rocm' if 'rocm' in suffix else 'unknown'
    return dict(version=version,base_version=version.partition('+')[0],build_suffix=suffix or None,
                flavor=flavor,flavor_source='distribution_version_metadata',
                requires_vendor_channel=flavor=='rocm',
                index_url='https://download.pytorch.org/whl/'+suffix if flavor in ('cpu','cuda') else None,
                channel_note='Preserve the exact installed ROCm build and AMD or PyTorch vendor wheel source; generic PyPI latest does not validate this channel.' if flavor=='rocm' else 'Unsuffixed package metadata does not prove CPU, CUDA or ROCm compatibility.' if flavor=='unknown' else 'Retain this build flavor in an isolated dependency candidate; validate drivers and runtime separately.')


def installed_environments(environments):
    rows=[]
    for environment in environments:
        for package in environment.get('packages',[]):
            if package.get('name','').lower()=='torch':
                rows.append(dict(environment=environment['name'],python=environment.get('python'),
                                 python_version=environment.get('python_version'),
                                 dependency_health=environment.get('dependency_health',{}).get('state'),
                                 update_check=environment.get('update_check',{}).get('state'),
                                 **torch_build(package['version'])))
    return rows


def installed_metadata(environments):
    rows=installed_environments(environments)
    active=next((row for row in rows if row['environment']=='Unsloth'),None)
    return dict(installed_version=active['version'] if active else None,
                installed_source='python_distribution_metadata',installed_environments=rows,
                inference_environment='Unsloth',version_comparable=False,
                automatic_update_supported=False,update_block_reason='build_channel_not_verified',
                flavor=active['flavor'] if active else None,flavor_compatibility_verified=False)


def release_from_metadata(data):
    info=data.get('info') or {};version=info.get('version','')
    if info.get('name','').lower()!='torch' or not re.fullmatch(r'\d+\.\d+\.\d+',version):
        raise ValueError('Official stable PyTorch package identity mismatch')
    dates=[row['upload_time_iso_8601'] for row in data.get('urls',[]) if row.get('upload_time_iso_8601')]
    return dict(id='pytorch',name='PyTorch',package='torch',version=version,repository='pytorch/pytorch',
                url='https://github.com/pytorch/pytorch',release_url='https://pypi.org/project/torch/'+version+'/',
                released_at=min(dates) if dates else None,state='available',assets=[],
                update_method='isolated_python_dependencies',requires_python=info.get('requires_python'),
                runtime_validated=False,flavor_compatibility_verified=False,
                installation_documentation_url='https://pytorch.org/get-started/locally/',
                notes='Official stable torch PyPI release. Preserve CPU/CUDA/ROCm build flavor and platform-specific wheel source. Resolve Torch, torchvision, torchaudio, Transformers, Unsloth, PEFT and TRL together in an isolated candidate; do not overwrite working environments.')


def latest():
    request=urllib.request.Request('https://pypi.org/pypi/torch/json',headers={'User-Agent':'StargateLab-PyTorch-Updates'})
    with urllib.request.urlopen(request,timeout=15) as response:raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('PyTorch metadata size limit')
    return release_from_metadata(json.loads(raw))
