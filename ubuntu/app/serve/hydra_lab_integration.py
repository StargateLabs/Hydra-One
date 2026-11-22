"""Opt-in bridge to the existing app Benchmark/Prestazioni routes, never a separate page."""
import json,os,threading
_context_lock=threading.Lock()
from pathlib import Path

def lab_enabled():return os.environ.get('HYDRA_LAB_MODE')=='1'
def render_lab_html(body):
 if not lab_enabled():return body
 return body.replace(b'</head>',b'<script>window.HYDRA_LAB_MODE=true;</script></head>')
def service_lab(service):
 if not lab_enabled() or not os.environ.get('HYDRA_LAB_PROFILE'):raise ValueError('Explicit HYDRA_LAB_PROFILE required')
 with _context_lock:
  lab=getattr(service,'_hydra_benchmark_lab',None)
  if lab is None:
   from serve.hydra_lab_app import Lab
   lab=Lab(json.loads(Path(os.environ['HYDRA_LAB_PROFILE']).read_text(encoding='utf-8')));service._hydra_benchmark_lab=lab
  if callable(getattr(service,'loaded',None)):lab.profile['operational_loaded']=bool(service.loaded())
  return lab

def existing_reports(workspace,rows=None):
 result=[]
 for r in (workspace.store.list() if rows is None else rows):
  if r.get('legacy_native_path'):continue
  stats=r.get('summary',{});s={}
  for old,new in [('decode_tok_s','decode_tps'),('prefill_tok_s','prefill_tps'),('generation_ms','decode_ms'),('ttft_ms','ttft_ms'),('wall_ms','e2e_ms')]:
   if stats.get(new):s[old]={k:stats[new][k] for k in ('min','max','median')}
  origin={'IMPORTED_HISTORICAL':'Storico importato','CAPABILITY_AUDIT':'Verifica disponibilità · nessuna inferenza','ADMISSION_TEST':'Ammissione / controlli - nessuna inferenza','ADMISSION':'Ammissione bloccata · nessuna inferenza','SOFTWARE_VALIDATION':'Test software · nessuna inferenza'}.get(r['origin'],'Prova dall’app')
  result.append(dict(label=origin+' · '+r['profile']+' · '+r['prompt_id'],model=r['model'],backend=r['backend'],started_at=r['timestamp'],status='complete' if r['status'] in ('COMPLETED','PASS','IMPORTED_HISTORICAL') else 'running' if r['status']=='RUNNING' else 'failed',origin=r['origin'],summary=s,protocol=dict(runs=len(r.get('samples',[])),warmup=len(r.get('warmup',[])),tokens=r.get('parameters',{}).get('max_tokens'),prompt_set=r.get('prompt_hash'),output_policy='actual_output'),binary_sha256=r.get('configuration',{}).get('runtime_manifest',{}).get('files',{}).get('llama-server.exe',{}).get('sha256',r['runtime_hash']),hydra_run_id=r['run_id'],source=r['artifacts'],quality_gate=r['quality_gate']))
 return result

