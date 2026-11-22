"""Verify the existing authenticated local bridge; never disclose its credential."""
import argparse,json,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

def rpc(method,params=None):
    token=(ROOT/'data/agent-harness/trueforge-mcp-token').read_text(encoding='utf-8').strip()
    data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}).encode()
    request=urllib.request.Request('http://127.0.0.1:8090/harness/mcp',data=data,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(request,timeout=45) as response:return json.load(response)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--inventory',action='store_true');parser.add_argument('--core',action='store_true');parser.add_argument('--boundaries',action='store_true');parser.add_argument('--only');parser.add_argument('--call');parser.add_argument('--arguments',default='{}');args=parser.parse_args()
    destination=ROOT/'output/verification';destination.mkdir(exist_ok=True)
    if args.inventory:
        initialized=rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'Strata integration audit','version':'1'}})
        response=rpc('tools/list');tools=response.get('result',{}).get('tools',[])
        (destination/'mcp-bridge-live-inventory.json').write_text(json.dumps({'initialize':initialized,'tools':tools},ensure_ascii=False,indent=2),encoding='utf-8')
        groups={}
        for tool in tools:groups.setdefault(tool['name'].split('__')[0],[]).append(tool['name'])
        print(json.dumps({'counts':{name:len(items) for name,items in groups.items()},'voice_tools':groups.get('voicestudio',[])},ensure_ascii=False))
    elif args.boundaries:
        cases=[('strata_diagnostics__read_harness_conversation',{}),('filesystem__get_file_info',{'path':'C:/Windows'}),('memory__search_nodes',{'query':3}),('sequential-thinking__sequentialthinking',{}),('context7__resolve-library-id',{}),('deepwiki__read_wiki_structure',{}),('graphify__graph_stats',{'project_path':3}),('time__get_current_time',{'timezone':'Strata/InvalidTimezone'}),('browser__browser_tabs',{'action':'invalid'}),('context-mode__ctx_search',{'queries':3}),('headroom__headroom_compress',{}),('voicestudio__transcribe',{})]
        proof=[]
        for name,arguments in cases:
            if args.only and name!=args.only:continue
            response=rpc('tools/call',{'name':name,'arguments':arguments})
            (destination/('mcp-bridge-invalid-'+name+'.json')).write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf-8')
            result=response.get('result',{});row={'tool':name,'rpc_error':response.get('error'),'isError':result.get('isError',False),'correctly_marked_error':bool(response.get('error') or result.get('isError'))};proof.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        target=destination/'mcp-bridge-boundaries-real.json'
        if args.only and target.is_file():
            previous=json.loads(target.read_text(encoding='utf-8'));proof=[row for row in previous if row['tool']!=args.only]+proof
        target.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    elif args.core:
        calls=[('strata_diagnostics__read_prepared_models',{}),('filesystem__list_allowed_directories',{}),('memory__search_nodes',{'query':'strata integration audit read-only'}),('sequential-thinking__sequentialthinking',{'thought':'Verifica del collegamento MCP locale; nessuna modifica ai file.','nextThoughtNeeded':False,'thoughtNumber':1,'totalThoughts':1}),('context7__resolve-library-id',{'libraryName':'transformers','query':'MusicGen audio prompt conditioning documentation'}),('deepwiki__read_wiki_structure',{'repoName':'ggml-org/whisper.cpp'}),('graphify__graph_stats',{}),('time__get_current_time',{'timezone':'Europe/Rome'}),('browser__browser_tabs',{'action':'list'}),('context-mode__ctx_stats',{}),('headroom__headroom_stats',{})]
        inventory=json.loads((destination/'mcp-bridge-live-inventory.json').read_text(encoding='utf-8'))['tools'];names={row['name'] for row in inventory};proof=[]
        for name,arguments in calls:
            if name not in names:raise ValueError('Tool absent from live inventory: '+name)
            try:response=rpc('tools/call',{'name':name,'arguments':arguments})
            except Exception as error:response={'transport_error':str(error)}
            (destination/('mcp-bridge-call-'+name+'.json')).write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf-8')
            result=response.get('result',{});row={'tool':name,'rpc_error':response.get('error'),'transport_error':response.get('transport_error'),'isError':result.get('isError',False),'content_types':[item.get('type') for item in result.get('content',[])]};proof.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        (destination/'mcp-bridge-core-real.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    elif args.call:
        tools=json.loads((destination/'mcp-bridge-live-inventory.json').read_text(encoding='utf-8'))['tools']
        if not any(row['name']==args.call for row in tools):raise ValueError('Tool must come from the current live inventory')
        response=rpc('tools/call',{'name':args.call,'arguments':json.loads(args.arguments)})
        target=destination/('mcp-bridge-call-'+args.call+'.json');target.write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf-8')
        result=response.get('result',{})
        print(json.dumps({'tool':args.call,'rpc_error':response.get('error'),'isError':result.get('isError',False),'content_types':[row.get('type') for row in result.get('content',[])],'proof':target.name},ensure_ascii=False))

if __name__=='__main__':main()
