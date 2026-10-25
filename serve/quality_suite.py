"""Shared closed-reference tasks, never a claim of general model quality."""
import hashlib,json
from tools.verify_iq3_tasks import CASES,evaluate
DATASET_SHA256=hashlib.sha256(json.dumps(CASES,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
CATEGORIES={'invoice':'arithmetic','sort':'data','aggregate':'data','trace_python':'code','trace_loop':'code','interval':'logic','deduplicate':'data','join':'data','schedule':'logic','nested':'data','logic':'logic','date':'arithmetic'}
