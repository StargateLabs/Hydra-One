import unittest,tempfile,json
from pathlib import Path
from serve.optional_reports import best_groups

class OptionalReportTests(unittest.TestCase):
    def test_streaming_colibri_report_preserves_first_token_and_identity(self):
        from serve.optional_reports import reports
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/'data/benchmark-checks';folder.mkdir(parents=True)
            rows=[dict(warmup=i==0,output_tokens=32,wall_s=.8,ttft_s=.15) for i in range(4)]
            report=dict(status='complete',id='colibri',backend='API locale',started_at=1,protocol=dict(runs=3,warmup=1,tokens=32,output_policy='actual_output'),runs=[dict(arm='manual',profile='balanced',public_model='local/qwen3.6-colibri',rows=rows)])
            (folder/'report.json').write_text(json.dumps(report),encoding='utf-8')
            result=reports(directory)[0]
            self.assertEqual(result['backend'],'Colibri');self.assertEqual(result['summary']['ttft_s']['median'],.15)
            self.assertEqual(result['summary']['wall_tok_s']['median'],40);self.assertNotIn('decode_tok_s',result['summary'])
    def row(self):
        return dict(model='local/colibri',source='proof.json',label='Colibri',started_at='2026-10-15T08:00:00+00:00',protocol={'full_budget':True,'runs':3,'tokens':32},summary={'wall_tok_s':{'median':40},'wall_s':{'median':.8}})

    def test_wall_only_engine_has_honest_record(self):
        result=best_groups([self.row()],'local/colibri')
        self.assertEqual(result[0]['winner']['ranking_metric'],'wall_tok_s')
        self.assertNotIn('decode_tok_s',result[0]['winner']['summary'])

    def test_incomplete_budget_or_other_model_cannot_win(self):
        row=self.row();row['protocol']['full_budget']=False
        self.assertEqual(best_groups([row],'local/colibri'),[])
        self.assertEqual(best_groups([self.row()],'another-model'),[])
