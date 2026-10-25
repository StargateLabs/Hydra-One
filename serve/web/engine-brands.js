/* Official project assets, served locally without tracking requests. */

(()=>{

 const assets={hydra:['hydra-one.png','HYDRA ONE Â· Stargate Lab'],colibri:['colibri.svg','Colibri'],strata:['hydra-one.png','Hydra One'], 'llama.cpp':['llama.cpp.svg','llama.cpp'],unsloth:['unsloth-symbol.png','Unsloth'],soup:['soup.png','Soup'],'whisper.cpp':['unsloth-symbol.png','Unsloth Â· whisper.cpp distribution'],'audio.cpp':['unsloth-symbol.png','Unsloth Â· audio.cpp distribution']};

 const harnesses={opencode:'OpenCode',dsh:'DeepSeek Harness',trueforge:'TrueForge',hermes:'Hermes Agent',claude:'Claude Code'};

 Object.assign(assets,{airllm:['airllm.png','AirLLM'],voicestudio:['voicestudio.ico','VoiceStudio Â· icona originale'],browser:['browser.svg','Playwright'],memory:['memory.svg','Model Context Protocol Â· memory server'],transformers:['transformers.svg','Hugging Face Transformers'],pytorch:['pytorch.svg','PyTorch'],node:['node.svg','Node.js'],git:['git.svg','Git Â· Jason Long Â· CC BY 3.0'],uv:['uv.svg','uv Â· Astral'],npm:['npm.svg','npm'],python:['python.svg','Python Software Foundation'],antigravity:['antigravity.ico','Antigravity Â· icona originale'],'claude-desktop':['claude-desktop.ico','Claude Desktop Â· icona originale'],openwebui:['openwebui.svg','Open WebUI'],meta:['meta-audio.svg','Meta Â· AudioCraft'],modelscope:['modelscope.svg','ModelScope'],openvoice:['myshell-original.svg','MyShell Â· OpenVoice'],huggingface:['transformers.svg','Hugging Face'],amd:['../amd-logo.png','AMD']});

 assets.openai=['openai-black.svg','OpenAI Â· formato API compatibile'];

 const aliases={safetensors:'huggingface',diffusers:'huggingface',trl:'huggingface',peft:'huggingface',datasets:'huggingface',accelerate:'huggingface',musicgen:'meta',htdemucs:'meta',kokoro:'huggingface',pockettts:'huggingface','node.js':'node',whisper:'whisper.cpp',tts:'audio.cpp','voice-conversion':'openvoice'};

 function identity(id){id=String(id).split(':').at(-1).toLowerCase();return aliases[id]||id;}

 function markup(id){id=identity(id);const a=assets[id],name=harnesses[id];if(!a&&!name)return '';const dark=document.documentElement.dataset.theme==='dark',suffix=dark&&['dsh','trueforge','hermes'].includes(id)?'-dark':'';const src=(id==='hydra'||id==='strata')?'hydra-one.png':id==='openai'?`brand-openai-${dark?'white':'black'}.svg`:id==='amd'?'amd-logo.png':id==='claude'?'harness-logo-claude.png':name?`harness-logo-${id}${suffix}.svg`:`brand-${a[0]}`;return `<img class="engine-brand-logo" data-i18n-ignore="true" data-brand="${id}" src="web/${src}" alt="" title="${name||a[1]}" width="44" height="44" decoding="async">`;}

 const selectedEngine=()=>String(window.StrataUnifiedEngine?.selected?.()||'strata').startsWith('hydra-')?'hydra':'strata';
 window.StrataBrands={markup,selectedEngine,identities:[...Object.keys(assets),...Object.keys(harnesses)],identity};

 new MutationObserver(()=>{for(const img of document.querySelectorAll('.engine-brand-logo[data-brand]')){const replacement=document.createElement('template');replacement.innerHTML=markup(img.dataset.brand);const src=replacement.content.firstChild?.getAttribute('src');if(src&&img.getAttribute('src')!==src)img.setAttribute('src',src);}}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});

 const targets={'vs-title':'voicestudio'};

 let pending=false;

 function decorate(){pending=false;for(const label of document.querySelectorAll('.st-badge, .backend-hub-tags span')){const key=identity(label.textContent.trim());if(assets[key]&&!label.querySelector('.engine-brand-logo'))label.insertAdjacentHTML('afterbegin',markup(key));}for(const [id,brand] of Object.entries(targets)){const heading=document.getElementById(id);if(!heading||heading.querySelector('.engine-brand-logo'))continue;heading.insertAdjacentHTML('afterbegin',markup(brand));}const tools={asr:'whisper.cpp',tts:'audio.cpp',separation:'meta',music:'meta',voice_conversion:'openvoice',image:'huggingface',video:'modelscope',vision:'strata',voicestudio:'voicestudio',library:'strata'};for(const button of document.querySelectorAll('.media-tool')){const brand=button.dataset.tool==='vision'?selectedEngine():tools[button.dataset.tool];const current=button.querySelector('.engine-brand-logo');if(current&&button.dataset.tool==='vision'&&current.dataset.brand!==brand){const template=document.createElement('template');template.innerHTML=markup(brand);current.replaceWith(template.content.firstElementChild);}if(button.querySelectorAll('img').length>1)button.querySelectorAll('.engine-brand-logo').forEach(image=>image.remove());if(brand&&!button.querySelector('img,svg'))button.insertAdjacentHTML('afterbegin',markup(brand));}}

 new MutationObserver(()=>{if(!pending){pending=true;requestAnimationFrame(decorate);}}).observe(document.body,{childList:true,subtree:true});document.addEventListener('strata:engine-selected',decorate);decorate();

})();



