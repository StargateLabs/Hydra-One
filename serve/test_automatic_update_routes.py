import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from serve.automatic_update_routes import post
class AutomaticUpdateRoutesTests(unittest.TestCase):
    def handler(self,body=b'{}'):
        handler=Mock();handler.headers={'Content-Length':str(len(body))};handler._read_body.return_value=body;handler._own_page.return_value=True;return handler
    def service(self):return SimpleNamespace(update_center=Mock(),automatic_updates=Mock(),automatic_restart=Mock())
    def test_restart_requires_own_page(self):
        service=self.service();handler=self.handler();handler._own_page.return_value=False
        post(handler,service,'/updates/restart');service.automatic_restart.assert_not_called()
    def test_busy_update_prevents_restart(self):
        service=self.service();service.update_center.operational_idle.return_value=False;handler=self.handler()
        post(handler,service,'/updates/restart');service.automatic_restart.assert_not_called();self.assertEqual(handler._json.call_args.args[0],400)
    def test_idle_post_restarts_once(self):
        service=self.service();handler=self.handler()
        post(handler,service,'/updates/restart');service.automatic_restart.assert_called_once();self.assertEqual(handler._json.call_args.args[0],202)
    def test_string_false_cannot_enable_updates(self):
        service=self.service();handler=self.handler(b'{"enabled":"false"}')
        post(handler,service,'/updates/automatic/configure');service.automatic_updates.configure.assert_not_called();self.assertEqual(handler._json.call_args.args[0],400)
if __name__=='__main__':unittest.main()
