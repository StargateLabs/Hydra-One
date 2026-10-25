"""Run the original AudioCraft/Dora solver on an owned dataset, offline."""
import hashlib,json,os,shutil,sys,time
from pathlib import Path

def run(request_path):
 root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
 from serve.configuration import atomic_json
 from serve.audiocraft_training import dataset,source
 request_path=Path(request_path).resolve();out=request_path.parent
 if not out.is_relative_to(root/'output/training'):raise ValueError('Training output outside owned workspace')
 request=json.loads(request_path.read_text(encoding='utf-8'));data_path,_=dataset(root,request['dataset']);original=source(root)
 config=out/'config';shutil.copytree(original/'config',config)
 main_config=config/'config.yaml';text=main_config.read_text(encoding='utf-8').replace('/checkpoint/${oc.env:USER}/experiments/audiocraft/outputs',(out/'experiments').as_posix());main_config.write_text(text,encoding='utf-8')
 team=out/'team.yaml';team.write_text('default:\n  dora_dir: '+(out/'experiments').as_posix()+'\n  reference_dir: '+out.as_posix()+'\n  partitions:\n    global: debug\n    team: debug\n',encoding='utf-8')
 os.environ.update(AUDIOCRAFT_CONFIG=str(team),AUDIOCRAFT_CLUSTER='default',HF_HUB_CACHE=request['cache'],HUGGINGFACE_HUB_CACHE=request['cache'],TRANSFORMERS_CACHE=request['cache'],HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
 sys.path.insert(0,str(original))
 import dora
 native_hydra=dora.hydra_main
 def own_config(*args,**kwargs):kwargs['config_path']=str(config);return native_hydra(*args,**kwargs)
 dora.hydra_main=own_config
 from audiocraft.utils import cluster
 if os.name=='nt':
  cluster._guess_cluster_type=lambda:cluster.ClusterType.DEFAULT
  import audiocraft.environment
  audiocraft.environment._guess_cluster_type=cluster._guess_cluster_type
 options=request['options'];debug=request['recipe']=='debug'
 args=['solver=musicgen/debug' if debug else 'solver=musicgen/musicgen_base_32khz','device=cpu','logging.log_tensorboard=false','dora.git_save=false','mp_start_method=spawn','dataset.batch_size='+str(options['batch']),'dataset.num_workers=0','+dataset.info_fields_required=false','dataset.segment_duration='+str(options['seconds']),'optim.epochs='+str(options['epochs']),'optim.updates_per_epoch='+str(options['steps']),'dataset.train.num_samples='+str(options['steps']*options['batch']),'dataset.valid.num_samples=1','dataset.generate.num_samples=1','generate.every=null','evaluate.every=null','transformer_lm.memory_efficient=false','autocast=false','num_threads=2']
 if debug:args.append('conditioners.description.t5.name=t5-base')
 else:args.extend(['continue_from=//pretrained/'+Path(request['model']).as_posix(),'compression_model_checkpoint='+Path(request['model']).as_posix()])
 for split in ['train','valid','evaluate','generate']:args.append('datasource.'+split+'='+(data_path.parent/('train' if split=='train' else 'valid')).as_posix())
 sys.argv=['audiocraft.train',*args]
 started=time.time();atomic_json(out/'workflow.json',{'status':'running','runner':'audiocraft','scope':'native debug pipeline' if debug else 'native MusicGen CPU training'})
 import audiocraft.train
 audiocraft.train.main()
 checkpoints=list((out/'experiments').glob('xps/*/checkpoint.th'))
 if len(checkpoints)!=1:raise ValueError('Native training checkpoint missing or ambiguous')
 from audiocraft.utils.export import export_lm
 exported=out/'export/state_dict.bin';export_lm(checkpoints[0],exported)
 import torch
 checkpoint=torch.load(checkpoints[0],map_location='cpu');release=torch.load(exported,map_location='cpu')
 expected=checkpoint['best_state']['model'];actual=release['best_state']
 if expected.keys()!=actual.keys() or not all(torch.equal(expected[k],actual[k]) for k in expected):raise ValueError('Native exported tensors differ from trained checkpoint')
 history=checkpoints[0].parent/'history.json';metrics=json.loads(history.read_text())
 if not metrics or not any(row.get('train') for row in metrics):raise ValueError('Native training history missing')
 atomic_json(out/'workflow.json',{'status':'complete','runner':'audiocraft','native_training_verified':True,'export_tensors_verified':True,'recipe':request['recipe'],'checkpoint':str(checkpoints[0]),'export':str(exported),'history':metrics,'elapsed_seconds':time.time()-started,'dataset':str(data_path),'scope':'Debug verifies original solver and export, not musical quality' if debug else 'Original solver and exact tensor export; musical quality requires independent evaluation'})

if __name__=='__main__':run(sys.argv[1])
