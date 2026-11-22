"""Opt-in repository source selection feeding the existing verified context path.

Graphify selects candidates, current local source bytes remain authoritative.
It does not optimize model weights, GPU memory, kernels or model loading.
"""
from contextlib import contextmanager
import hashlib,json,re,time,zlib
from pathlib import Path

class GraphIndexTiers:
 """Own only the repository candidate index: parsed RAM, compressed RAM, source disk.

 Every request still reads/hashes the source archive. A cache hit avoids JSON
 decoding, not source I/O or model-weight reads. Cold releases all retained data.
 """
 def __init__(self):
  self.hot=None;self.warm=None;self.identity=None;self.tier=0
  self.stats=dict(hot_hits=0,warm_hits=0,misses=0,invalidations=0,transitions=0,source_bytes_read=0,resident_bytes=0)
 def clear(self):
  self.hot=None;self.warm=None;self.identity=None;self.tier=0;self.stats['resident_bytes']=0
 def resolve(self,raw,target):
  if type(target) is not int or target not in (0,1,2):raise ValueError('index tier must be0 cold,1 warm,2 hot')
  identity=hashlib.sha256(raw).hexdigest();self.stats['source_bytes_read']+=len(raw)
  if self.identity is not None and self.identity!=identity:self.clear();self.stats['invalidations']+=1
  if self.hot is not None:nodes=self.hot;self.stats['hot_hits']+=1
  elif self.warm is not None:nodes=json.loads(zlib.decompress(self.warm));self.stats['warm_hits']+=1
  else:
   nodes=json.loads(raw).get('nodes',[]);self.stats['misses']+=1
   # Relationships and other AST metadata are not owned by this selector cache.
   nodes=[{key:node.get(key) for key in ('id','label','source_file')} for node in nodes]
  if self.tier!=target:self.stats['transitions']+=1
  self.identity=identity;self.tier=target
  if target==2:
   self.hot=nodes;self.warm=None;self.stats['resident_bytes']=len(json.dumps(nodes).encode())
  elif target==1:
   self.hot=None;self.warm=zlib.compress(json.dumps(nodes).encode());self.stats['resident_bytes']=len(self.warm)
  else:self.hot=None;self.warm=None;self.stats['resident_bytes']=0
  return nodes

def revalidate_selection(row):
 path=Path(row['path'])
 if path.is_symlink():raise ValueError('GRAPHIFY_SOURCE_CHANGED')
 if 'authorized_root' in row and (not path.resolve(strict=True).is_relative_to(Path(row['authorized_root']).resolve()) or path.resolve(strict=True)!=path):raise ValueError('GRAPHIFY_SOURCE_OUTSIDE_AUTHORIZED_ROOT')
 raw=path.read_bytes()
 if len(raw)!=row['bytes'] or hashlib.sha256(raw).hexdigest()!=row['source_sha256']:raise ValueError('GRAPHIFY_SOURCE_CHANGED; selection cannot authorize different source bytes')

