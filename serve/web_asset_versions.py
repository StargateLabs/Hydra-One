"""Content-based asset URLs: fresh UI on reload, without rebuilding dependencies."""
import hashlib,re
from pathlib import Path
_cache={}
# A reference may carry a stale token or none at all; both get the current digest.
_PATTERN=re.compile(r'((?:src|href)="web/([^"?]+))((?:\?v=)[^"&]*)?([^"]*")')
def versioned_html(path):
 path=Path(path);root=path.parent;source=path.read_text(encoding='utf-8')
 def replace(match):
  asset=(root/match[2]).resolve()
  if not asset.is_relative_to(root.resolve()) or asset.suffix not in ('.js','.css') or not asset.is_file():return match[0]
  stat=asset.stat();key=(str(asset),stat.st_size,stat.st_mtime_ns)
  digest=_cache.get(key)
  if digest is None:
   digest=hashlib.sha256(asset.read_bytes()).hexdigest()[:12]
   if len(_cache)>256:_cache.clear()
   _cache[key]=digest
  return match[1]+'?v='+digest+match[4]
 return _PATTERN.sub(replace,source).encode('utf-8')
