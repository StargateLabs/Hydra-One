(()=>{
 if(location.origin!=='http://127.0.0.1:8088'||window.parent===window)return;
 const token=location.hash.slice(1);if(!/^[a-f0-9-]{36}$/i.test(token))return;
 const keys=['chat','chat_id','chat_title','chat_draft','conversations'];
 const data={};for(const key of keys){const value=localStorage.getItem('strata.'+key);if(value!==null)data[key]=value;}
 window.parent.postMessage({type:'localai-storage-export',token,data},'http://127.0.0.1:8090');
})();
