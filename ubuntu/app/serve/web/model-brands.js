/* Original publisher assets; local model metadata never leaves the browser here. */
(()=>{
 const publishers={"xhtoken":"brand-model-spark.png","qwen": "brand-model-qwen.svg", "deepseek-ai": "brand-model-deepseek-ai.webp", "google": "brand-model-google.webp", "mistralai": "brand-model-mistralai.webp", "openbmb": "brand-model-openbmb.webp", "huggingfacetb": "brand-model-huggingfacetb.webp", "meta-llama": "brand-model-meta-llama.webp"};
 const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function modelMarkup(row){
  const author=String(row.base_author||row.author||row.repo?.split('/')[0]||'').toLowerCase();
  const name=[row.name,row.repo,row.base_repo].filter(Boolean).join(' ');
  let owner=publishers[author]?author:/spark-x2[.]5/i.test(name)?'xhtoken':/qwen/i.test(name)?'qwen':/deepseek/i.test(name)?'deepseek-ai':/gemma/i.test(name)?'google':/mistral|mixtral/i.test(name)?'mistralai':/minicpm/i.test(name)?'openbmb':/smollm|smolvlm/i.test(name)?'huggingfacetb':/llama/i.test(name)?'meta-llama':null;
  if(owner&&publishers[owner])return '<img class="model-brand-logo" src="web/'+publishers[owner]+'" alt="" title="'+esc(owner)+' · riferimento editore/famiglia" width="30" height="30" decoding="async">';
  return '';
 }
 function engineMarkup(value){return({strata:['strata'],'hydra-strata':['hydra'],'hydra-gguf':['hydra'],'hydra-safetensors':['hydra'],gguf:['llama.cpp','unsloth'],safetensors:['huggingface','python'],api:['openai'],colibri:['colibri'],transformers:['transformers'],unsloth:['unsloth'],airllm:['airllm']})[value]?.map(id=>window.StrataBrands?.markup(id)||'').join('')||'';}
 function optionMarkup(select,option){
  if(['unified-engine','backend-mode','backend-python-loader'].includes(select.id))return engineMarkup(option.value);
  if(!/model|projector/i.test(select.id)||!option.value)return '';
  const rows=window.StrataOptional?.localModels?.()||[];
  return modelMarkup(rows.find(row=>row.path===option.value||row.name===option.value)||{name:option.textContent});
 }
 window.StrataModelBrands={modelMarkup,engineMarkup,optionMarkup};
})();
