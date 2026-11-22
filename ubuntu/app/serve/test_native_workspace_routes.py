import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from serve.native_workspace_routes import get,post

class NativeRouteTests(unittest.TestCase):
    def handler(self,payload=b'{"kind":"claude"}'):
        h=Mock();h.headers={'Content-Length':str(len(payload))};h._read_body.return_value=payload;h._own_page.return_value=True;h._authorized.return_value=True;return h
    def test_native_open_requires_own_page(self):
        h=self.handler();h._own_page.return_value=False;service=SimpleNamespace(native_workspace=Mock())
        self.assertTrue(post(h,service,'/native-workspace/open'));service.native_workspace.open.assert_not_called()
    def test_only_known_apps_open(self):
        h=self.handler(b'{"kind":"other"}');service=SimpleNamespace(native_workspace=Mock())
        post(h,service,'/native-workspace/open');service.native_workspace.open.assert_not_called();self.assertEqual(h._json.call_args.args[0],400)
    def test_rejected_desktop_wrapper_cannot_be_reopened(self):
        h=self.handler();service=SimpleNamespace(native_workspace=Mock())
        post(h,service,'/native-workspace/open');service.native_workspace.open.assert_not_called();self.assertEqual(h._json.call_args.args[0],410)
    def test_stop_is_graceful_and_unrelated_routes_are_preserved(self):
        h=self.handler();service=SimpleNamespace(native_workspace=Mock())
        post(h,service,'/native-workspace/stop');service.native_workspace.stop_app.assert_called_once_with('claude')
        self.assertFalse(get(h,service,'/metrics'));self.assertFalse(post(h,service,'/v1/chat/completions'))
    def test_status_is_authenticated(self):
        h=self.handler();h._authorized.return_value=False;service=SimpleNamespace(native_workspace=Mock())
        get(h,service,'/native-workspace');service.native_workspace.status.assert_not_called()

if __name__=='__main__':unittest.main()
