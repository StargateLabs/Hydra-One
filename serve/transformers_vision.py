"""Bounded local Transformers vision path, separate from text and GGUF projectors."""
import base64,copy,io,json,warnings
from pathlib import Path

MAX_IMAGES=2
MAX_PIXELS=1024*1024
MAX_IMAGE_BYTES=2*1024*1024
FAMILIES={'llava':'LlavaForConditionalGeneration'}

def inspect_vision(folder):
 folder=Path(folder)
 if not folder.is_absolute() or not folder.is_dir():raise ValueError('Select an absolute local vision model directory')
 config=json.loads((folder/'config.json').read_text(encoding='utf-8'))
 architecture=FAMILIES.get(config.get('model_type'))
 if not architecture or architecture not in (config.get('architectures') or []):raise ValueError('Vision family not validated; this path supports local LLaVA')
 if config.get('quantization_config'):raise ValueError('Prequantized vision weights require a validated loader')
 weights=list(folder.glob('*.safetensors'))
 if not weights:raise ValueError('Local vision Safetensors weights missing')
 if not (folder/'preprocessor_config.json').is_file():
  integrated=folder/'processor_config.json'
  if not integrated.is_file() or not isinstance(json.loads(integrated.read_text(encoding='utf-8')).get('image_processor'),dict):raise ValueError('Local image processor configuration missing')
 index=folder/'model.safetensors.index.json'
 if index.is_file():
  names=set(json.loads(index.read_text(encoding='utf-8'))['weight_map'].values())
  if any(not isinstance(name,str) or Path(name).name!=name or not (folder/name).is_file() for name in names):raise ValueError('Missing or invalid vision weight shard')
 text=config.get('text_config') or {};maximum=text.get('max_position_embeddings')
 if type(maximum) is not int or maximum<1024:raise ValueError('Vision text context unavailable')
 layers=text.get('num_hidden_layers');heads=text.get('num_attention_heads');kvheads=text.get('num_key_value_heads',heads);width=text.get('hidden_size')
 dimension=text.get('head_dim') or (width//heads if type(width) is int and type(heads) is int and heads>0 and width%heads==0 else None)
 kv=8*layers*kvheads*dimension if all(type(v) is int and v>0 for v in (layers,kvheads,dimension)) else None
 vision=config.get('vision_config') or {};size=vision.get('image_size');patch=vision.get('patch_size')
 if type(size) is not int or not 1<=size<=1024 or type(patch) is not int or patch<1:raise ValueError('Vision image budget unavailable')
 return dict(path=str(folder),bytes=sum(p.stat().st_size for p in weights),kv_bytes_per_token=kv,model_max_context=maximum,architecture=architecture,model_type=config['model_type'],input_modalities=['text','image'],image_tokens_per_image=(size//patch)**2+1,image_memory_reserve_bytes=512*1024**2,checkpoint_quantization={'method':'none','prequantized':False,'scheme':'unquantized','bits':None},runtime_supported=True,runtime_error=None)

def image_inputs(messages):
 from PIL import Image,UnidentifiedImageError
 if not isinstance(messages,list) or not messages:raise ValueError('Messages required')
 output=[];images=[];instructions=[]
 for source in copy.deepcopy(messages):
  if not isinstance(source,dict) or source.get('role') not in ('system','developer','user','assistant'):raise ValueError('Vision accepts system/user/assistant messages without tools')
  content=source.get('content');parts=[{'type':'text','text':content}] if isinstance(content,str) else content
  if not isinstance(parts,list) or not parts:raise ValueError('Vision content must contain text or images')
  converted=[]
  for part in parts:
   if not isinstance(part,dict):raise ValueError('Invalid vision content part')
   if part.get('type')=='text':
    if not isinstance(part.get('text'),str):raise ValueError('Invalid vision text')
    converted.append({'type':'text','text':part['text']})
   elif part.get('type')=='image_url':
    if source['role']!='user' or len(images)>=MAX_IMAGES:raise ValueError('At most two user images per request')
    value=part.get('image_url');url=value.get('url') if isinstance(value,dict) else None
    if not isinstance(url,str) or not url.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')):raise ValueError('Vision requires local PNG/JPEG/WebP base64 images')
    payload=url.split(',',1)[1]
    if len(payload)>(MAX_IMAGE_BYTES*4//3+4):raise ValueError('Image byte budget exceeded')
    try:raw=base64.b64decode(payload,validate=True)
    except ValueError:raise ValueError('Invalid base64 image') from None
    if len(raw)>MAX_IMAGE_BYTES:raise ValueError('Image byte budget exceeded')
    try:
     with warnings.catch_warnings():
      warnings.simplefilter('error',Image.DecompressionBombWarning)
      with Image.open(io.BytesIO(raw)) as decoded:
       if decoded.width*decoded.height>MAX_PIXELS or getattr(decoded,'n_frames',1)!=1:raise ValueError('Image pixel budget exceeded or animated image')
       if decoded.format not in ('PNG','JPEG','WEBP'):raise ValueError('Unsupported image encoding')
       decoded.load();images.append(decoded.convert('RGB'))
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as error:raise ValueError('Invalid or oversized image') from error
    converted.append({'type':'image'})
   else:raise ValueError('Unsupported vision modality')
  if source['role'] in ('system','developer'):
   if any(part['type']!='text' for part in converted):raise ValueError('Instructions must be text')
   instructions.extend(part['text'] for part in converted)
  else:output.append({'role':source['role'],'content':converted})
 if instructions:output.insert(0,{'role':'system','content':[{'type':'text','text':'\n\n'.join(instructions)}]})
 if not output:raise ValueError('Conversation required')
 return output,images

def load_vision(folder,torch,attention):
 from transformers import AutoProcessor,LlavaForConditionalGeneration
 processor=AutoProcessor.from_pretrained(str(folder),local_files_only=True,trust_remote_code=False)
 model=LlavaForConditionalGeneration.from_pretrained(str(folder),local_files_only=True,trust_remote_code=False,use_safetensors=True,dtype=torch.float32,device_map='cpu',**attention).eval()
 if not processor.chat_template:raise ValueError('Vision processor has no local chat template')
 processor.patch_size=model.config.vision_config.patch_size
 processor.vision_feature_select_strategy=model.config.vision_feature_select_strategy
 processor.num_additional_image_tokens=1
 return model,processor

def prepare_inputs(processor,messages,device):
 normalized,images=image_inputs(messages)
 prompt=processor.apply_chat_template(normalized,tokenize=False,add_generation_prompt=True)
 options={'text':prompt,'return_tensors':'pt','padding':False}
 if images:options['images']=images
 return processor(**options).to(device)
