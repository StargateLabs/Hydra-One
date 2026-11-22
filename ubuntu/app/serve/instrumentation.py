"""Common instrumentation contract for native, optional and API runtimes."""
def active_instrumentation(native_engine,optional,hardware):
 optional=optional or {};active=optional.get('status') in ('ready','loading');engine=native_engine or {};capabilities=optional.get('capabilities') or {}
 row={'source':'optional' if active else 'strata','model':optional.get('public_model') if active else engine.get('model'),'backend':optional.get('backend') if active else engine.get('backend'),'hardware_scope':'host_system','hardware_sensors_available':any(hardware.get(key) is not None for key in ('cpu','ram_used','gpu_mem_used')),'functions':{'monitor':True,'conversation_history':True,'context_preview':True,'local_media_workspace':True,'training_workspace':True,'model_selection':True,'updates':True},'limits':[]}
 if active:
  row['context']=optional.get('context_per_slot') or optional.get('context')
  row['tool_calling']=capabilities.get('tool_calling','unknown');row['image_input']=capabilities.get('images') is True
  row['process_memory_scope']='owned_backend_process' if optional.get('process_resources') else 'unavailable'
  row['timing_scope']=(optional.get('last_request') or {}).get('timings',{}) or {}
  if row['tool_calling'] is False:row['limits'].append('Il modello non supporta chiamate strumenti native; gli strumenti diretti della dashboard restano disponibili.')
  if optional.get('publisher')=='colibri':
   row['source']='colibri';row['backend']='Colibri'
  elif optional.get('mode')=='api':row['limits'].append('Sensori riferiti alla macchina host; memoria e tempi del processo API esterno dipendono dalla telemetria fornita dal servizio.')
 else:
  row['context']=engine.get('max_context');row['tool_calling']='model_dependent';row['image_input']=engine.get('images') is True;row['process_memory_scope']='native_engine'
 return row
