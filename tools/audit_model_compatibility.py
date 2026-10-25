"""Persist local-model compatibility evidence without loading weights or guessing support."""
import argparse,json,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from serve.gguf_metadata_light import metadata_string
from serve.configuration import atomic_json

def inspect(row):
 result={key:row.get(key) for key in ('name','path','format','bytes','runtime_supported','runtime_error','paired_projectors')}
 result.update(role='chat_candidate' if row.get('runtime_supported') else 'unsupported_or_auxiliary',execution='not_tested',tools='unknown',devices='requires_host_runtime_validation')
 path=Path(row['path'])
 try:
  if row['format']=='GGUF':
   result['architecture']=metadata_string(path,'general.architecture')
   template=metadata_string(path,'tokenizer.chat_template') or ''
   result['chat_template_present']=bool(template)
   result['tools']='template_declares_tools_not_execution_verified' if 'tools' in template else 'not_declared_by_template'
  else:
   config=json.loads((path/'config.json').read_text(encoding='utf-8'))
   result.update(architecture=config.get('architectures'),context=config.get('max_position_embeddings'))
   tokenizer=json.loads((path/'tokenizer_config.json').read_text(encoding='utf-8'))
   template=tokenizer.get('chat_template') or ''
   result['tools']='parser_candidate_not_verified' if tokenizer.get('response_schema') or isinstance(template,str) and all(marker in template for marker in ('<tool_call>','</tool_call>','arguments','tools')) else 'unsupported_by_current_parser'
 except (OSError,ValueError,KeyError) as error:result['metadata_error']=str(error)
 return result

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8088);args=parser.parse_args()
 with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/inference-backends',timeout=20) as response:catalogue=json.load(response)
 report={'created_at':time.time(),'scope':'Metadata audit only; no model loading and no universal tool capability claim','models':[inspect(row) for row in catalogue.get('local_models',[])]}
 destination=ROOT/'output/verification/open-plans-20261012/model-compatibility-matrix.json';atomic_json(destination,report)
 print('Models audited:',len(report['models']));print('Metadata errors:',sum('metadata_error' in row for row in report['models']));print(destination)
if __name__=='__main__':main()
