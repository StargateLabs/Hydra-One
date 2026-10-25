"""Apply a verified harness update and restart only an idle managed component."""
def activate_managed(service,kind,factory,rollback=False):
 manager=factory();state=manager.status()
 if state.get('busy') or state.get('owned_process') and state.get('activity_known') is not True:raise ValueError('Harness occupato o attività non verificabile: attesa del termine del lavoro')
 if state.get('status')=='starting':raise ValueError('Attendi il completamento dell’avvio dell’harness')
 restart=state.get('status')=='ready'
 if restart:manager.stop()
 try:service.update_center.harness_updates.activate(kind,rollback=rollback)
 except Exception:
  if restart:manager.start()
  raise
 attr='agent_harness' if kind=='opencode' else 'agent_harness_'+kind
 with service.status_lock:setattr(service,attr,None)
 if kind=='hermes':
  from serve.hermes_integration import runtime,installed_version
  runtime.cache_clear();installed_version.cache_clear()
 replacement=None
 try:
  replacement=factory()
  if restart:replacement.start()
 except Exception as error:
  service.update_center.harness_updates.activate(kind,rollback=True)
  with service.status_lock:setattr(service,attr,manager)
  if restart:
   try:manager.start()
   except Exception as recovery:raise RuntimeError('Aggiornamento non applicato; selezione precedente ripristinata, avvio da verificare: '+str(recovery)) from error
  raise RuntimeError('Aggiornamento non applicato; versione precedente ripristinata: '+str(error)) from error
 job=service.update_center.harness_updates
 with job.lock:
  job.job.update(restart_verified=restart,activation_verified=True)
  job.persist()
 return replacement.status()