def select_sources(root,graph_path,query,limit=2,tiers=None,target_tier=0):
 root=Path(root).resolve();graph_path=Path(graph_path).resolve();started=time.perf_counter()
 if not graph_path.is_relative_to(root) or graph_path.stat().st_size>40*1024**2:raise ValueError('Graphify archive outside local size/root budget')
 if type(limit) is not int or not 1<=limit<=4:raise ValueError('invalid Graphify source limit')
 raw=graph_path.read_bytes();nodes=tiers.resolve(raw,target_tier) if tiers is not None else json.loads(raw).get('nodes',[]);words=set(re.findall(r'\w{3,}',query.casefold()));ranked=[]
 for node in nodes:
  label=node.get('label','');source=node.get('source_file','')
  if not isinstance(label,str) or not isinstance(source,str) or not label or not source:continue
  terms=set(re.findall(r'\w{3,}',(label+' '+Path(source).stem).casefold()))
  symbol=label.rstrip('()').casefold();folded=query.casefold()
  exact_symbol=len(symbol)>=4 and re.search(r'(?<!\w)'+re.escape(symbol)+r'(?!\w)',folded) is not None
  exact_file=Path(source).name.casefold() in folded
  score=len(terms&words)+(100 if exact_symbol else 0)+(50 if exact_file else 0)
  if score:ranked.append((score,source,label,node.get('id')))
 rows=[];seen=set()
 for score,source,label,node_id in sorted(ranked,key=lambda row:(-row[0],row[1],row[2])):
  relative=Path(source)
  if relative.is_absolute() or '..' in relative.parts or relative.suffix not in ('.py','.cpp','.hpp','.h','.js','.md'):continue
  if not relative.parts or relative.parts[0] not in ('serve','src','include','docs','tools'):continue
  if any(part.startswith('.') or part in ('data','output','node_modules','venv','__pycache__') for part in relative.parts):continue
  candidate=root/relative
  if candidate.is_symlink():continue
  try:
   path=candidate.resolve(strict=True)
   if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size>65536 or str(path) in seen:continue
   content=path.read_bytes();text=content.decode('utf-8-sig')
  except (OSError,UnicodeError):continue
  if label.rstrip('()') not in text:continue # stale AST identity cannot authorize unrelated source text
  seen.add(str(path));rows.append(dict(path=str(path),authorized_root=str(root),node_id=node_id,label=label,source_sha256=hashlib.sha256(content).hexdigest(),bytes=len(content)))
  if len(rows)>=limit:break
 meta=dict(kind='REPOSITORY_SOURCE_SELECTION; not GPU or weight acceleration',graph_sha256=hashlib.sha256(raw).hexdigest(),graph_bytes_read=len(raw),selected_sources=len(rows),selection_ms=(time.perf_counter()-started)*1000,current_source_bytes=sum(row['bytes'] for row in rows),graph_relationships='candidate provenance only; not computational dependencies')
 if tiers is not None:meta['index_tiering']=dict(tier=('cold','warm','hot')[target_tier],**tiers.stats,byte_measure='serialized index bytes or compressed bytes; not RSS',scope='repository candidate index only; source disk re-read for freshness')
 return rows,meta

@contextmanager
def repository_context(lab,body,*,section_chars=1200):
 request=body['request'];path=body['path'];features=getattr(lab,'features',None)
 if features is None or path not in ('/lab/retrieve','/lab/chat') or path=='/lab/chat' and not request.get('graph') or not features.setting(26)['desired']:
  if getattr(lab,'graphify_index',None) is not None:lab.graphify_index.clear()
  yield None;return
 query=request.get('query') if path=='/lab/retrieve' else next((m['content'] for m in reversed(request.get('messages',[])) if m['role']=='user'),'')
 root=Path(__file__).resolve().parents[1];graph_path=root/'graphify-out/graph.json'
 tier_setting=features.setting(17);tiers=None
 if tier_setting['desired']:
  if getattr(lab,'graphify_index',None) is None:lab.graphify_index=GraphIndexTiers()
  tiers=lab.graphify_index
 elif getattr(lab,'graphify_index',None) is not None:lab.graphify_index.clear()
 rows,meta=select_sources(root,graph_path,query,limit=2,tiers=tiers,target_tier=tier_setting['parameters'].get('resident_tier',0))
 old_sources=list(lab.sources);old_roots=lab.g.roots;old_options=lab.graph_options
 try:
  lab.g.roots=(*old_roots,root)
  for row in rows:
   revalidate_selection(row)
   # ingest re-reads and hashes authoritative bytes; retrieval validates freshness
   # again and RequestGuard uses the same exact source spans as ordinary Graph.
   # Whole modules exceeded the compiler budget and silently selected its safe
   # standard fallback. Index exact bounded sections using existing span/hash
   # verification instead; never truncate a paragraph or weaken RequestGuard.
   sections=lab.g.ingest_sections('lab',row['path'],target_chars=section_chars,expected_sha256=row['source_sha256'])
   revalidate_selection(row)
   meta.setdefault('source_sections',[]).append(dict(path=row['path'],graphify_node=row['node_id'],source_sha256=row['source_sha256'],section_count=len(sections),section_chars=section_chars))
   if row['path'] not in lab.sources:lab.sources.append(row['path'])
  lab.configure_graph();lab.graph_options['source_roots']=[str(value) for value in lab.g.roots]
  yield meta
 finally:lab.sources=old_sources;lab.g.roots=old_roots;lab.graph_options=old_options
