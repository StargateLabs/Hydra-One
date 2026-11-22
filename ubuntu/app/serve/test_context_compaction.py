import unittest
from serve.context_compaction import prepare

class CompactionTests(unittest.TestCase):
    def test_preserves_system_recent_turns_and_complete_tool_exchange(self):
        rows=[{'role':'system','content':'immutable system'}]
        for i in range(8):
            rows += [{'role':'user','content':str(i)+'u'*2000},{'role':'assistant','content':str(i)+'a'*2000}]
            if i==1:
                rows[-1]['tool_calls']=[{'id':'t','function':{'name':'read','arguments':'{}'}}]
                rows += [{'role':'tool','tool_call_id':'t','content':'exact tool result'}]
        snapshot=repr(rows)
        result=prepare({'messages':rows})
        self.assertEqual(repr(rows),snapshot)
        self.assertGreater(result['before_characters'],result['after_characters'])
        self.assertTrue(result['changes'])
        protected={0,3,4,5,*range(10,len(rows))}
        self.assertFalse(protected.intersection(c['index'] for c in result['changes']))
        for c in result['changes']:
            self.assertIn('middle omitted',c['replacement']['content'])
            self.assertEqual(c['original'],rows[c['index']])

    def test_short_and_multimodal_context_no_change(self):
        rows=[{'role':'user','content':[{'type':'text','text':'x'*2000}]}]
        self.assertEqual(prepare({'messages':rows})['changes'],[])

    def test_rejects_unbounded_invalid_payloads(self):
        for payload in ({'messages':[]},{'messages':[{'role':'unknown'}]}, {'messages':[{'role':'user','content':'ok'}],'keep_recent_turns':True}):
            with self.assertRaises(ValueError):prepare(payload)
