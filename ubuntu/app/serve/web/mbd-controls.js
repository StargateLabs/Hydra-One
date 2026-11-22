/* Original MBD bandwidth choices. This panel never downloads or starts work. */
(()=>{
 const form=document.getElementById('generation-form'),task=document.getElementById('generation-task');
 if(!form||!task)return;
 const panel=document.createElement('section');panel.className='generation-grid';
 panel.innerHTML='<label><span>MultiBand Diffusion · banda audio</span><select id="mbd-bandwidth" class="st-input"><option value="1.5">1,5 kbps · 2 codebook</option><option value="3" selected>3 kbps · 4 codebook</option><option value="6">6 kbps · 8 codebook</option></select></label><p class="dm__sub">Ricostruisce un audio della libreria con il decoder originale Meta. Richiede pesi MBD e codec EnCodec a 24 kHz locali. Massimo 10 secondi su CPU; l’originale viene conservato.</p>';
 form.querySelector('footer').before(panel);
 const update=()=>{panel.hidden=task.value!=='mbd';document.getElementById('mbd-bandwidth').disabled=panel.hidden;};
 task.addEventListener('change',update);update();
})();
