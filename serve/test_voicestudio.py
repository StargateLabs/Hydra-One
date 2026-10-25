import base64
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
from unittest.mock import patch

from serve.voicestudio import VoiceStudio


class ConnectorTests(unittest.TestCase):
    def test_stop_only_managed_host_and_preserves_active_generation(self):
        client=VoiceStudio(root=self.workdir.name)
        with patch('serve.process_lifecycle.stop_owned_tree') as stop, patch.object(client,'_request',return_value=(b'{"jobs":[]}', 'fixture', 'application/json')):
            self.assertFalse(client.stop()['managed'])
            stop.assert_not_called()
            child=client._web_process=object()
            client._busy.acquire()
            self.assertTrue(client.stop()['busy'])
            stop.assert_not_called()
            client._busy.release()
            self.assertTrue(client.stop()['stopped'])
            stop.assert_called_once_with(child)
            self.assertIsNone(client._web_process)

    def test_stop_preserves_model_downloads(self):
        client=VoiceStudio(root=self.workdir.name);client._web_process=object()
        with patch.object(client,'_request',return_value=(b'{"jobs":[{"target":"local","state":"downloading"}]}','fixture','application/json')), patch('serve.process_lifecycle.stop_owned_tree') as stop:
            self.assertTrue(client.stop()['busy'])
            stop.assert_not_called()

    def test_stop_preserves_native_batch_and_persisted_running_jobs(self):
        client=VoiceStudio(root=self.workdir.name);client._web_process=object()
        for active_route in ('/jobs?status=active&limit=500','/batch/jobs?status=running&limit=500','/batch/jobs?status=queued&limit=500'):
            def response(route,*args,**kwargs):
                rows=[{'id':'native-job','status':'running'}] if route==active_route else []
                return (json.dumps({'jobs':rows}).encode(),'fixture','application/json')
            with patch.object(client,'_request',side_effect=response),patch('serve.process_lifecycle.stop_owned_tree') as stop:
                self.assertTrue(client.stop()['busy'])
                stop.assert_not_called()

    def test_web_start_reuses_original_backend_without_desktop_launch(self):
        client=VoiceStudio(root=self.workdir.name)
        with patch.object(client,'web_ui',return_value={'web_ui_available':True,'web_url':client.base_url+'/'}), \
             patch.object(client,'_request',return_value=(b'{"status":"ok"}','0.5.6','application/json')), \
             patch('serve.voicestudio.subprocess.Popen') as launch:
            result=client.ensure_web()
        self.assertTrue(result['reused'])
        launch.assert_not_called()

    def test_status_separates_torch_cpu_from_actual_tts_vulkan(self):
        client = VoiceStudio(root=self.workdir.name)
        evidence = {'evidence_state': 'loaded', 'actual_execution_provider': 'vulkan', 'gpu_name': 'AMD Radeon RX 7900 XTX'}
        responses = [(json.dumps({'status': 'ok', 'device': 'cpu', 'version': '0.5.6'}).encode(), '0.5.6', 'application/json'),
                     (json.dumps({'tts': {'active': 'audiocpp', 'backends': [{'id': 'audiocpp', 'effective_device': 'vulkan', 'execution_evidence': evidence}]}}).encode(), '0.5.6', 'application/json')]
        with patch.object(client, '_request', side_effect=responses):
            state = client.status()
        self.assertEqual(state['device'], 'cpu')
        self.assertEqual(state['active_engine'], 'audiocpp')
        self.assertEqual(state['active_engine_device'], 'vulkan')
        self.assertEqual(state['active_engine_execution'], evidence)
        self.assertEqual(state['active_engine_gpu_name'], 'AMD Radeon RX 7900 XTX')

    def test_install_preserves_engines_and_skips_unsupported_preset(self):
        client = VoiceStudio(root=self.workdir.name)
        state = {'models': [{'repo_id': 'fixture/model', 'installed': False, 'size_gb': 1}],
                 'disk_free_gb': 12, 'min_free_gb': 10, 'performance_preset_applicable': False}
        with patch.object(client, 'setup', return_value=state), patch.object(client, '_request', return_value=(b'{"started":true}', 'fixture', 'application/json')) as request:
            self.assertTrue(client.install({'repo_id': 'fixture/model', 'confirm': True})['downloads_started'])
            request.assert_called_once_with('/models/install', {'repo_id': 'fixture/model', 'target': 'local'}, timeout=30)
            state['models'][0]['installed'] = True
            request.reset_mock()
            self.assertTrue(client.install({'repo_id': 'fixture/model'})['already_installed'])
            request.assert_not_called()
            with self.assertRaises(ValueError): client.install({'repo_id': 'unlisted/model', 'confirm': True})
            state['models'][0]['installed'] = False
            with self.assertRaises(ValueError): client.install({'repo_id': 'fixture/model'})
            state['disk_free_gb'] = 9
            with self.assertRaises(RuntimeError): client.install({'repo_id': 'fixture/model', 'confirm': True})

    def setUp(self):
        self.workdir=tempfile.TemporaryDirectory();self.addCleanup(self.workdir.cleanup)
        self.marker = '1.2.3'
        self.health = {'status': 'ok', 'version': '1.2.3', 'device': 'cpu'}
        self.calls = []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                owner.calls.append(self.path)
                if self.path == '/health': data = owner.health
                else: data = {'voices': [{'id': 'fixture', 'name': 'Fixture voice'}]}
                self.send_response(200)
                if owner.marker: self.send_header('x-omnivoice-backend', owner.marker)
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            def do_POST(self):
                owner.calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.send_header('x-omnivoice-backend', owner.marker)
                self.send_header('Content-Type', 'audio/wav')
                self.end_headers()
                self.wfile.write(b'RIFF\x04\x00\x00\x00WAVEfixture')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = VoiceStudio(base_url='http://127.0.0.1:' + str(self.server.server_port))
        state = self.client.status()
        if '10013' in state['message']:
            self.server.shutdown()
            self.server.server_close()
            self.skipTest('Sandbox blocks outgoing localhost sockets (WinError 10013).')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_actual_http_health_voices_and_audio(self):
        state = self.client.status()
        self.assertTrue(state['connected'])
        self.assertEqual(state['version'], '1.2.3')
        self.assertFalse(state['inference_verified'])
        self.assertEqual(self.client.voices()['voices'][0]['id'], 'fixture')
        result = self.client.speech({'input': 'Hello', 'voice': 'fixture'})
        self.assertTrue(base64.b64decode(result['audio_base64']).startswith(b'RIFF'))
        self.assertEqual(self.calls[-1]['model'], 'tts-1')
        self.assertEqual(self.calls[-1]['response_format'], 'wav')

    def test_native_speech_controls_are_forwarded_and_validated(self):
        self.client.speech({'input':'Fixture','speed':1.25,'instructions':'Calm','language':'it'})
        body=self.calls[-1]
        self.assertEqual(body['speed'],1.25)
        self.assertEqual(body['instructions'],'Calm')
        self.assertEqual(body['language'],'it')
        for speed in (True,0.1,5,float('nan')):
            with self.subTest(speed=speed),self.assertRaises(ValueError):
                self.client.speech({'input':'Fixture','speed':speed})

    def test_unrelated_service_cannot_receive_text(self):
        self.marker = ''
        self.assertFalse(self.client.status()['connected'])
        with self.assertRaises(RuntimeError): self.client.speech({'input': 'Private text'})
        self.assertFalse(any(isinstance(call, dict) for call in self.calls))

    def test_starting_is_not_ready(self):
        self.health['status'] = 'starting'
        self.assertFalse(self.client.status()['connected'])
        with self.assertRaises(RuntimeError): self.client.speech({'input': 'Hello'})

    def test_nonlocal_urls_and_bad_text_rejected(self):
        for url in ('https://example.com', 'http://localhost:3900', 'http://127.0.0.1:3900/path', 'http://user@127.0.0.1:3900'):
            with self.assertRaises(ValueError): VoiceStudio(base_url=url)
        for payload in ({'input': ''}, {'input': 'x'*4097}, {'input': ['wrong type']}):
            with self.assertRaises(ValueError): self.client.speech(payload)

    def test_executable_detection_and_launch_are_separate_from_health(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'tmp') as folder:
            exe=Path(folder)/'VoiceStudio.exe';exe.write_bytes(b'fixture')
            client=VoiceStudio(base_url=self.client.base_url,executable=exe)
            self.assertTrue(client.status()['installed'])
            with patch.object(client,'ensure_web',return_value={'ok':True,'starting':True}),patch('serve.voicestudio.subprocess.Popen') as desktop:
                self.assertTrue(client.launch()['starting']);desktop.assert_not_called()
            exe.unlink()
            with self.assertRaises(RuntimeError):client.launch()


