(()=>{
 const host=document.getElementById('view-monitor');if(!host)return;const notice=document.createElement('div');notice.className='configuration-assistant';notice.hidden=true;notice.setAttribute('role','status');host.prepend(notice);let busy=false;
 async function refresh(){if(document.hidden||busy)return;busy=true;try{const key=document.getElementById('api-key')?.value||sessionStorage.getItem('strata-api-key'),headers={};if(key)headers.Authorization='Bearer '+key;const response=await fetch('metrics',{headers});if(!response.ok)return;const data=await response.json(),warnings=data.performance_profile?.warnings||[];notice.hidden=!warnings.length;notice.textContent=warnings.map(row=>row.message+(row.previous!=null?' · '+row.current+' → '+row.previous:'')).join(' · ');}catch{}finally{busy=false;}}
 refresh();setInterval(()=>{if(!host.hidden)refresh();},10000);
})();
