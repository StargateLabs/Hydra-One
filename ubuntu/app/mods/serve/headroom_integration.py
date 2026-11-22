"""Project-scoped official Headroom runtime metadata and MCP launch contract."""
import json
import threading
from pathlib import Path

_proxy_lock = threading.Lock()


def enabled(root):
    """A malformed or explicitly disabled marker must never enable routing."""
    try:
        config=json.loads((Path(root)/'data/headroom/enabled.json').read_text(encoding='utf-8'))
        return isinstance(config,dict) and config.get('enabled') is True
    except (OSError,ValueError):
        return False


def mcp_config(root):
    root=Path(root).resolve()
    return dict(command=str(root/'output/tools/headroom-runtime/Scripts/headroom.exe'),
                args=['mcp','serve','--proxy-url','http://127.0.0.1:18198'],
                env={'HEADROOM_WORKSPACE_DIR':str(root/'data/headroom'),
                     'HEADROOM_CONFIG_DIR':str(root/'data/headroom/config'),
                     'HEADROOM_TELEMETRY':'off','HEADROOM_BEACON':'off',
                     'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})


def status(root):
    root=Path(root);manifest=root/'output/tools/headroom-runtime/INSTALL.json'
    try:metadata=json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError,ValueError):metadata={}
    proof=root/'output/verification/headroom-mcp-proof.json'
    try:verification=json.loads(proof.read_text(encoding='utf-8'))
    except (OSError,ValueError):verification={}
    return dict(installed=Path(mcp_config(root)['command']).is_file(),
                version=metadata.get('version'),repository='headroomlabs-ai/headroom',
                scope='project_isolated_runtime',automatic_traffic_compression=enabled(root),
                mcp_verified=verification.get('original_retrieved_exactly') is True,
                fixture_tokens_saved=verification.get('compression',{}).get('tokens_saved'),
                compression_scope='local_harness_requests_and_on_demand_mcp_tools' if enabled(root) else 'on_demand_mcp_tools',torch_modified=False)


def ensure_proxy(root, upstream, *, port=18198, workspace=None):
    """Start the project proxy only when explicitly enabled, bound to loopback."""
    with _proxy_lock:
        return _ensure_proxy(root, upstream,port=port,workspace=workspace)


def _ensure_proxy(root, upstream, *, port=18198, workspace=None):
    import os, subprocess, urllib.request
    from urllib.parse import urlsplit
    root=Path(root).resolve()
    if type(port) is not int or port not in (18198,18199):raise ValueError('Unknown Headroom proxy port')
    workspace=(root/'data/headroom') if workspace is None else Path(workspace).resolve()
    if not workspace.is_relative_to(root/'data/headroom'):raise ValueError('Headroom state must stay project-local')
    if not enabled(root): return upstream
    target=urlsplit(upstream)
    if (target.scheme != 'http' or target.hostname not in ('127.0.0.1','localhost') or target.port != 8090
            or target.username or target.password or target.path or target.query or target.fragment):
        return upstream
    base='http://127.0.0.1:'+str(port)
    try:
        with urllib.request.urlopen(base+'/livez',timeout=2) as response:
            health=json.load(response)
        if not isinstance(health,dict) or health.get('service') != 'headroom-proxy':
            raise RuntimeError('Porta Headroom occupata da un altro servizio')
        if health.get('status') != 'healthy' or health.get('alive') is not True:
            raise RuntimeError('Il proxy Headroom non è pronto')
        return base
    except urllib.error.URLError:
        pass
    env=os.environ.copy();env.update(mcp_config(root)['env'])
    env.update(HEADROOM_WORKSPACE_DIR=str(workspace),HEADROOM_CONFIG_DIR=str(workspace/'config'))
    log=root/('output/verification/headroom-active.log' if port==18198 else 'output/verification/headroom-codex-proxy.log');log.parent.mkdir(parents=True,exist_ok=True)
    command=[mcp_config(root)['command'],'proxy','--host','127.0.0.1','--port',str(port),
             '--anthropic-api-url',upstream,'--openai-api-url',upstream,
             '--disable-kompress','--disable-kompress-fallback','--no-telemetry',
             '--no-learn','--no-memory-tools','--no-memory-context']
    with log.open('ab') as stream:
        child=subprocess.Popen(command,cwd=root,env=env,stdin=subprocess.DEVNULL,
                         stdout=stream,stderr=stream,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    import time
    for _ in range(40):
        if child.poll() is not None:
            raise RuntimeError('Avvio Headroom fallito: controllare il registro locale')
        time.sleep(.25)
        try:
            with urllib.request.urlopen(base+'/livez',timeout=1) as response:
                health=json.load(response)
            if isinstance(health,dict) and health.get('service')=='headroom-proxy' and health.get('status')=='healthy' and health.get('alive') is True: return base
        except (OSError,ValueError): pass
    child.terminate()
    try:child.wait(timeout=3)
    except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
    raise RuntimeError('Headroom non disponibile: controllare il registro locale')
