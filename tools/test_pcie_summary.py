import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import summarize_pcie_abba as module
from iq3_memory_ab import pcie55_arms

class PcieSummary(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=module.ROOT/'output/verification');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'data/benchmarks').mkdir(parents=True);(self.root/'output/verification').mkdir(parents=True)
        self.reports=[]
        for index,(name,args) in enumerate(pcie55_arms('pcie55-abba')):
            config=dict(args=args,env={'constant':'1'})
            (self.root/f'output/verification/test-iq3-memory-{name}.json').write_text(json.dumps(config))
            self.reports.append(dict(status='complete',started_at='2026-10-09T00:00:00Z',binary_sha256='a'*64,
                engine=dict(model='iq3_xxs',expert_slots=8706,vram_free_mib=2400,pcie_frac='0.55' if index in (1,2) else '0.36'),
                protocol=dict(tokens=256,warmup=5,runs=5),rows=[dict(warmup=i<5,output_tokens=256,reused=0,prompt_sha256=str(i),
                    decode_tok_s=50,prefill_tok_s=180,wall_s=10,wall_tok_s=25.6) for i in range(10)]))
        self.write()
    def write(self):
        for name,report in zip(module.NAMES,self.reports):
            (self.root/f'data/benchmarks/test-iq3-memory-{name}.json').write_text(json.dumps(report))
    def summarize(self):
        with patch.object(module,'ROOT',self.root),patch('builtins.print'):return module.summarize('test')
    def test_valid(self):self.assertEqual(self.summarize()['pooled']['decode_tok_s']['change_percent'],0)
    def test_refuses_uncontrolled_reports(self):
        initial=copy.deepcopy(self.reports)
        for mutate in (lambda r:r.update(status='running'),lambda r:r['engine'].update(pcie_frac='0.36'),
            lambda r:r['engine'].update(vram_free_mib=37),lambda r:r['engine'].update(expert_slots=9000),
            lambda r:r.update(binary_sha256='b'*64),lambda r:r['rows'][5].update(prompt_sha256='different'),
            lambda r:r['rows'][5].update(decode_tok_s=float('nan')),lambda r:r['rows'][5].update(reused=1)):
            with self.subTest(mutation=mutate):
                self.reports=copy.deepcopy(initial);mutate(self.reports[1]);self.write()
                with self.assertRaises(AssertionError):self.summarize()

if __name__=='__main__':unittest.main()
