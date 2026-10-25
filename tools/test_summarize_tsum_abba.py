"""Exercise publication rejection for incomplete and confounded experiments."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import summarize_tsum_abba as module

class SummaryChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=module.ROOT/'output/verification')
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        (self.root/'data/benchmarks').mkdir(parents=True)
        (self.root/'output/verification').mkdir(parents=True)
        self.reports = []
        for index, name in enumerate(module.NAMES):
            rows = [dict(warmup=i<5,output_tokens=256,reused=0,prompt_sha256=str(i),
                decode_tok_s=50.,prefill_tok_s=180.,wall_s=10.,wall_tok_s=25.6) for i in range(10)]
            report = dict(status='complete',rows=rows,engine=dict(vram_free_mib=2400,expert_slots=8706,model='iq3_xxs'),
                protocol=dict(tokens=256,warmup=5,runs=5),binary_sha256='a'*64)
            self.reports.append(report)
            config = dict(args=['--expert-cache','6500'],env=dict(STRATA_TSUM='1' if index in (1,2) else '0',OTHER='constant'))
            (self.root/f'output/verification/test-iq3-memory-{name}.json').write_text(json.dumps(config))
        self.write()

    def write(self):
        for name, report in zip(module.NAMES,self.reports):
            (self.root/f'data/benchmarks/test-iq3-memory-{name}.json').write_text(json.dumps(report))

    def run_summary(self):
        with patch.object(module,'ROOT',self.root),patch('builtins.print'):
            return module.summarize('test')

    def test_valid_complete_campaign(self):
        self.assertEqual(self.run_summary()['pooled']['decode_tok_s']['change_percent'],0)

    def test_refuses_invalid_campaigns(self):
        original = copy.deepcopy(self.reports)
        mutations = [lambda r:r.update(status='running'),
            lambda r:r['rows'].pop(),
            lambda r:r['engine'].update(vram_free_mib=37),
            lambda r:r.update(binary_sha256='b'*64),
            lambda r:r['engine'].update(expert_slots=10110),
            lambda r:r['rows'][5].update(prompt_sha256='different'),
            lambda r:r['rows'][0].update(prompt_sha256='different-warmup'),
            lambda r:r['rows'][0].update(warmup=False),
            lambda r:r['rows'][5].update(decode_tok_s=float('nan')),
            lambda r:r['rows'][5].update(reused=1)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.reports = copy.deepcopy(original)
                mutate(self.reports[1]); self.write()
                with self.assertRaises(AssertionError): self.run_summary()

    def test_refuses_second_variable(self):
        path = self.root/'output/verification/test-iq3-memory-tsum-b1.json'
        config = json.loads(path.read_text());config['env']['OTHER']='changed'
        path.write_text(json.dumps(config))
        with self.assertRaises(AssertionError):self.run_summary()

if __name__ == '__main__':
    unittest.main()
