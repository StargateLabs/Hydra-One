"""Keep the project-local proxy available while official Headroom MCP runs.

No provider changes, installs, external endpoints or stdout diagnostics.
"""
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))


def launch(root=ROOT,*,ensure=None,spawn=subprocess.Popen,is_enabled=None):
    from serve.headroom_integration import ensure_proxy,enabled,mcp_config
    is_enabled=is_enabled or enabled
    root=Path(root).resolve();spec=mcp_config(root)
    if ensure is None:
        ensure=lambda r,u:ensure_proxy(r,u,port=18199,workspace=r/'data/headroom/codex-proxy')
    spec['args']=['mcp','serve','--proxy-url','http://127.0.0.1:18199']
    spec['env'].update(HEADROOM_WORKSPACE_DIR=str(root/'data/headroom/codex-mcp'),
        HEADROOM_CONFIG_DIR=str(root/'data/headroom/codex-mcp/config'))
    def recover():
        if ensure(root,'http://127.0.0.1:8090')!='http://127.0.0.1:18199':
            raise RuntimeError('Headroom proxy endpoint not verified')
    active=is_enabled(root)
    if active:recover()
    args=spec['args'] if active else ['mcp','serve']
    child=spawn([spec['command'],*args],cwd=root,env={**os.environ,**spec['env']})
    interval=5
    try:
        while True:
            try:return child.wait(timeout=interval)
            except subprocess.TimeoutExpired:
                if not is_enabled(root):continue
                try:
                    recover();interval=5
                except Exception as exc:
                    print('Headroom proxy recovery failed: '+type(exc).__name__,file=sys.stderr,flush=True)
                    interval=min(interval*2,60)
    except BaseException:
        child.terminate()
        try:child.wait(timeout=3)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
        raise


if __name__=='__main__':
    raise SystemExit(launch())
