"""Publish lab-owned progress through the app's existing Monitor snapshot contract."""
import json,os,threading,time,uuid
from pathlib import Path
from datetime import datetime

def monitor_metrics(rows,current=None):
 requests=[]
 for row in rows:
  if row.get('origin') not in ('LIVE_APP','E2E_TEST','BENCHMARK','IMPORTED_HISTORICAL'):continue
  if not row.get('real_execution_kind') and row.get('profile','').startswith('functional-'):continue
  samples=row.get('samples') or [None]
  for sample in samples:
   sample=sample or {};stamp=row.get('finished_at') or row.get('timestamp')
   requests.append({'run_id':row['run_id'],'model':row.get('model'),'time':datetime.fromisoformat(stamp).timestamp() if stamp else time.time(),'finish':'stop' if row['status'] in ('PASS','COMPLETED','IMPORTED_HISTORICAL') else 'cancel' if row['status']=='CANCELLED' else row['status'],'output_tokens':sample.get('tokens'),'prompt_tokens':sample.get('prompt_tokens'),'duration_s':sample.get('e2e_ms')/1000 if sample.get('e2e_ms') is not None else None,'decode_tok_s':sample.get('decode_tps'),'prefill_tok_s':sample.get('prefill_tps'),'prompt_ms':sample.get('prefill_ms'),'reused':None,'status':row['status'],'origin':row['origin']})
 requests.sort(key=lambda r:r['time'],reverse=True);active=current and current['status'] in ('QUEUED','RUNNING');last=(current or (rows[0] if rows else {}));event=last.get('events',[]);phase=event[-1]['kind'] if event else 'idle';started=last.get('started_at') or last.get('timestamp');elapsed=time.time()-datetime.fromisoformat(started).timestamp() if started and active else None
 import psutil
 mem=psutil.virtual_memory();hw={'ram_total':mem.total,'ram_used':mem.total-mem.available,'cpu':psutil.cpu_percent(interval=None)}
 return {'engine':{'model':last.get('model'),'display_name':last.get('model'),'backend':'HYDRA LAB · '+str(last.get('backend','NOT_VERIFIED')),'max_context':last.get('configuration',{}).get('context'),'images':last.get('real_execution_kind')=='image-generation'},'live':{'state':'loading' if active and phase in ('admission','loading','startup') else 'generating' if active else 'idle','phase':phase,'queued':0,'elapsed_s':elapsed,'generated':None,'tok_s':None,'prefill_tok_s_mean':None,'completed_samples':len(last.get('samples',[]))},'requests':requests[:100],'requests_kept':min(len(requests),100),'totals':{'requests':len(requests),'output_tokens':sum(r['output_tokens'] for r in requests if r['output_tokens'] is not None)},'hardware':hw,'hardware_static':{},'history':{},'power':{},'source':'HYDRA LAB persistent registry; live throughput unavailable until runtime emits counters'}

class LiveMonitor:
 def __init__(self,workspace,row):
  self.workspace=workspace;self.row=row;self.token=uuid.uuid4().hex;self.path=Path(__file__).resolve().parents[1]/'data/benchmark-live.json';self.done=threading.Event();self.thread=None
  self.enabled=not getattr(workspace.lab,'features',None) or workspace.lab.features.setting(53)['desired']
  if not self.enabled:return
  # The shared coordinator excludes other writers for this admission. Keep
  # immutable past rows once; the current row remains live and is replaced on
  # every tick, including final samples/status. retained() refreshes after release.
  self.history=[r for r in workspace.store.list() if r['run_id']!=row['run_id']]
  self.write(True)
  self.thread=threading.Thread(target=self.loop,name='hydra-monitor-'+row['run_id'],daemon=True);self.thread.start()
 def write(self,active):
  from serve.benchmark_monitor import snapshot
  current=snapshot(self.path)
  if current and current.get('active') and current.get('owner_token')!=self.token:raise RuntimeError('another Monitor producer is active; no overwrite')
  row=self.row;data={'label':str(row.get('model'))+' · '+str(row.get('profile')),'source_port':self.workspace.lab.profile.get('port'),'updated_at':time.time(),'active':active,'owner_token':self.token,'run_id':row['run_id'],'metrics':monitor_metrics([row,*self.history],row)};self.path.parent.mkdir(exist_ok=True);temp=self.path.with_name(self.path.name+'.'+self.token+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf-8');os.replace(temp,self.path)
 def loop(self):
  while not self.done.wait(1):
   try:self.write(True)
   except Exception:return
 def close(self):
  self.done.set()
  if self.thread:self.thread.join(2)
  if self.enabled:self.write(False)

def retained(workspace):
 if getattr(workspace.lab,'features',None) and not workspace.lab.features.setting(53)['desired']:return
 from serve.benchmark_monitor import snapshot
 path=Path(__file__).resolve().parents[1]/'data/benchmark-live.json';existing=snapshot(path)
 if existing and existing.get('active'):return
 rows=workspace.store.list();real=[r for r in rows if r.get('origin') in ('LIVE_APP','E2E_TEST','BENCHMARK')]
 if real:
  last=real[0];data={'label':last['model']+' · '+last['profile'],'source_port':workspace.lab.profile.get('port'),'updated_at':time.time(),'active':False,'run_id':last['run_id'],'metrics':monitor_metrics(rows,last)};tmp=path.with_suffix('.hydra-retained.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf-8');os.replace(tmp,path)
