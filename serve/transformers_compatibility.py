"""Choose the newest official release allowed by installed native Unsloth metadata."""
import hashlib,json
from pathlib import Path
from packaging.requirements import Requirement
from packaging.version import Version,InvalidVersion
from urllib.request import Request,urlopen

def constraints():
 base=Path.home()/'.unsloth/studio/unsloth_studio/Lib/site-packages';digest=hashlib.sha256();specs=[]
 for name in ('unsloth','unsloth_zoo'):
  paths=list(base.glob(name+'-*.dist-info/METADATA'))
  if len(paths)!=1:continue
  raw=paths[0].read_bytes();digest.update(raw)
  for line in raw.decode('utf-8').splitlines():
   if line.startswith('Requires-Dist:'):
    requirement=Requirement(line.partition(':')[2].strip())
    if requirement.name.lower()=='transformers' and (not requirement.marker or requirement.marker.evaluate({'extra':''})):specs.append(str(requirement.specifier))
 return specs,digest.hexdigest()

def cached(root,row):
 try:
  specs,digest=constraints();data=json.loads((Path(root)/'data/transformers-compatible-release.json').read_text(encoding='utf-8'))
  if specs and data.get('constraints_sha256')==digest and data.get('latest_version')==(row.get('latest_version') or row.get('version')):
   return {**row,**data['release'],'latest_version':data['latest_version'],'compatible_release':True,'compatibility_constraints':specs}
 except (OSError,ValueError,KeyError):pass
 return {**row,'compatible_release':False} if row.get('compatible_release') else row

def latest(root):
 from serve.configuration import atomic_json
 from serve.transformers_integration import release_from_metadata
 from packaging.specifiers import SpecifierSet
 def read(url):
  with urlopen(Request(url,headers={'User-Agent':'StargateLab-Compatibility'}),timeout=15) as response:raw=response.read(2*1024**2+1)
  if len(raw)>2*1024**2:raise ValueError('Official package metadata exceeds limit')
  return json.loads(raw)
 metadata=read('https://pypi.org/pypi/transformers/json');release=release_from_metadata(metadata);specs,digest=constraints()
 if not specs:return release
 versions=[]
 for text,files in metadata.get('releases',{}).items():
  try:
   version=Version(text)
   if not version.is_prerelease and not version.is_devrelease and files and any(not file.get('yanked') for file in files) and all(SpecifierSet(spec).contains(version) for spec in specs):versions.append(version)
  except InvalidVersion:continue
 if not versions:raise ValueError('No official Transformers release satisfies installed Unsloth')
 selected=str(max(versions));compatible=release_from_metadata(read('https://pypi.org/pypi/transformers/'+selected+'/json'))
 data={'constraints_sha256':digest,'latest_version':release['version'],'release':compatible};path=Path(root)/'data/transformers-compatible-release.json';path.parent.mkdir(parents=True,exist_ok=True);atomic_json(path,data)
 return {**compatible,'latest_version':release['version'],'compatible_release':True,'compatibility_constraints':specs}
