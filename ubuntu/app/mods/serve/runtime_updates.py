"""Read-only runtime discovery and bounded checks against official release sources.

System interpreters are never overwritten: changing them also requires rebuilding
dependent environments and native Node extensions.
"""
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


def version_tuple(value):
    match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:\.windows\.\d+)?',str(value or ''))
    return tuple(map(int,match.groups())) if match else None


def version_state(installed,available):
    old,new=version_tuple(installed),version_tuple(available)
    if old is None or new is None:return 'unavailable'
    return 'available' if new>old else 'ahead' if old>new else 'current'


def select_node_release(releases,installed):
    version=version_tuple(installed)
    candidates=[row for row in releases if version_tuple(row.get('version')) and
                version and version_tuple(row['version'])[0]==version[0]]
    return max(candidates,key=lambda row:version_tuple(row['version'])) if candidates else None


def official_read(url):
    request=urllib.request.Request(url,headers={'User-Agent':'StargateLab-runtime-check','Accept':'application/json'})
    with urllib.request.urlopen(request,timeout=8) as response:
        content=response.read(2*1024*1024+1)
    if len(content)>2*1024*1024:raise ValueError('Runtime release response too large')
    return content.decode('utf-8')


def probe(command):
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=5,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:return None
        match=re.search(r'(?<!\d)v?(\d+\.\d+\.\d+(?:\.windows\.\d+)?)\b',result.stdout[:4096])
        return match.group(1) if match else None
    except (OSError,subprocess.SubprocessError):return None


def inventory(root,environments,native):
    rows=[]
    for environment in environments:
        executable=environment.get('python')
        rows.append({'id':'python:'+environment['name'],'name':'Python · '+environment['name'],
                     'installed_version':environment.get('python_version'),'path':executable,
                     'used_by':[environment['name']],'family':'python','url':'https://www.python.org/downloads/',
                     'update_method':'rebuild_environment','available_version':None})
    for name,command,owners,url in [
        ('Node.js','node',['OpenCode','DeepSeek Harness','TrueForge','MCP','Context-mode'],'https://nodejs.org/en/download'),
        ('uv','uv',['Hermes','Isolated Python environments'],'https://docs.astral.sh/uv/getting-started/installation/'),
        ('Git','git',['Harness repositories','Engine sources'],'https://git-scm.com/downloads')]:
        binary=shutil.which(command)
        if binary:
            rows.append({'id':command,'name':name,'installed_version':probe([binary,'--version']),
                         'path':binary,'family':command,'used_by':owners,'url':url,
                         'available_version':None,'update_method':'official_installer'})
    # Hermes can use a sealed interpreter outside PATH and the dashboard venv.
    try:
        from serve.hermes_integration import runtime
        hermes=runtime(root)
        if hermes:
            binary=str(hermes['python'])
            rows.append({'id':'python:Hermes','name':'Python · Hermes','installed_version':probe([binary,'--version']),
                         'path':binary,'family':'python','used_by':['Hermes'],'url':'https://www.python.org/downloads/',
                         'available_version':None,'update_method':'rebuild_environment'})
    except (OSError,ValueError,RuntimeError):pass
    releases={}
    for row in rows:
        try:
            family=row['family'];installed=row['installed_version']
            if family=='node':
                if family not in releases:releases[family]=json.loads(official_read('https://nodejs.org/dist/index.json'))
                release=select_node_release(releases[family],installed)
                if release:
                    row.update(available_version=release['version'].lstrip('v'),channel='same_major',
                               url='https://nodejs.org/en/download/archive/'+release['version'])
            elif family=='python':
                if family not in releases:releases[family]=official_read('https://www.python.org/ftp/python/')
                current=version_tuple(installed)
                available=[version_tuple(version) for version in re.findall(r'href="(\d+\.\d+\.\d+)/"',releases[family])]
                available=[version for version in available if current and version[:2]==current[:2]]
                if available:row.update(available_version='.'.join(map(str,max(available))),channel='same_minor')
            else:
                repository={'uv':'astral-sh/uv','git':'git-for-windows/git'}[family]
                release=json.loads(official_read('https://api.github.com/repos/'+repository+'/releases/latest'))
                if release.get('prerelease') or release.get('draft'):raise ValueError('Stable release unavailable')
                row.update(available_version=release['tag_name'].lstrip('v'),url=release['html_url'])
            row['state']=version_state(installed,row.get('available_version'))
        except Exception as error:row.update(state='unavailable',error=str(error)[:250])
    node_row=next((row for row in rows if row['family']=='node'),None)
    if node_row:
        manifest=Path(node_row['path']).parent/'node_modules/npm/package.json'
        try:
            installed=json.loads(manifest.read_text(encoding='utf-8'))['version']
            release=select_node_release(releases.get('node',[]),node_row['installed_version']) or {}
            available=release.get('npm')
            rows.append({'id':'npm','name':'npm','family':'npm','installed_version':installed,
                         'available_version':available,'state':version_state(installed,available),
                         'path':str(manifest),'used_by':['Harness updates','MCP updates'],
                         'update_method':'owning_engine_bundle','url':node_row['url']})
        except (OSError,ValueError,KeyError):pass
    for environment in environments:
        for package in environment.get('packages',[]):
            if package['name'].lower() in ('torch','onnxruntime','onnxruntime-gpu','transformers','tokenizers','safetensors','accelerate','peft','trl'):
                rows.append({'id':package['name']+':'+environment['name'],
                             'name':package['name']+' · '+environment['name'],'family':'python_package',
                             'installed_version':package['version'],'available_version':package.get('available_version'),
                             'state':package.get('update_state','unavailable'),
                             'used_by':[environment['name']],'update_method':'python_dependency_plan',
                             'environment':environment['name'],'url':'https://pypi.org/project/'+package['name']+'/'})
    # Native GPU/OpenMP/VC++ dependencies must follow the exact owning bundle.
    groups={}
    for library in native.get('libraries',[]):
        name=library['name'].lower()
        family=('ROCm / HIP' if any(part in name for part in ('hip','rocblas','amd')) else
                'CUDA' if any(part in name for part in ('cuda','cublas','nvrtc')) else
                'OpenMP' if 'omp' in name else 'Microsoft C++' if name.startswith(('vcruntime','msvcp')) else None)
        if family:groups.setdefault((family,library['owner']),[]).append(library)
    for (family,owner),libraries in groups.items():
        rows.append({'id':family+':'+owner,'name':family+' · '+owner,'family':'native',
                     'installed_version':None,'available_version':None,'state':'bundled','used_by':[owner],
                     'libraries':libraries,'update_method':'owning_engine_bundle',
                     'url':'https://github.com/unslothai/llama.cpp/releases' if 'Unsloth' in owner else 'https://github.com/Niko1221/Strata/releases'})
    return rows
