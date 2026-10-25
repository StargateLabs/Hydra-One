"""Local-only original MultiBand Diffusion with the original HF EnCodec wrapper."""
import hashlib,json
from pathlib import Path

def run(request,torch,soundfile):
 from transformers import EncodecModel
 from audiocraft.models.encodec import HFEncodecCompressionModel
 from audiocraft.models.loaders import load_diffusion_models
 from audiocraft.models.multibanddiffusion import MultiBandDiffusion,DiffusionProcess,NoiseSchedule
 from audiocraft.data.audio_utils import convert_audio
 folder=Path(request['model_path']);filename='mbd_comp_'+str(request['mbd_codebooks'])+'.pt'
 spec=json.loads((folder/'audiogen.json').read_text(encoding='utf-8'))
 with (folder/filename).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
 if digest!=spec.get('sha256',{}).get(filename):raise ValueError('Original MBD hash mismatch')
 codec_path=Path(request['codec_path']);provenance=json.loads((codec_path/'provenance.json').read_text(encoding='utf-8'))
 if provenance.get('repository')!='facebook/encodec_24khz':raise ValueError('Original Meta codec provenance required')
 for name in ('model.safetensors','config.json'):
  with (codec_path/name).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
  if digest!=provenance.get('sha256',{}).get(name):raise ValueError('Codec asset integrity mismatch')
 codec=HFEncodecCompressionModel(EncodecModel.from_pretrained(str(codec_path),local_files_only=True,use_safetensors=True)).to(request['device'])
 if codec.sample_rate!=24000 or codec.cardinality!=1024:raise ValueError('MBD requires the original 24 kHz/1024-code codec')
 codec.set_num_codebooks(request['mbd_codebooks'])
 models,processors,configs=load_diffusion_models(str(folder),filename=filename,device=request['device'])
 processes=[DiffusionProcess(model=model,noise_schedule=NoiseSchedule(**cfg.schedule,sample_processor=processor,device=request['device'])) for model,processor,cfg in zip(models,processors,configs)]
 model=MultiBandDiffusion(DPs=processes,codec_model=codec)
 waveform,rate=soundfile.read(request['source_path'],dtype='float32',always_2d=True)
 x=convert_audio(torch.from_numpy(waveform.T),rate,codec.sample_rate,codec.channels).unsqueeze(0).to(request['device']);torch.manual_seed(request['seed'])
 with torch.inference_mode():y=model.regenerate(x,sample_rate=codec.sample_rate)
 return y[0].float().cpu().numpy().T,codec.sample_rate,{'bandwidth_kbps':request['mbd_bandwidth'],'codebooks':request['mbd_codebooks'],'codec':'facebook/encodec_24khz','decoder':'facebook/multiband-diffusion','seed':request['seed'],'source_retained':True}
