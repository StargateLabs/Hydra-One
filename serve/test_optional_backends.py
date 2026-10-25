import tempfile
import threading
import unittest
from unittest.mock import patch

from serve.optional_backends import OptionalBackends


class LifecycleTests(unittest.TestCase):
    def test_manual_cpu_start_rejects_combined_draft_ram_before_worker(self):
        from pathlib import Path
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root,discover_models=False);python=Path(root)/'python.exe';python.touch()
            info={'model_max_context':8192,'bytes':512*1024**2,'kv_bytes_per_token':32}
            with patch('serve.safetensors_runtime.inspect_model',side_effect=lambda path:dict(info)),patch('serve.python_inference_update.selected_python',return_value=python),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=int(11.5*2**30))),patch('serve.optional_backends.threading.Thread') as worker:
                with self.assertRaisesRegex(ValueError,'RAM'):
                    backend.start({'mode':'safetensors','model_path':root,'context':1024,'gpu':False,'runtime':{'python_draft_path':root}},True)
                worker.assert_not_called()


    def test_python_draft_memory_and_context_are_included(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root,discover_models=False)
            target=dict(bytes=1024**3,kv_bytes_per_token=512,model_max_context=8192)
            draft=dict(bytes=512*1024**2,kv_bytes_per_token=256,model_max_context=2048)
            with patch('serve.safetensors_runtime.inspect_model',side_effect=[target,draft]),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=64*2**30)):
                result=backend.python_context_plan({'model_path':root,'runtime':{'python_draft_path':root}})
            self.assertEqual(result['model_max_context'],2048)
            self.assertEqual(result['kv_bytes_per_token'],768)
            self.assertEqual(result['weights_gib'],3)
            self.assertEqual(result['recommended_context'],2048)


    def test_draft_limits_reject_invalid_values_before_start(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root,discover_models=False)
            for runtime in ({'draft_min':-1},{'draft_max':65},{'draft_min':True},{'draft_min':17,'draft_max':16},{'draft_probability':float('nan')},{'draft_probability':float('inf')},{'draft_probability':1.01},{'draft_probability':True}):
                with self.subTest(runtime=runtime),self.assertRaisesRegex(ValueError,'[Dd]raft'):
                    backend.start({'mode':'api','runtime':runtime},operational_idle=True)
            self.assertIsNone(backend.child)
            self.assertIsNone(backend.lease)

    def test_metrics_status_never_scans_model_directories(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root, discover_models=False)
            with patch('pathlib.Path.rglob',side_effect=AssertionError('Metrics must not scan disks')):
                state=backend.status(include_models=False)
            self.assertEqual(state['status'],'idle')
            self.assertEqual(state['local_models'],[])
            self.assertEqual(backend.model_cache_at,0)

    def test_python_gpu_fit_uses_fp16_and_free_vram(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root)
            backend.memory_snapshot=lambda:dict(now=dict(gpu_mem_total=24*2**30,gpu_mem_used=4*2**30))
            info=dict(bytes=4*2**30,kv_bytes_per_token=65536,model_max_context=1048576)
            with patch('serve.safetensors_runtime.inspect_model',return_value=info),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=32*2**30)):
                plan=backend.fit_model(dict(mode='safetensors',model_path=root,gpu=True))
                self.assertTrue(plan['recommended']['gpu'])
                self.assertEqual(plan['kv_type'],'f16')
                self.assertLess(plan['recommended_context'],1048576)
                self.assertTrue(any(row['fits'] for row in plan['options']))
                backend.memory_snapshot=lambda:dict(now=dict(gpu_mem_total=24*2**30,gpu_mem_used=22*2**30))
                with self.assertRaises(ValueError):backend.fit_model(dict(mode='safetensors',model_path=root,gpu=True))

    def test_speed_gpu_fit_never_silently_falls_back_to_cpu(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root,discover_models=False)
            with patch.object(backend,'context_plan',side_effect=ValueError('GPU unavailable')) as plan:
                with self.assertRaisesRegex(ValueError,'GPU'):
                    backend.fit_model(dict(mode='gguf',gpu=True,fit_goal='speed'))
                self.assertEqual(plan.call_count,1)

    def test_speed_fit_preserves_requested_context_instead_of_maximum(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root,discover_models=False)
            options=[dict(context=n,fits=True) for n in (1024,4096,8192,131072)]
            with patch.object(backend,'context_plan',return_value=dict(recommended_context=131072,options=options)):
                fit=backend.fit_model(dict(mode='gguf',gpu=True,context=4096,fit_goal='speed'))
                self.assertEqual(fit['recommended']['context'],4096)
                self.assertEqual(fit['recommended']['fit_goal'],'speed')
                self.assertTrue(fit['recommended']['gpu'])

    def test_gguf_fit_has_no_legacy_context_cap_and_preserves_memory_settings(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root)
            for goal in ('context','balanced','compact'):
                options=[dict(context=n,fits=True) for n in (8192,32768,262144)]
                with patch.object(backend,'context_plan',return_value=dict(recommended_context=262144,options=options)) as preview:
                    fit=backend.fit_model(dict(mode='gguf',gpu=False,fit_goal=goal,runtime=dict(kv_type='q8_0',slots=2,checkpoints=2,cache_ram_mib=512)))
                    self.assertEqual(fit['recommended_context'],262144)
                    self.assertEqual(fit['recommended']['fit_goal'],'context')
                    for name,value in [('kv_type','q8_0'),('slots',2),('checkpoints',2),('cache_ram_mib',512)]:
                        self.assertEqual(preview.call_args.args[0]['runtime'][name],value)

    def test_native_auto_fit_preserves_context_and_cpu_only_parameters(self):
        from pathlib import Path
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root);model=Path(root)/'native';model.mkdir()
            backend.python_runtime=model/'python.exe';backend.python_runtime.touch()
            info=dict(model_max_context=262144,bytes=1024,kv_bytes_per_token=512)
            with patch('serve.safetensors_runtime.inspect_model',return_value=info), \
                 patch('psutil.virtual_memory',return_value=SimpleNamespace(available=64*2**30)), \
                 patch('serve.optional_backends.GpuLease'), \
                 patch('serve.optional_backends.threading.Thread') as worker:
                state=backend.start(dict(mode='safetensors',model_path=str(model),gpu=False,fit_mode='auto',fit_goal='context'),True)
                self.assertEqual(state['context'],262144)
                self.assertEqual(worker.call_args.kwargs['args'][1]['context'],262144)
                self.assertEqual(set(state['runtime']),{'threads'})
                self.assertFalse(state['gpu_requested'])
                self.assertIsNotNone(state['context_plan'])

    def test_nf4_survives_automatic_fit(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root,discover_models=False)
            with patch.object(backend,'python_context_plan',return_value={'options':[{'context':8192,'fits':True}]}):
                result=backend.fit_model(dict(mode='safetensors',gpu=True,runtime={'python_loader':'unsloth','python_quantization':'nf4'}))
            self.assertEqual(result['recommended']['runtime']['python_quantization'],'nf4')

    def test_nf4_rejects_incompatible_device_or_loader_before_worker(self):
        from pathlib import Path
        import json,time
        for gpu,loader in [(False,'unsloth'),(True,'transformers')]:
            with tempfile.TemporaryDirectory() as root:
                backend=OptionalBackends(root,discover_models=False);backend.python_runtime=Path(root)/'python.exe';backend.python_runtime.touch()
                directory=Path(root)/'output/verification';directory.mkdir(parents=True)
                (directory/'amd-gpu-bounded-probe.json').write_text(json.dumps({'passed':True,'finished_at':time.time()}))
                with patch('serve.safetensors_runtime.inspect_model',return_value={'model_max_context':8192,'bytes':1024,'kv_bytes_per_token':32}),patch.object(backend,'_load') as worker:
                    with self.assertRaisesRegex(ValueError,'NF4'):backend.start(dict(mode='safetensors',model_path=root,gpu=gpu,runtime={'python_loader':loader,'python_quantization':'nf4'}),True)
                    worker.assert_not_called()

    def test_native_loader_survives_automatic_fit(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root,discover_models=False)
            with patch.object(backend,'python_context_plan',return_value={'options':[{'context':8192,'fits':True}]}):
                result=backend.fit_model(dict(mode='safetensors',gpu=True,runtime={'python_loader':'unsloth'}))
            self.assertEqual(result['recommended']['runtime']['python_loader'],'unsloth')

    def test_native_loader_rejects_cpu_before_starting_worker(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root,discover_models=False)
            backend.python_runtime=Path(root)/'python.exe';backend.python_runtime.touch()
            with patch('serve.safetensors_runtime.inspect_model',return_value={'model_max_context':8192}),patch('serve.optional_backends.threading.Thread') as worker:
                with self.assertRaisesRegex(ValueError,'richiede GPU'):
                    backend.start(dict(mode='safetensors',model_path=root,gpu=False,runtime={'python_loader':'unsloth'}),True)
                worker.assert_not_called()

    def test_native_fit_goals_and_insufficient_ram(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root)
            info=dict(model_max_context=1048576,bytes=1024,kv_bytes_per_token=512)
            with patch('serve.safetensors_runtime.inspect_model',return_value=info), \
                 patch('psutil.virtual_memory',return_value=SimpleNamespace(available=64*2**30)):
                for goal,target in [('context',1048576),('balanced',1048576),('compact',1048576)]:
                    self.assertEqual(backend.fit_model(dict(mode='safetensors',model_path=root,fit_goal=goal))['recommended_context'],target)
            with patch('serve.safetensors_runtime.inspect_model',return_value=info), \
                 patch('psutil.virtual_memory',return_value=SimpleNamespace(available=2**30)):
                with self.assertRaises(ValueError):backend.fit_model(dict(mode='safetensors',model_path=root))

    def test_context_preview_caps_runtime_free_memory_with_matching_global_gpu(self):
        from pathlib import Path
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root);model=Path(root)/'model.gguf';model.write_bytes(b'GGUF')
            backend.memory_snapshot=lambda:dict(now=dict(gpu_mem_used=22*2**30,gpu_mem_total=24*2**30),static=dict(gpu_name='AMD Radeon RX 7900 XTX'))
            runtime=SimpleNamespace(returncode=0,stdout='ROCm0: AMD Radeon RX 7900 XTX (24560 MiB, 24410 MiB free)',stderr='')
            with patch('serve.catalogue.read_gguf_header',return_value=dict(meta={'general.architecture':'unknown'})),patch('serve.optional_backends.subprocess.run',return_value=runtime),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=64*2**30)):
                preview=backend.context_plan(dict(model_path=str(model),gpu=True))
                self.assertEqual(preview['gpu_free_gib'],2)
                self.assertEqual(preview['gpu_memory_source'],'runtime_and_system_telemetry')
                self.assertTrue(all(not row['fits'] for row in preview['options']))
                backend.memory_snapshot=lambda:dict(now=dict(gpu_mem_used=22*2**30,gpu_mem_total=24*2**30),static=dict(gpu_name='Other GPU'))
                self.assertGreater(backend.context_plan(dict(model_path=str(model),gpu=True))['gpu_free_gib'],23)

    def test_auto_fit_keeps_memory_checked_context_in_loader_payload(self):
        from pathlib import Path
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root)
            model=Path(root)/'model.gguf';model.write_bytes(b'GGUF')
            backend.binary=model
            row=dict(context=262144,fits=True,kv_gib=1,ram_required_gib=2)
            plan=dict(recommended_context=32768,options=[row])
            recommended=dict(context=262144,context_mode='auto',fit_mode='auto',gpu=True,
                             profile='rocm',runtime=dict(slots=1),fit_goal='context')
            with patch.object(backend,'fit_model',return_value=dict(recommended=recommended)), \
                 patch.object(backend,'context_plan',return_value=plan), \
                 patch('serve.catalogue.read_gguf_header',return_value=dict(meta={'general.architecture':'fixture','fixture.context_length':1048576})), \
                 patch('psutil.virtual_memory',return_value=SimpleNamespace(available=64*2**30)), \
                 patch('serve.optional_backends.GpuLease'), \
                 patch('serve.optional_backends.threading.Thread') as worker:
                state=backend.start(dict(mode='gguf',model_path=str(model),fit_mode='auto'),True)
                self.assertEqual(state['context'],262144)
                self.assertEqual(worker.call_args.kwargs['args'][1]['context'],262144)

    def test_activity_uses_runtime_timings_without_inventing_tokens(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root)
            backend.state.update(status='ready',mode='gguf',model='fixture',api_model='fixture')
            with patch('serve.optional_backends.LocalOpenAIBackend') as factory:
                backend.client=factory.return_value
                backend.client.chat.return_value=iter([dict(choices=[dict(delta=dict(content='ok'))],timings=dict(predicted_n=2,predicted_per_second=123)),dict(choices=[],usage=dict(completion_tokens=2))])
                events=list(backend.chat(dict(messages=[dict(role='user',content='hi')],stream=True),threading.Event()))
                self.assertEqual(events[0]['model'],'local/fixture')
                self.assertEqual(backend.client.chat.call_args.kwargs['timings_per_token'],True)
                status=backend.status()
                self.assertEqual(status['activity']['state'],'complete')
                self.assertEqual(status['last_request']['timings']['predicted_n'],2)
                self.assertFalse(status['busy'])

    def test_api_discovery_keeps_credentials_out_of_status(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root)
            with patch('serve.optional_backends.LocalOpenAIBackend') as factory:
                factory.return_value.models.return_value=[{'id':'actual-model','other':'not needed'}]
                self.assertEqual(backend.probe_api(dict(url='http://127.0.0.1:8888/v1',api_key='secret-fixture')),{'models':[{'id':'actual-model'}]})
                self.assertEqual(factory.call_args.kwargs['api_key'],'secret-fixture')
            self.assertNotIn('secret-fixture',str(backend.status()))
            self.assertIsNone(backend.lease)
            with self.assertRaises(ValueError):backend.api_client(dict(url='http://127.0.0.1:8090/v1'))
            self.assertIsNotNone(backend.api_client(dict(url='http://127.0.0.1:8088/v1')))
            backend.dashboard_port=18090
            with self.assertRaises(ValueError):backend.api_client(dict(url='http://127.0.0.1:18090/v1'))

    def test_cancelled_load_cannot_replace_new_backend(self):
        entered, release, finished = (threading.Event() for _ in range(3))

        class Client:
            def __init__(self, url, **kwargs):
                self.url = url

            def models(self):
                entered.set()
                release.wait(3)
                raise RuntimeError('Old connection failed')

        with tempfile.TemporaryDirectory() as root:
            backend = OptionalBackends(root)
            old = backend.cancel_load
            backend.state['status'] = 'loading'
            with patch('serve.optional_backends.LocalOpenAIBackend', Client):
                def load():
                    try:
                        backend._load('api', {'url': 'http://localhost:8091/v1', 'model': 'old'}, None, old)
                    finally:
                        finished.set()
                worker = threading.Thread(target=load)
                worker.start()
                self.assertTrue(entered.wait(3))
                backend.stop()
                with backend.lock:
                    backend.cancel_load = threading.Event()
                    backend.state.update(status='ready', model='new')
                release.set()
                self.assertTrue(finished.wait(3))
                worker.join()
                self.assertEqual(backend.status()['status'], 'ready')
                self.assertEqual(backend.status()['model'], 'new')
            backend.stop()

    def test_busy_response_prevents_release(self):
        with tempfile.TemporaryDirectory() as root:
            backend = OptionalBackends(root)
            backend.request_lock.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, 'risposta'):
                    backend.stop()
                self.assertFalse(backend.cancel_load.is_set())
            finally:
                backend.request_lock.release()
                backend.stop()

    def test_operational_model_blocks_start(self):
        with tempfile.TemporaryDirectory() as root:
            backend = OptionalBackends(root)
            with self.assertRaisesRegex(RuntimeError, 'Ferma'):
                backend.start({'mode': 'api'}, operational_idle=False)
            self.assertIsNone(backend.lease)
            backend.stop()

    def test_fit_rejects_malformed_runtime_before_resource_probe(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root)
            with patch.object(backend,'context_plan') as probe:
                for runtime in (None,[],False,'invalid'):
                    with self.assertRaisesRegex(ValueError,'runtime'):
                        backend.fit_model({'mode':'gguf','runtime':runtime})
                probe.assert_not_called()

    def test_rocm_profile_requires_gpu_and_rejects_unknown_profiles(self):
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root)
            for payload in ({'mode':'gguf','profile':'rocm','gpu':False},{'mode':'api','profile':'rocm','gpu':True},{'mode':'gguf','profile':'unchecked'}):
                with self.assertRaises(ValueError):backend.start(payload,operational_idle=True)
            self.assertIsNone(backend.lease)

    def test_gguf_lora_adapter_is_forwarded_to_llama_server(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root,discover_models=False)
            model=Path(root)/'model.gguf';model.write_bytes(b'GGUF')
            adapter=Path(root)/'lora.gguf';adapter.write_bytes(b'GGUF')
            backend.binary=Path(root)/'llama-server.exe';backend.binary.touch()
            with patch('serve.optional_backends.subprocess.Popen') as popen, \
                    patch('socket.socket') as socket_factory:
                # This is an argv contract test, independent of a live model's
                # port. No process is started; exercise real ports separately.
                socket_factory.return_value.__enter__.return_value.connect_ex.return_value=1
                popen.return_value.poll.return_value=1
                backend._load('gguf',dict(mode='gguf',model_path=str(model),adapter_path=str(adapter),context=4096,gpu=False),model,backend.cancel_load)
                command=popen.call_args.args[0]
                self.assertIn('--lora',command)
                self.assertEqual(command[command.index('--lora')+1],str(adapter))

    def test_gguf_lora_adapter_must_be_a_local_gguf_file(self):
        from pathlib import Path
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            model=Path(root)/'model.gguf';model.write_bytes(b'GGUF')
            cases=[(None,False),('',False),(str(Path(root)/'missing.gguf'),True),(str(model).replace('.gguf','.safetensors'),True)]
            for adapter,rejected in cases:
                with self.subTest(adapter=adapter):
                    backend=OptionalBackends(root,discover_models=False)
                    backend.binary=Path(root)/'llama-server.exe';backend.binary.touch()
                    payload=dict(mode='gguf',model_path=str(model),context=1024,gpu=False)
                    if adapter is not None:payload['adapter_path']=adapter
                    if rejected:
                        with self.assertRaisesRegex(ValueError,'[Ll]oRA'):backend.start(payload,operational_idle=True)
                        self.assertIsNone(backend.lease)
                    else:
                        with patch('serve.optional_backends.subprocess.Popen'),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=64*2**30)),patch('serve.optional_backends.GpuLease'),patch('serve.optional_backends.threading.Thread') as worker,patch('serve.catalogue.read_gguf_header',return_value={'meta':{}}):
                            backend.start(payload,True);worker.assert_called_once()
                            self.assertFalse(worker.call_args.kwargs['args'][1].get('adapter_path'))

    def test_large_gguf_uses_available_ram_instead_of_fixed_file_limit(self):
        import os
        from pathlib import Path
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            backend=OptionalBackends(root);model=Path(root)/'large.gguf';model.write_bytes(b'GGUF');backend.binary=model
            original_stat=Path.stat
            def file_stat(path,*args,**kwargs):
                original=original_stat(path,*args,**kwargs)
                return os.stat_result((*original[:6],52*2**30,*original[7:])) if path==model else original
            with patch('pathlib.Path.stat',file_stat),patch('serve.catalogue.read_gguf_header',return_value={'meta':{}}),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=128*2**30)),patch('serve.optional_backends.GpuLease'),patch('serve.optional_backends.threading.Thread') as worker,patch.object(backend,'status',return_value={'status':'loading'}):
                backend.start({'mode':'gguf','model_path':str(model),'context':1024,'gpu':False},True)
                worker.assert_called_once()
            backend.state={'status':'idle'}
            with patch('pathlib.Path.stat',file_stat),patch('serve.catalogue.read_gguf_header',return_value={'meta':{}}),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=56*2**30)),patch('serve.optional_backends.threading.Thread') as worker:
                with self.assertRaisesRegex(ValueError,'RAM'):backend.start({'mode':'gguf','model_path':str(model),'context':1024,'gpu':False},True)
                worker.assert_not_called()


if __name__ == '__main__':
    unittest.main()

class SharedThinkingProfile(unittest.TestCase):
    def test_harness_requests_use_saved_none_but_explicit_request_wins(self):
        from types import SimpleNamespace
        seen=[]
        def chat(*args,**options):
            seen.append(options)
            yield {'choices':[{'message':{'content':'hello'},'finish_reason':'stop'}],'usage':{'completion_tokens':1}}
        with tempfile.TemporaryDirectory() as folder:
            backend=OptionalBackends(folder,discover_models=False)
            backend.state.update(status='ready',model='fixture',api_model='fixture',mode='api',inference_profile={'thinking':'none'})
            backend.client=SimpleNamespace(chat=chat)
            list(backend.chat({'messages':[],'stream':False},threading.Event()))
            self.assertFalse(seen[-1]['chat_template_kwargs']['enable_thinking'])
            list(backend.chat({'messages':[],'stream':False,'chat_template_kwargs':{'enable_thinking':True}},threading.Event()))
            self.assertTrue(seen[-1]['chat_template_kwargs']['enable_thinking'])
