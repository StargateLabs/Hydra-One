"""Shared exception identity for module and script laboratory entrypoints."""
class TaskIncomplete(RuntimeError):
 def __init__(self,response):super().__init__('TASK_INCOMPLETE; output budget exhausted or no final answer; native response preserved');self.response=response

def require_completed_task(response):
 choice=response['choices'][0];text=choice.get('message',{}).get('content') or ''
 if choice.get('finish_reason')=='length' or not text.strip():raise TaskIncomplete(response)
