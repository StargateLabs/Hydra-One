import unittest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from tools.voicestudio_original_web_host import create_web_app


class WebRoutesTests(unittest.TestCase):
    def test_native_api_and_browser_alias_share_original_routes(self):
        async def answer(request):
            from starlette._utils import get_route_path
            return JSONResponse({'path': get_route_path(request.scope)})
        original = Starlette(routes=[Route('/health', answer),
                                     Route('/api/settings/performance-profile', answer)])
        with TestClient(create_web_app(original)) as client:
            for path in ('/health', '/api/health', '/api/settings/performance-profile'):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
            self.assertEqual(client.get('/api/health').json()['path'], '/health')


if __name__ == '__main__':
    unittest.main()
