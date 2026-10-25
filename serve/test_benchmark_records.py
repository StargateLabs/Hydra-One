import copy
import json
from pathlib import Path
import tempfile
import unittest
from serve.benchmark_records import best_groups

class RecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'output/verification');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def record(self,identity,speed,tokens=128,status='complete'):
        directory=self.root/'data/benchmark-lab'/identity;directory.mkdir(parents=True)
        protocol=dict(model='strata-model.json',tokens=tokens,runs=5,paragraphs=8,workers=16,spec=4,ram_gib=16,reserve_mib=2560,mode='manual',variants=['auto'],quality=False)
        source=f'data/benchmarks/lab-{identity}-auto.json'
        job=dict(id=identity,status=status,protocol=protocol,prompt_sha256='b'*64,finished_at=float(identity),results=[dict(variant='auto',label='Auto',source=source)])
        (directory/'job.json').write_text(json.dumps(job));(directory/'auto-config.json').write_text(json.dumps(dict(args=['--native','same-model.gguf'],env={})))
        raw=dict(protocol={**protocol,'warmup':5},status='complete',engine={'model':'model'},binary_sha256='a'*64,rows=[dict(reused=0,output_tokens=tokens,warmup=i<5,decode_tok_s=speed,prefill_tok_s=200,wall_s=4) for i in range(10)])
        report=self.root/source;report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(raw));return report
    def test_larger_complete_updates_but_failed_does_not(self):
        self.record('1',50);self.record('2',60);self.record('3',100,status='failed')
        groups=best_groups(self.root,'model');self.assertEqual(len(groups),1);self.assertEqual(groups[0]['winner']['summary']['decode_tok_s'],60)
        self.assertEqual(groups[0]['tested_profiles'],2)
    def test_protocols_are_separate(self):
        self.record('1',100,128);self.record('2',60,256)
        groups=best_groups(self.root,'model');self.assertEqual(len(groups),2);self.assertEqual(groups[0]['protocol']['tokens'],256)
        self.assertEqual(groups[1]['winner']['summary']['decode_tok_s'],100)
    def test_invalid_or_wrong_model_report_never_becomes_record(self):
        path=self.record('1',100);raw=json.loads(path.read_text());raw['rows'][7]['decode_tok_s']=0;path.write_text(json.dumps(raw))
        self.assertEqual(best_groups(self.root,'model'),[])
        self.record('2',80);self.assertEqual(best_groups(self.root,'other-model'),[])

if __name__=='__main__':unittest.main()
