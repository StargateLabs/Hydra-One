"""LAB-only extension of the existing bundled package, preserving its original classes."""
import importlib,os,threading
from pathlib import Path
_LOCK=threading.RLock()
_ALLOWED={'graph_hybrid','graph_hybrid_v2','decision_scoring','execution_admission','system_one_semantics_contract_lab'}
def load(name):
 if os.environ.get('HYDRA_LAB_MODE')!='1' or name not in _ALLOWED:raise ValueError('explicit laboratory module required')
 root=Path(__file__).resolve().parents[1]/'hydra-engine/hydra_lab';expected=(root/(name+'.py')).resolve()
 if not expected.is_file():raise ValueError('laboratory module asset missing')
 with _LOCK:
  package=importlib.import_module('hydra_lab')
  paths=list(package.__path__)
  if str(root) not in paths:package.__path__=[*paths,str(root)]
  module=importlib.import_module('hydra_lab.'+name)
  if Path(module.__file__).resolve()!=expected:raise ValueError('laboratory module provenance mismatch; no replacement of a loaded module')
  return module
