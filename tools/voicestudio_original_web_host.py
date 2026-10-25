"""Serve unchanged original VoiceStudio app with its renderer's /api web prefix."""
import argparse
from pathlib import Path
import sys
from contextlib import asynccontextmanager

def create_web_app(app):
    from starlette.applications import Starlette
    from starlette.routing import Mount, Match
    web=Starlette(routes=[Mount('/api',app=app),Mount('/',app=app)])
    @asynccontextmanager
    async def lifespan(_):
        async with app.router.lifespan_context(app):
            yield
    web.router.lifespan_context=lifespan
    async def dispatch(scope, receive, send):
        # Preserve native /api routes before applying the renderer's alias.
        if scope['type'] in ('http', 'websocket') and any(
            getattr(route, 'path', '').startswith('/api/') and
            route.matches(scope)[0] != Match.NONE for route in app.routes
        ):
            await app(scope, receive, send)
        else:
            await web(scope, receive, send)
    return dispatch

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',required=True)
    args=parser.parse_args()
    backend=Path(args.backend).resolve()
    sys.path.insert(0,str(backend))
    import main as original
    import uvicorn
    # Both mounts reference the exact same original app and engine registry.
    # The official desktop renderer uses /api in browser mode. Existing clients
    # continue to use the original root paths; WebSockets share the same mapping.
    web=create_web_app(original.app)
    uvicorn.run(web,host='127.0.0.1',port=3900,log_level='info')

if __name__=='__main__':main()
