import json
import threading
import unittest
from types import SimpleNamespace

from serve.optional_tools import compact_result, chat_with_tools


def tools(count=20):
    return [{'name': f'server__tool{i}', 'description': f'tool {i}', 'parameters': {'type': 'object', 'properties': {'x': {'type': 'string'}}}} for i in range(count)]


class CompactTests(unittest.TestCase):
    def test_many_tools_send_three_compact_schemas(self):
        seen = []
        class Manager:
            def chat(self, payload, cancel):
                seen.extend(tool['function']['name'] for tool in payload['tools'])
                yield dict(id='x', created=1, model='local/test',
                           choices=[{'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}],
                           usage={'completion_tokens': 1})
        hub = SimpleNamespace(settings={'max_rounds': 2}, template_tools=tools)
        list(chat_with_tools(Manager(), hub, {'messages': [{'role': 'user', 'content': 'hi'}]}, threading.Event()))
        self.assertEqual(seen, ['strata_mcp_search', 'strata_mcp_describe', 'strata_mcp_call'])

    def test_small_selection_stays_direct(self):
        seen = []
        class Manager:
            def chat(self, payload, cancel):
                seen.extend(tool['function']['name'] for tool in payload['tools'])
                yield dict(id='x', created=1, model='local/test',
                           choices=[{'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}],
                           usage={'completion_tokens': 1})
        hub = SimpleNamespace(settings={'max_rounds': 2}, template_tools=lambda: tools(5))
        list(chat_with_tools(Manager(), hub, {'messages': [{'role': 'user', 'content': 'hi'}]}, threading.Event()))
        self.assertEqual(seen, [f'server__tool{i}' for i in range(5)])

    def test_search_describe_call_and_allowlist(self):
        calls = []
        hub = SimpleNamespace(call=lambda name, arguments, cancel: (calls.append((name, arguments)) or
                                                                     {'ok': True, 'text': 'result', 'chars': 6,
                                                                      'truncated': False, 'ms': 1}))
        available = tools(20)
        search = compact_result('strata_mcp_search', {'query': 'tool1'}, available, hub, threading.Event())
        found = json.loads(search['text'])['tools']
        self.assertEqual(found[0]['name'], 'server__tool1')
        described = compact_result('strata_mcp_describe', {'name': 'server__tool1'}, available, hub, threading.Event())
        self.assertEqual(json.loads(described['text'])['parameters']['properties']['x']['type'], 'string')
        called = compact_result('strata_mcp_call', {'name': 'server__tool1', 'arguments': {'x': '1'}},
                                available, hub, threading.Event())
        self.assertTrue(called['ok'])
        self.assertEqual(calls, [('server__tool1', {'x': '1'})])
        blocked = compact_result('strata_mcp_call', {'name': 'server__tool99', 'arguments': {}},
                                 available, hub, threading.Event())
        self.assertFalse(blocked['ok'])

    def test_compact_loop_runs_local_tools_then_final_answer(self):
        replies = [
            {'message': {'role': 'assistant', 'content': None,
                         'tool_calls': [{'id': 's', 'type': 'function', 'function': {'name': 'strata_mcp_search', 'arguments': '{"query":"tool1"}'}}]},
             'finish_reason': 'tool_calls'},
            {'message': {'role': 'assistant', 'content': None,
                         'tool_calls': [{'id': 'c', 'type': 'function', 'function': {'name': 'strata_mcp_call', 'arguments': '{"name":"server__tool1","arguments":{"x":"1"}}'}}]},
             'finish_reason': 'tool_calls'},
            {'message': {'role': 'assistant', 'content': 'final'}, 'finish_reason': 'stop'},
        ]
        calls = []
        class Manager:
            def chat(self, payload, cancel):
                choice = replies.pop(0)
                yield dict(id='x', created=1, model='local/test', choices=[choice],
                           usage={'completion_tokens': 1})
        hub = SimpleNamespace(settings={'max_rounds': 4}, template_tools=tools,
                              call=lambda name, arguments, cancel: (calls.append((name, arguments)) or
                                                                     {'ok': True, 'text': 'tool result', 'chars': 11,
                                                                      'truncated': False, 'ms': 1}))
        events = list(chat_with_tools(Manager(), hub, {'messages': [{'role': 'user', 'content': 'hi'}]}, threading.Event()))
        self.assertEqual(calls, [('server__tool1', {'x': '1'})])
        self.assertTrue(any(event.get('choices', [{}])[0].get('delta', {}).get('content') == 'final' for event in events))


if __name__ == '__main__':
    unittest.main()
