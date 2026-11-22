"""Merge native and optional benchmark history without hiding an active run."""
import copy

def merge_benchmark_state(data,optional_job,optional_history,ready_model=None):
    data=copy.deepcopy(data)
    by_id={}
    terminal=[optional_job] if optional_job.get('id') and optional_job.get('status') in ('complete','failed','cancelled') else []
    for row in [*data.get('history',[]),*optional_history,*terminal]:
        if row.get('id'):by_id[row['id']]=row
    history=sorted(by_id.values(),key=lambda row:row.get('started_at') or 0,reverse=True)
    data['history']=history
    active=('queued','running','cancelling')
    if optional_job.get('status') in active:data['job']=copy.deepcopy(optional_job)
    elif data.get('job',{}).get('status') not in active:
        matching=[row for row in history if not ready_model or row.get('model')==ready_model]
        if matching:data['job']=copy.deepcopy(matching[0])
        elif ready_model:data['job']=copy.deepcopy(optional_job)
    return data
