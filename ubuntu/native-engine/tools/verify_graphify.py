"""Exercise the installed Graphify MCP locally and retain installation evidence."""
import asyncio
import json
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

root = Path(__file__).resolve().parent.parent

async def main():
    params = StdioServerParameters(command=sys.executable,
        args=['-m', 'graphify.serve', '--graph', str(root/'graphify-out/graph.json')],
        env={'GRAPHIFY_QUERY_LOG_DISABLE':'1'})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            query = next(tool for tool in listing.tools if tool.name == 'query_graph')
            schema = query.model_dump(by_alias=True).get('inputSchema', {})
            properties = schema.get('properties', {})
            arguments = {'question':'OptionalBackends benchmark'}
            if 'budget' in properties:
                arguments['budget'] = 600
            result = await session.call_tool(query.name, arguments)
            if result.model_dump(by_alias=True).get('isError') or not result.content:
                raise RuntimeError('Graph query failed')
            graph = json.loads((root/'graphify-out/graph.json').read_text(encoding='utf-8'))
            report = {'version':'0.9.85','mcp_connected':True,
                'tools':[tool.name for tool in listing.tools],
                'nodes':len(graph['nodes']),'edges':len(graph.get('links', graph.get('edges',[]))),
                'query_verified':True,'local_code_only':True,'measured_token_savings':None}
            (root/'output/verification/graphify-install.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report))

if __name__ == '__main__':
    asyncio.run(main())
