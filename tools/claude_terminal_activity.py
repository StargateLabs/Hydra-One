"""Silent Claude lifecycle hook: record state, never prompt text or hook decisions."""
import json
from pathlib import Path
import sys
import time


def update(marker,token,event):
    path=Path(marker)
    try:old=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):old={}
    if old.get('token')!=token:return
    name=event.get('hook_event_name')
    if name not in ('SessionStart','UserPromptSubmit','PreToolUse','Stop','SessionEnd','Notification'):return
    if name=='Notification' and event.get('notification_type')!='idle_prompt':return
    busy=name in ('UserPromptSubmit','PreToolUse') or name=='Stop' and event.get('stop_hook_active') is True
    row={'token':token,'event':name,'busy':busy,'known':True,'time':time.time()}
    session=event.get('session_id') or old.get('session_id')
    try:row['session_id']=str(__import__('uuid').UUID(session))
    except (ValueError,TypeError,AttributeError):pass
    temporary=path.with_name(path.name+'.'+str(__import__('os').getpid())+'.tmp')
    temporary.write_text(json.dumps(row),encoding='utf-8');temporary.replace(path)


if __name__=='__main__':
    try:update(sys.argv[1],sys.argv[2],json.load(sys.stdin))
    except (OSError,ValueError,IndexError):pass
