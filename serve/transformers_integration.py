"""Official release metadata and environment-scoped Transformers inventory."""
import json
import re
import urllib.request


def installed_environments(environments):
    rows=[]
    for environment in environments:
        for package in environment.get('packages',[]):
            if package.get('name','').lower()=='transformers':
                rows.append({'environment':environment['name'],'python':environment.get('python'),
                             'python_version':environment.get('python_version'),'version':package['version'],
                             'dependency_health':environment.get('dependency_health',{}).get('state'),
                             'update_check':environment.get('update_check',{}).get('state')})
    return rows


def release_from_metadata(data):
    info=data.get('info') or {};version=info.get('version','')
    if info.get('name','').lower()!='transformers' or not re.fullmatch(r'\d+\.\d+\.\d+',version):
        raise ValueError('Official stable Transformers package identity mismatch')
    urls=data.get('urls') or []
    dates=[row.get('upload_time_iso_8601') for row in urls if row.get('upload_time_iso_8601')]
    return {'id':'transformers','name':'Transformers','version':version,'repository':'huggingface/transformers',
            'url':'https://github.com/huggingface/transformers',
            'release_url':'https://pypi.org/project/transformers/'+version+'/',
            'released_at':min(dates) if dates else None,'state':'available','assets':[],
            'update_method':'isolated_python_dependencies','requires_python':info.get('requires_python'),
            'runtime_validated':False,'notes':'Official stable PyPI release. Compatibility with PyTorch, Unsloth, PEFT and TRL must be resolved and validated in an isolated environment.'}


def latest():
    request=urllib.request.Request('https://pypi.org/pypi/transformers/json',headers={'User-Agent':'StargateLab-Transformers-Updates'})
    with urllib.request.urlopen(request,timeout=15) as response:raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('Transformers metadata size limit')
    return release_from_metadata(json.loads(raw))


def installed_metadata(environments):
    rows=installed_environments(environments)
    active=next((row for row in rows if row['environment']=='Unsloth'),None)
    return {'installed_version':active['version'] if active else None,
            'installed_source':'python_distribution_metadata','installed_environments':rows,
            'inference_environment':'Unsloth','version_comparable':bool(active)}


def runtime_versions():
    """Record the interpreter actually running a training job, without importing GPU libraries."""
    import importlib.metadata,sys
    versions={}
    for name in ('transformers','torch','tokenizers','safetensors','accelerate','peft','trl','unsloth'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    return {'python':sys.version.split()[0],'packages':versions}
