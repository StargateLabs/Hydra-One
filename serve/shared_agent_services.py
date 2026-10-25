"""Activate verified shared MCP candidates without touching profiles or graph data."""
import json
from pathlib import Path
from serve.configuration import atomic_json
from serve.harness_updates import selected
from serve.trueforge_setup import _BROWSER_LOCK,_MEMORY_LOCK

def activate_shared_service(svc,kind,rollback=False):
 lock=_BROWSER_LOCK if kind=='browser' else _MEMORY_LOCK
 if not lock.acquire(False):raise ValueError('Il servizio condiviso sta eseguendo una richiesta')
 updater=svc.update_center.harness_updates;root=updater.root;path=root/'data/mcp-dashboard.json';data=json.loads(path.read_text(encoding='utf-8'));original=dict(data['mcpServers'][kind]);manager=svc.mcp.servers[kind]
 try:
  updater.activate(kind,rollback=rollback);active=selected(root,kind)
  binary=active['binary'] if active else str(root/'output/tools'/('agent-browser' if kind=='browser' else 'agent-memory')/'node_modules'/('@playwright/mcp/cli.js' if kind=='browser' else '@modelcontextprotocol/server-memory/dist/index.js'))
  configuration={**original,'args':[binary,*original.get('args',[])[1:]]}
  manager.close()
  from serve.mcp import McpServer
  replacement=McpServer(kind,configuration,svc.mcp.settings)
  if not replacement.start():
   updater.activate(kind,rollback=True);restored=McpServer(kind,original,svc.mcp.settings);restored.start();svc.mcp.servers[kind]=restored;raise ValueError('Nuovo servizio non disponibile; versione precedente ripristinata')
  data['mcpServers'][kind]=configuration;atomic_json(path,data);svc.mcp.servers[kind]=replacement
 finally:lock.release()
