/* Interface-only localisation. No reload, no value/payload/content rewriting. */
(()=>{
 'use strict';
 const data=window.StrataLanguageData;
 const normal=s=>String(s).replace(/[’‘]/g,"'").replace(/…/g,'...').replace(/\s+/g,' ').trim();
 const entries=Object.entries(data.pairs),exact=new Map(),reverse=new Map(),aliases=new Map(Object.entries(data.aliases).map(([a,b])=>[normal(a),b]));
 const patterns=[];
 function pattern(template){
  const captures=[];let source='',at=0;const regex=/\{(\d+)\}/g;let match;
  const escape=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  while((match=regex.exec(template))){source+=escape(template.slice(at,match.index))+'((?:(?![·]|[.!?](?:\\s|$)).)+?)';captures.push(match[1]);at=regex.lastIndex;}
  source+=escape(template.slice(at));return {regex:new RegExp('^'+source+'$','u'),captures};
 }
 for(const [it,en] of entries){
  // Asset filenames are not Italian labels. Reversing them corrupts brand names.
  if(/^[\w./-]+\.(?:svg|png|ico|jpg|jpeg|webp)$/i.test(it))continue;
  if(it===en)continue;
  if(/\{\d+\}/.test(it)){patterns.push({it,en,a:pattern(normal(it)),b:pattern(normal(en))});}
  else{exact.set(normal(it),[it,en]);if(!reverse.has(normal(en)))reverse.set(normal(en),it);}
 }
 patterns.sort((a,b)=>b.it.replace(/\{\d+\}/g,'').length-a.it.replace(/\{\d+\}/g,'').length);
 let language='it';try{const saved=JSON.parse(localStorage.getItem('strata.language'));if(saved==='en')language='en';}catch(error){}
 const texts=new WeakMap(),attributes=new WeakMap();
 function translate(text,depth=0){
  const key=normal(text);if(!key)return text;
  const source=aliases.get(key)||reverse.get(key)||text;
  const pair=exact.get(normal(source))||exact.get(key);
  if(pair)return language==='en'?pair[1]:pair[0];
  if(depth<6)for(const rule of patterns){
   const direct=rule.a.regex.exec(key),back=direct?null:rule.b.regex.exec(key),match=direct||back;if(!match)continue;
   const format=language==='en'?rule.en:rule.it,slots=direct?rule.a.captures:rule.b.captures,values={};slots.forEach((slot,i)=>values[slot]=translate(match[i+1],depth+1));return format.replace(/\{(\d+)\}/g,(_,slot)=>values[slot]);
  }
  if(depth<6){
   const parts=String(text).split(/(\s+·\s+|\s+—\s+|\s+→\s+|\s+\/\s+|:\s+(?=\p{L})|(?<=[.!?])\s+)/u);
   if(parts.length>1)return parts.map((part,i)=>i%2?part:translate(part,depth+1)).join('');
   if(/[.!?]$/.test(text))return translate(text.slice(0,-1),depth+1)+text.slice(-1);
  }
  return text;
 }
 const protectedSelector='script,style,textarea,pre,code,.st-bubble,.thinking,.tool-call__pre,.tool-call__preview,.tool-call__name,.msg-images,#attachments,#chat-archive-list b,.catalogue-entry h3,.catalogue-entry a,.perf-model,#lab-model option,#ctrl-model option,[data-i18n-ignore]';
 function textNode(node){
  if(!node.parentElement||(node.parentElement.closest(protectedSelector)&&!node.parentElement.closest('[data-code-copy],.msg-error,.tool-call__label,.tool-call .st-badge')))return;
  const previous=texts.get(node),current=node.nodeValue;
  const base=previous&&current===previous.rendered?previous.base:current;
  const trimmed=base.trim();if(!trimmed)return;
  const translated=translate(trimmed),rendered=base.slice(0,base.indexOf(trimmed))+translated+base.slice(base.indexOf(trimmed)+trimmed.length);
  if(node.parentElement.tagName==='OPTION'&&!node.parentElement.hasAttribute('value'))node.parentElement.setAttribute('value',node.parentElement.value);
  texts.set(node,{base,rendered});if(current!==rendered)node.nodeValue=rendered;
 }
 function elementAttributes(el){
  if(el.closest('script,style,pre,code,.st-bubble,.thinking,.tool-call__pre,.msg-images,[data-i18n-ignore]')&&!el.closest('[data-code-copy],.msg-error'))return;
  let records=attributes.get(el);if(!records){records={};attributes.set(el,records);}
  for(const name of ['aria-label','title','placeholder','alt']){
   if(!el.hasAttribute(name))continue;const current=el.getAttribute(name),previous=records[name],base=previous&&current===previous.rendered?previous.base:current,rendered=translate(base);
   records[name]={base,rendered};if(current!==rendered)el.setAttribute(name,rendered);
  }
 }
 function apply(root){
  if(root.nodeType===Node.TEXT_NODE){textNode(root);return;}
  if(root.nodeType!==Node.ELEMENT_NODE)return;
  elementAttributes(root);const walker=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT);
  let node;while((node=walker.nextNode())){if(node.nodeType===Node.TEXT_NODE)textNode(node);else elementAttributes(node);}
 }
 function setLanguage(next,persist=true){
  language=next==='en'?'en':'it';document.documentElement.lang=language;
  if(persist)try{localStorage.setItem('strata.language',JSON.stringify(language));}catch(error){}
  for(const button of document.querySelectorAll('[data-language]'))button.setAttribute('aria-pressed',String(button.dataset.language===language));
  apply(document.body);window.dispatchEvent(new CustomEvent('strata:languagechange',{detail:{language}}));
 }
 const observer=new MutationObserver(records=>{
  const roots=new Set();for(const record of records){if(record.type==='characterData')roots.add(record.target);else if(record.type==='attributes')elementAttributes(record.target);else for(const node of record.addedNodes)roots.add(node);}
  for(const root of roots)apply(root);
 });
 window.uiLocale=()=>language==='en'?'en-GB':'it-IT';
 window.StrataI18n={text:translate,setLanguage,get language(){return language;},prompt(text){
  if(language!=='en')return text.replace(/\\n/g,'\n');
  const starters={
   'Spiega questo argomento con esempi e passaggi chiari:':'Explain this topic with examples and clear steps:',
   'Analizza questo testo e individua punti critici e possibili miglioramenti:':'Analyse this text and identify critical points and possible improvements:',
   'Scrivi una soluzione in codice, spiegando scelte e casi limite:':'Write a solution in code, explaining decisions and edge cases:',
   'Rivedi questo testo migliorando chiarezza e precisione, mantenendo il significato:':'Revise this text for clarity and accuracy while preserving its meaning:'
  };const value=text.replace(/\\n/g,'\n');return (starters[value.trim()]||value.trim())+'\n';
 }};
 for(const button of document.querySelectorAll('[data-language]'))button.addEventListener('click',()=>setLanguage(button.dataset.language));
 setLanguage(language,false);
 observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['aria-label','title','placeholder','alt']});
})();
