import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from serve.generation_routes import get,post

class RoutesTests(unittest.TestCase):
    def test_idle_models_are_released_before_media_start(self):
        from serve.generation_routes import prepare_idle_media
        audio=Mock();audio.status.return_value={'status':'ready','busy':False};audio.request_lock.acquire.return_value=True
        speech=Mock();speech.status.return_value={'status':'idle','busy':False}
        optional=Mock();optional.status.return_value={'status':'idle','busy':False}
        service=SimpleNamespace(local_audio=audio,local_speech=speech,optional_backends=optional,unload=Mock(return_value='unloaded'))
        prepare_idle_media(service);audio.stop.assert_called_once();service.unload.assert_called_once();audio.request_lock.release.assert_called_once()
    def test_running_audio_is_preserved_before_media_start(self):
        from serve.generation_routes import prepare_idle_media
        audio=Mock();audio.status.return_value={'status':'ready','busy':True}
        service=SimpleNamespace(local_audio=audio)
        with self.assertRaises(ValueError):prepare_idle_media(service)
        audio.stop.assert_not_called()
    def test_status_requires_key_before_touching_managers(self):
        h=Mock();h._authorized.return_value=False
        self.assertTrue(get(h,SimpleNamespace(),'/local-visual'))
        h._json.assert_not_called()
    def test_start_is_refused_while_operation_active(self):
        h=Mock();h._own_page.return_value=True;h.headers={'Content-Length':'2'};h._read_body.return_value=b'{}'
        manager=Mock();service=SimpleNamespace(optional_backends=SimpleNamespace(root='fixture'),update_center=SimpleNamespace(operational_idle=lambda:False),local_visual=manager)
        self.assertTrue(post(h,service,'/local-visual/start'));manager.start.assert_not_called();self.assertEqual(h._json.call_args.args[0],400)
    def test_unrelated_routes_are_preserved(self):
        self.assertFalse(get(Mock(),SimpleNamespace(),'/metrics'));self.assertFalse(post(Mock(),SimpleNamespace(),'/v1/chat/completions'))
    def test_invalid_request_size_is_rejected(self):
        h=Mock();h._own_page.return_value=True;h.headers={'Content-Length':'16385'}
        self.assertTrue(post(h,SimpleNamespace(),'/local-generative-audio/start'));h._read_body.assert_not_called();self.assertEqual(h._json.call_args.args[0],400)

if __name__=='__main__':unittest.main()
