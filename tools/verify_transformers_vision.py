"""Tiny untrained LLaVA CPU proof; does not measure image understanding quality."""
import base64,hashlib,io,json,os,socket,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
import torch
from PIL import Image
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import LlavaConfig,LlavaForConditionalGeneration,LlavaProcessor,CLIPImageProcessor,PreTrainedTokenizerFast
folder=ROOT/'output/verification/llava-cpu-fixture';folder.mkdir(exist_ok=True)
torch.set_num_threads(2);torch.manual_seed(42)
tokenizer=Tokenizer(WordLevel({'[UNK]':0,'[PAD]':1,'[BOS]':2,'[EOS]':3,'<image>':4,'USER':5,'ASSISTANT':6,':':7,'Describe':8,'this':9,'image':10,'red':11,'blue':12,'green':13,'square':14,'.':15},unk_token='[UNK]'));tokenizer.pre_tokenizer=Whitespace()
fast=PreTrainedTokenizerFast(tokenizer_object=tokenizer,unk_token='[UNK]',pad_token='[PAD]',bos_token='[BOS]',eos_token='[EOS]',additional_special_tokens=['<image>'])
template="{% for message in messages %}{{ message['role'] }}: {% for part in message['content'] %}{% if part['type'] == 'image' %}<image> {% else %}{{ part['text'] }} {% endif %}{% endfor %}{% endfor %}ASSISTANT:"
fast.chat_template=template
config=LlavaConfig(vision_config={'model_type':'clip_vision_model','hidden_size':16,'intermediate_size':32,'num_hidden_layers':2,'num_attention_heads':2,'image_size':16,'patch_size':4},text_config={'model_type':'llama','vocab_size':16,'hidden_size':16,'intermediate_size':32,'num_hidden_layers':1,'num_attention_heads':2,'num_key_value_heads':2,'max_position_embeddings':2048,'pad_token_id':1,'bos_token_id':2,'eos_token_id':3},image_token_index=4,image_token_id=4,image_seq_length=16,vision_feature_layer=-2)
model=LlavaForConditionalGeneration(config);model.save_pretrained(folder,safe_serialization=True)
processor=LlavaProcessor(CLIPImageProcessor(size={'shortest_edge':16},crop_size={'height':16,'width':16}),fast,patch_size=4,num_additional_image_tokens=1,vision_feature_select_strategy='default',chat_template=template);processor.save_pretrained(folder)
(folder/'FIXTURE-NOT-A-TRAINED-MODEL.txt').write_text('Random fixture. No quality/performance claim.')
weights=folder/'model.safetensors';before=hashlib.sha256(weights.read_bytes()).hexdigest()
image=io.BytesIO();Image.new('RGB',(16,16),'red').save(image,format='PNG')
messages=[{'role':'user','content':[{'type':'text','text':'Describe this image'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image.getvalue()).decode()}}]}]
from serve.transformers_vision import load_vision,prepare_inputs
loaded,local_processor=load_vision(folder,torch,{'attn_implementation':'sdpa'})
inputs=prepare_inputs(local_processor,messages,'cpu');assert 'pixel_values' in inputs
with torch.inference_mode():tokens=loaded.generate(**inputs,max_new_tokens=4,do_sample=False,pad_token_id=1)
count=tokens.shape[-1]-inputs['input_ids'].shape[-1];assert count>0
result={'passed':True,'device':'cpu','framework_version':__import__('transformers').__version__,'input_modalities':['text','image'],'processor':'AutoProcessor','pixel_values_shape':list(inputs['pixel_values'].shape),'completion_tokens':count,'original_weights_unchanged':hashlib.sha256(weights.read_bytes()).hexdigest()==before,'scope':'Untrained tiny LLaVA fixture; not an image quality or speed test'}
(ROOT/'output/verification/transformers-vision-cpu.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