class TransportTests(unittest.TestCase):
    def test_native_job_operations_are_routed_and_cannot_delete_history(self):
        client=VoiceStudio(root=self.workdir.name)
        with patch.object(client,'_ready'),patch.object(client,'_request',return_value=(b'[]','1','application/json')) as request:
            self.assertEqual([group['kind'] for group in client.activities()['groups']],['jobs','batch','longform','resumable','projects'])
            client.job_action({'kind':'batch','action':'retry','id':'job-1'})
            self.assertEqual(request.call_args.args[0],'/batch/jobs/job-1/retry')
            client.job_action({'kind':'jobs','action':'cancel','id':'job-2'})
            self.assertEqual(request.call_args.args[0],'/tasks/cancel/job-2')
        for payload in ({'kind':'batch','action':'delete','id':'job-1'},{'kind':'jobs','action':'cancel','id':'../../settings'}):
            with self.assertRaises(ValueError):client.job_action(payload)
    def test_mcp_activity_protects_idle_stop_and_releases_after_call(self):
        client=VoiceStudio(root=self.workdir.name)
        with client.mcp_activity():
            self.assertTrue(client._busy.locked())
            self.assertTrue(client.stop()['busy'])
        self.assertFalse(client._busy.locked())

    def test_mcp_initialization_waits_for_native_readiness(self):
        client=VoiceStudio(root=self.workdir.name)
        from unittest.mock import MagicMock
        client._web_process=MagicMock();client._web_process.poll.return_value=None
        with patch.object(client,'ensure_web') as activate,patch.object(client,'status',side_effect=[{'connected':False},{'connected':True}]),patch('serve.voicestudio.time.sleep') as sleep:
            client.ensure_mcp_ready()
            activate.assert_called_once();sleep.assert_called_once_with(0.5)

    def test_profile_update_is_partial_and_paths_and_imports_are_bounded(self):
        client=VoiceStudio(root=self.workdir.name)
        with patch.object(client,'_ready'),patch.object(client,'_request',return_value=(b'{"id":"fixture-voice"}','1','application/json')) as request:
            client.profile({'action':'update','id':'fixture-voice','name':'Fixture renamed'})
            self.assertEqual(request.call_args.args[:2],('/profiles/fixture-voice',{'name':'Fixture renamed'}))
            self.assertEqual(request.call_args.kwargs['method'],'PUT')
        for payload in ({'action':'update','id':'../settings','name':'x'},{'action':'import','file_base64':'not base64'},{'action':'create_clone','name':'x','file_base64':''}):
            with self.assertRaises(ValueError):client.profile(payload)

    def test_engine_controls_use_installed_language_and_speed_contracts(self):
        root=Path(self.workdir.name);desktop=root/'VoiceStudio.exe';desktop.write_bytes(b'fixture')
        lang=root/'resources/omnivoice/utils/lang_map.py';lang.parent.mkdir(parents=True);lang.write_text("LANG_NAME_TO_ID = {'english':'en','chinese':'zh','italian':'it'}")
        adapter=root/'resources/backend/engines/audiocpp/__init__.py';adapter.parent.mkdir(parents=True);adapter.write_text('# speed is not supported; ignoring.')
        client=VoiceStudio(root=root,executable=desktop)
        with patch.object(client,'_ready'),patch.object(client,'_request',return_value=(b'{"active":"audiocpp","backends":[{"id":"audiocpp","supported_language_names":["english","chinese"]}]}','1','application/json')):
            result=client.engines()
        self.assertEqual(result['language_catalog']['italian'],'it')
        self.assertIs(result['backends'][0]['speech_controls']['speed_supported'],False)
        self.assertEqual(result['backends'][0]['supported_language_names'],['english','chinese'])
    def test_workspace_reads_original_collections_and_rejects_malformed_records(self):
        client=VoiceStudio(root=self.workdir.name)
        from unittest.mock import patch
        with patch.object(client,'_ready'),patch.object(client,'_request',return_value=(b'[]','1','application/json')) as request:
            self.assertEqual(client.workspace()['profiles'],[])
            self.assertEqual([call.args[0] for call in request.call_args_list],['/profiles','/personalities','/pronunciation'])
        with self.assertRaises(ValueError):client.pronunciation({'action':'add','term':'','replacement':'x'})
        with self.assertRaises(ValueError):client.pronunciation({'action':'delete','id':'../settings'})
        with patch.object(client,'_ready'),patch.object(client,'_request',return_value=(b'{}','1','application/json')):
            with self.assertRaises(RuntimeError):client.workspace()

    def test_dictionary_preserves_native_id_type_and_disabled_state(self):
        client=VoiceStudio(root=self.workdir.name)
        with patch.object(client,'_ready'),patch.object(client,'_request',return_value=(b'{}','1','application/json')) as request:
            client.pronunciation({'action':'update','id':'a1b2c3d4-e5f','term':'Fixture','replacement':'f','type':'ipa','language':'it','enabled':False})
            self.assertEqual(request.call_args.args[0],'/pronunciation/a1b2c3d4-e5f')
            self.assertEqual(request.call_args.kwargs['method'],'PUT')
            self.assertFalse(request.call_args.args[1]['enabled'])
            self.assertEqual(request.call_args.args[1]['type'],'ipa')
            client.pronunciation({'action':'preview','text':'Fixture'})
            self.assertEqual(request.call_args.args[0],'/pronunciation/test')
            client.pronunciation({'action':'delete','id':'a1b2c3d4-e5f'})
            self.assertEqual(request.call_args.kwargs['method'],'DELETE')
            self.assertFalse(client._busy.locked())

    def test_dictionary_import_is_validated_before_any_mutation_and_never_replaces(self):
        client=VoiceStudio(root=self.workdir.name)
        with patch.object(client,'_ready'),patch.object(client,'_request',return_value=(b'{"imported":1}','1','application/json')) as request:
            client.pronunciation({'action':'import','entries':[{'term':'Fixture','replacement':'fixtur','enabled':False}]})
            self.assertEqual(request.call_args.args[0],'/pronunciation/import')
            self.assertIs(request.call_args.args[1]['replace'],False)
            request.reset_mock()
            for payload in ({'action':'import','entries':[{'term':'Fixture'}, {'term':''}]},{'action':'import','entries':[{'term':'Fixture'}],'replace':True}):
                with self.assertRaises(ValueError):client.pronunciation(payload)
            request.assert_not_called()

    def setUp(self):
        self.workdir=tempfile.TemporaryDirectory();self.addCleanup(self.workdir.cleanup)
    def test_voice_inventory_allows_first_engine_import(self):
        client=VoiceStudio(root=self.workdir.name)
        with patch.object(client,'_ready'),patch.object(client,'_request',return_value=(b'{"voices":[]}', '1.2.3','application/json')) as request:
            client.voices()
            self.assertEqual(request.call_args.kwargs['timeout'],30)

    def test_launcher_uses_verified_private_cpu_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            client=VoiceStudio(root=directory,executable=Path('C:/VoiceStudio/VoiceStudio.exe'))
            environment={'OMNIVOICE_BACKEND_CMD':json.dumps(['C:/private/python.exe','-m','uvicorn','main:app']),'OMNIVOICE_TORCH_VARIANT':'cpu'}
            with patch.object(client,'executable',return_value=Path('C:/VoiceStudio/VoiceStudio.exe')),patch.object(client,'web_ui',return_value={'web_ui_available':True}),patch.object(client,'_request',side_effect=RuntimeError('offline')),patch.object(client,'status',return_value={'connected':False}),patch('serve.voicestudio._cpu_backend_environment',return_value=environment),patch('serve.voicestudio.subprocess.Popen') as start,patch('psutil.Process') as process:
                start.return_value.pid=12345;process.return_value.create_time.return_value=1.0
                self.assertTrue(client.launch()['starting'])
            self.assertEqual(start.call_args.args[0][0],str(Path('C:/private/python.exe')))
            self.assertTrue(start.call_args.args[0][1].endswith('voicestudio_original_web_host.py'))
            self.assertEqual(start.call_args.kwargs['env']['OMNIVOICE_TORCH_VARIANT'],'cpu')


    def response(self, data, marker='1.2.3', content_type='application/json', status=200):
        from unittest.mock import MagicMock
        result = MagicMock()
        result.status = status
        result.headers = {'x-omnivoice-backend': marker, 'Content-Type': content_type}
        result.read.return_value = data
        result.__enter__.return_value = result
        return result

    def test_health_identity_and_error_handling(self):
        client = VoiceStudio(root=self.workdir.name)
        with patch.object(client._opener, 'open', return_value=self.response(b'{"status":"ok","version":"1.2.3","device":"cpu"}')):
            self.assertTrue(client.status()['connected'])
            self.assertEqual(client.status()['device'], 'cpu')
        with patch.object(client._opener, 'open', return_value=self.response(b'{"status":"ok"}', marker='')):
            self.assertFalse(client.status()['connected'])
            with self.assertRaises(RuntimeError): client.speech({'input': 'private'})
        with patch.object(client._opener, 'open', return_value=self.response(b'not json')):
            self.assertFalse(client.status()['connected'])

    def test_speech_contract_wav_and_busy_release(self):
        client = VoiceStudio(root=self.workdir.name)
        wav = b'RIFF\x04\x00\x00\x00WAVEfixture'
        health = self.response(b'{"status":"ok"}')
        with patch.object(client._opener, 'open', side_effect=[health, self.response(b'{"tts":{"active":"audiocpp","backends":[]}}'), self.response(wav, content_type='audio/wav')]) as request:
            result = client.speech({'input': 'Hello', 'voice': 'profile-id', 'language': 'it'})
            self.assertEqual(base64.b64decode(result['audio_base64']), wav)
            body = json.loads(request.call_args.args[0].data)
            self.assertEqual(body, {'model':'tts-1', 'input':'Hello', 'voice':'profile-id', 'language':'it', 'response_format':'wav'})
        with patch.object(client._opener, 'open', side_effect=[health, self.response(b'{"tts":{}}'), self.response(b'wrong', content_type='audio/wav')]):
            with self.assertRaises(RuntimeError): client.speech({'input': 'Hello'})
        self.assertFalse(client._busy.locked())

    def test_redirects_limits_and_local_boundaries(self):
        from serve.voicestudio import _NoRedirect
        with self.assertRaises(RuntimeError): _NoRedirect().redirect_request(None,None,302,None,None,'https://example.com')
        client = VoiceStudio(root=self.workdir.name)
        with patch.object(client._opener, 'open', return_value=self.response(b'x'*21)):
            with self.assertRaises(RuntimeError): client._request('/health', limit=20)
        for url in ('https://example.com', 'http://localhost:3900', 'http://127.0.0.1:3900/path', 'http://user@127.0.0.1:3900'):
            with self.assertRaises(ValueError): VoiceStudio(base_url=url)
        for payload in ({'input': ''}, {'input': 'x'*4097}, {'input': ['wrong type']}):
            with self.assertRaises(ValueError): client.speech(payload)

    def test_launch_activates_internal_services_without_desktop_window(self):
        client=VoiceStudio(root=self.workdir.name)
        with patch.object(client,'ensure_web',return_value={'ok':True,'starting':True}) as activate,patch('serve.voicestudio.subprocess.Popen') as desktop:
            self.assertTrue(client.launch()['starting'])
        activate.assert_called_once_with();desktop.assert_not_called()

    def test_engine_selection_preserves_other_families_and_enforces_availability(self):
        client=VoiceStudio(root=self.workdir.name);inventory={'active':'old','backends':[{'id':'cpu','available':True,'routing_status':'cpu_only'},{'id':'gpu','available':True,'routing_status':'unavailable'},{'id':'licensed','available':True,'license_required':True,'license_accepted':False}]}
        with patch.object(client,'engines',return_value=inventory),patch.object(client,'_request',return_value=(b'{"active":"cpu"}','version','application/json')) as request,patch.object(client,'status',return_value={}):
            client.select_engine({'backend_id':'cpu'});self.assertEqual(request.call_args.args[:2],('/engines/select',{'family':'tts','backend_id':'cpu'}))
            for identity in ('missing','gpu','licensed'):
                with self.assertRaises(ValueError):client.select_engine({'backend_id':identity})



if __name__ == '__main__': unittest.main()