def route(handler,lab,method,path):
 def reply(status,data,kind='application/json'):
  raw=json.dumps(data,ensure_ascii=False).encode() if not isinstance(data,bytes) else data;handler.send_response(status);handler.send_header('Content-Type',kind+'; charset=utf-8');handler.send_header('Content-Length',str(len(raw)));handler.end_headers();handler.wfile.write(raw)
 if handler.headers.get('X-Hydra-Lab')!=lab.profile['key']:reply(403,{'error':'laboratory token required'});return
 try:
  if method=='GET' and path.startswith('/lab/benchmarks/api/features/'):
   from serve.hydra_feature_control import features_api
   reply(200,features_api(lab.features,path.rsplit('/',1)[1]));return
  if method=='POST' and path.startswith('/lab/benchmarks/features/'):
   size=int(handler.headers.get('Content-Length','0'))
   if not 0<size<=32768:raise ValueError('request size limit')
   body=json.loads(handler.rfile.read(size));operation=path.rsplit('/',1)[1]
   from serve.hydra_feature_control import features_api,probe
   reply(200,probe(lab.benchmarks,body) if operation=='probe' else features_api(lab.features,operation,body));return
  if method=='POST' and path=='/lab/benchmarks/functional':
   from serve.hydra_lab_functional import execute,response
   size=int(handler.headers.get('Content-Length','0'))
   if not 0<size<=32768:raise ValueError('request size limit')
   status,value=response(execute(lab.benchmarks,json.loads(handler.rfile.read(size))));reply(status,value);return
  if method=='POST' and path in ('/lab/benchmarks/run','/lab/benchmarks/submit','/lab/benchmarks/cancel','/lab/benchmarks/assess'):
   size=int(handler.headers.get('Content-Length','0'))
   if not 0<size<=32768:raise ValueError('request size limit')
   body=json.loads(handler.rfile.read(size));action={'/lab/benchmarks/assess':lab.benchmarks.assess,'/lab/benchmarks/run':lab.benchmarks.execute,'/lab/benchmarks/submit':lab.benchmarks.submit,'/lab/benchmarks/cancel':lambda b:lab.benchmarks.cancel(b['run_id'])}[path];reply(200,action(body));return
  suffix=path.removeprefix('/lab/benchmarks/api/')
  if method!='GET':reply(405,{'error':'unsupported benchmark operation'});return
  if suffix=='readiness':
   from serve.hydra_lab_readiness import readiness
   reply(200,readiness(lab))
  elif suffix=='admission':
   from serve.hydra_execution_v10 import admission_status
   reply(200,admission_status())
  elif suffix=='runs':reply(200,lab.benchmarks.store.list())
  elif suffix=='catalog':reply(200,lab.benchmarks.catalog())
  elif suffix in ('export.json','export.csv'):
   raw,kind=lab.benchmarks.store.export(suffix.split('.')[-1]);reply(200,raw,kind)
  elif suffix.startswith('run/'):
   key=suffix.split('/')[1]
   if '/artifact/' in suffix:
    from serve.hydra_lab_benchmarks import read_artifact
    reply(200,read_artifact(lab.benchmarks.store.get(key),suffix.split('/artifact/',1)[1]),__import__('mimetypes').guess_type(suffix.split('/artifact/',1)[1])[0] or 'application/octet-stream')
   elif suffix.endswith('/log'):reply(200,lab.benchmarks.log(key).encode(),'text/plain')
   elif suffix.endswith('/samples.csv'):
    from serve.hydra_lab_benchmarks import export_samples
    reply(200,export_samples(lab.benchmarks.store.get(key)),'text/csv')
   else:reply(200,lab.benchmarks.store.get(key))
  else:reply(404,{'error':'unknown benchmark route'})
 except (ValueError,TypeError,KeyError) as exc:reply(400,{'error':str(exc)})
 except Exception as exc:reply(503,{'error':str(exc)})

def publish_existing_registry(workspace,root,run_id=None):
 """Append publisher-owned schema-v1 records to the app's existing benchmark archive."""
 import sqlite3
 from types import SimpleNamespace
 rows=[workspace.store.get(run_id)] if run_id is not None else workspace.store.list()
 root=Path(root);directory=root/'data/benchmarks';directory.mkdir(parents=True,exist_ok=True)
 registry=root/'data/hydra-benchmark-registry';registry.mkdir(parents=True,exist_ok=True)
 # Merge by stable ID, preserving unrelated history and never overwriting foreign files.
 target=registry/'benchmarks.sqlite'
 connection=sqlite3.connect(target)
 try:
  with connection:
   connection.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
   for row in rows:connection.execute('INSERT OR REPLACE INTO runs VALUES(?,?)',(row['run_id'],json.dumps(row,ensure_ascii=False)))
 finally:connection.close()
 reports={r['hydra_run_id']:r for r in existing_reports(workspace,rows)}
 for row in rows:
  if row.get('legacy_native_path'):continue
  record=reports[row['run_id']];path=directory/('hydra-'+row['run_id']+'.json')
  if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('publisher')!='hydra-benchmark-registry-v2':raise ValueError('foreign benchmark projection already exists')
  payload=dict(schema_version=1,publisher='hydra-benchmark-registry-v2',run_id=row['run_id'],origin=row['origin'],label=record['label'],started_at=row['timestamp'],status=record['status'],engine={'model':row['model'],'backend':row['backend']},binary_sha256=record['binary_sha256'],config_fingerprint=row['comparison_key'],protocol=record['protocol'],summary=record['summary'],quality_gate=row['quality_gate'],error=row.get('error'),source_registry=str(target),source_artifacts=row['artifacts'],rows=[dict(warmup=False,decode_tok_s=v.get('decode_tps'),prefill_tok_s=v.get('prefill_tps'),wall_s=v.get('e2e_ms')/1000 if v.get('e2e_ms') is not None else None,output_tokens=v.get('tokens'),output=v.get('output')) for v in row.get('samples',[])])
  if path.exists() and json.loads(path.read_text(encoding='utf-8'))==payload:continue
  temp=path.with_suffix('.tmp');temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,path)
  from datetime import datetime
  stamp=datetime.fromisoformat(row['timestamp']).timestamp();os.utime(path,(stamp,stamp))
 return len(reports)
