"""Startup failures must return a useful HTTP error instead of dropping the socket."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from serve.frontend import ChatTemplate
from serve.server import ByteTokenizer,EngineDied,MockEngine,Service,serve

class StartupHTTP(unittest.TestCase):
    def test_failed_start_returns_json_and_a_later_request_recovers(self):
        tok=ByteTokenizer()
        service=Service(MockEngine(tok,'</think>hello',max_context=4096),tok,
            ChatTemplate(Path(__file__).parent/'chat_template.jinja'))
        server=serve(service,port=0)
        try:
            request=Request(f'http://127.0.0.1:{server.server_address[1]}/v1/chat/completions',
                data=json.dumps(dict(model=service.model,messages=[dict(role='user',content='Hi')],max_tokens=32,stream=False)).encode(),headers={'Content-Type':'application/json'})
            with patch.object(service,'load',side_effect=EngineDied('Engine exited before READY: invalid pack settings')):
                with self.assertRaises(HTTPError) as caught:urlopen(request,timeout=5)
                self.assertEqual(caught.exception.code,503)
                error=json.load(caught.exception)['error']['message']
                self.assertIn('invalid pack settings',error)
            with urlopen(request,timeout=5) as response:
                self.assertTrue(json.load(response)['choices'][0]['message']['content'])
        finally:
            server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
