(()=>{
 if(location.origin!=='http://127.0.0.1:8090')return;
 const keys=['chat','chat_id','chat_title','chat_draft','conversations'];
 const RETRY_MS=7*24*60*60*1000;                 // one attempt a week, not one per page load
 try{
  const state=localStorage.getItem('localai.storage-migration-8088');
  if(state==='copied')return;
  if(state){try{const s=JSON.parse(state);if(s&&s.state==='unavailable'&&Date.now()-(s.at||0)<RETRY_MS)return;}catch{}}
  if(['chat','conversations'].some(key=>{const value=JSON.parse(localStorage.getItem('strata.'+key)||'[]');return !Array.isArray(value)||value.length;}))return;
 }catch{return;}
 const token=crypto.randomUUID(),frame=document.createElement('iframe');frame.hidden=true;frame.src='http://127.0.0.1:8088/web/localai-storage-bridge.svg#'+token;
 const cleanup=()=>{removeEventListener('message',receive);frame.remove();clearTimeout(timeout);};
 function receive(event){
  if(event.origin!=='http://127.0.0.1:8088'||event.source!==frame.contentWindow||event.data?.type!=='localai-storage-export'||event.data.token!==token)return;
  const data=event.data.data;if(!data||typeof data!=='object'){cleanup();return;}
  try{
   const values={};for(const key of keys){if(data[key]!==undefined){if(typeof data[key]!=='string')throw Error('Invalid archive');values[key]=JSON.parse(data[key]);}}
   if(JSON.stringify(values).length>8*1024*1024)throw Error('Archive too large');
   if(values.chat!==undefined&&!Array.isArray(values.chat)||values.conversations!==undefined&&!Array.isArray(values.conversations))throw Error('Invalid archive');
   // Recheck immediately before writing: an existing destination is never overwritten.
   if(['chat','conversations'].some(key=>JSON.parse(localStorage.getItem('strata.'+key)||'[]').length)){cleanup();return;}
   const hasContent=values.chat?.length||values.conversations?.length||values.chat_draft;
   if(hasContent){for(const [key,value] of Object.entries(values))localStorage.setItem('strata.'+key,JSON.stringify(value));}
   localStorage.setItem('localai.storage-migration-8088','copied');cleanup();if(hasContent)location.reload();
  }catch{cleanup();}
 }
 addEventListener('message',receive);
 const timeout=setTimeout(()=>{try{localStorage.setItem('localai.storage-migration-8088',JSON.stringify({state:'unavailable',at:Date.now()}));}catch{}cleanup();},5000);
 document.documentElement.append(frame);
})();