def published_rows(root):
 import sqlite3
 path=Path(root)/'data/hydra-benchmark-registry/benchmarks.sqlite'
 if not path.is_file():return []
 connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
 try:return [json.loads(r[0]) for r in connection.execute('SELECT payload FROM runs')]
 finally:connection.close()
def history_html(body,root):
 if (Path(root)/'data/hydra-benchmark-registry/benchmarks.sqlite').is_file():return body.replace(b'</head>',b'<script>window.HYDRA_BENCHMARK_HISTORY_AVAILABLE=true;</script></head>')
 return body
def readonly_route(handler,root,path):
 rows=published_rows(root);by_id={r['run_id']:r for r in rows};suffix=path.removeprefix('/lab/benchmarks/api/')
 def reply(value,kind='application/json'):
  raw=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode();handler.send_response(200);handler.send_header('Content-Type',kind+'; charset=utf-8');handler.send_header('Content-Length',str(len(raw)));handler.end_headers();handler.wfile.write(raw)
 if suffix=='runs':reply(sorted(rows,key=lambda r:r.get('timestamp',''),reverse=True));return
 if suffix=='catalog':
  import sqlite3
  connection=sqlite3.connect((Path(root)/'data/hydra-benchmark-registry/benchmarks.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
  try:
   try:data=[json.loads(r[0]) for r in connection.execute('SELECT payload FROM catalog_entries ORDER BY model_id')]
   except sqlite3.OperationalError:data=[]
  finally:connection.close()
  if not data:data=json.loads(Path(__file__).with_name('hydra_lab_catalog.json').read_text(encoding='utf-8'))
  from serve.hydra_lab_benchmarks import catalog_evidence
  data=[catalog_evidence(r,rows) for r in data]
  reply(data);return
 if suffix.startswith('run/'):
  key=suffix.split('/')[1]
  if key not in by_id:raise ValueError('unknown published run')
  row=by_id[key]
  if '/artifact/' in suffix:
   from serve.hydra_lab_benchmarks import read_artifact
   reply(read_artifact(row,suffix.split('/artifact/',1)[1]),__import__('mimetypes').guess_type(suffix.split('/artifact/',1)[1])[0] or 'application/octet-stream')
  elif suffix.endswith('/log'):
   p=Path(row['log_path']);reply(p.read_bytes() if p.is_file() else b'NOT_AVAILABLE','text/plain')
  elif suffix.endswith('/samples.csv'):
   from serve.hydra_lab_benchmarks import export_samples
   reply(export_samples(row),'text/csv')
  else:reply(row)
  return
 if suffix=='export.json':reply(rows);return
 if suffix=='export.csv':
  import csv,io
  buf=io.StringIO();w=csv.writer(buf);w.writerow(['run_id','origin','model','profile','status','quality_gate','e2e_median_ms'])
  for r in rows:w.writerow([r['run_id'],r['origin'],r['model'],r['profile'],r['status'],r['quality_gate'],(r.get('summary',{}).get('e2e_ms') or {}).get('median')])
  reply(('\ufeff'+buf.getvalue()).encode(),'text/csv');return
 raise ValueError('unknown published history operation')
