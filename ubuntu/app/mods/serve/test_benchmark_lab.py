import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from serve.benchmark_lab import BenchmarkLab,validate_request

class BenchmarkLabTests(unittest.TestCase):
    def test_scratch_server_receives_owned_bounded_reservation(self):
        with patch('serve.benchmark_lab.threading.Thread'):
            self.lab.start({'model':'strata-iq3_xxs.json'},True)
        request=validate_request({'model':'strata-iq3_xxs.json'},self.lab.models())
        calls=[]
        def launch(command,**kwargs):
            calls.append((command,kwargs))
            if 'serve/server.py' in command:raise RuntimeError('fixture stop before launch')
            return object()
        with patch('serve.benchmark_lab.threading.Thread'),patch('serve.benchmark_lab.subprocess.Popen',side_effect=launch),patch.object(self.lab,'wait_process',return_value=0),patch.object(self.lab,'end_process'):
            token=self.lab.lease.token
            self.lab.run(request)
        server=[kwargs for command,kwargs in calls if 'serve/server.py' in command]
        self.assertEqual(len(server),1)
        self.assertEqual(server[0]['env']['STRATA_VALIDATION_LEASE_TOKEN'],token)
        self.assertEqual(server[0]['env']['STRATA_API_KEY'],'private-fixture')
        self.assertFalse((self.root/'data/.gpu-campaign.lock').exists())

    def test_native_sidecar_inherits_only_its_existing_bounded_reservation(self):
        import os
        with patch('serve.benchmark_lab.threading.Thread'):
            self.lab.start({'model':'strata-iq3_xxs.json'},True)
        self.addCleanup(self.lab.lease.release)
        lease=json.loads((self.root/'data/.gpu-campaign.lock').read_text())
        self.assertEqual(lease['owner'],'strata-bounded-check')
        self.lab.key='fixture-api-key'
        with patch.dict(os.environ,{'STRATA_VALIDATION_LEASE_TOKEN':'unrelated-parent-token'}):
            environment=self.lab.child_environment()
            self.assertEqual(os.environ['STRATA_VALIDATION_LEASE_TOKEN'],'unrelated-parent-token')
        self.assertEqual(environment['STRATA_VALIDATION_LEASE_TOKEN'],lease['token'])
        self.assertEqual(environment['STRATA_API_KEY'],'fixture-api-key')

    def setUp(self):
        # Unit fixtures must not depend on a real campaign listening on 8089.
        probe=patch('serve.benchmark_lab.socket.socket')
        fake=probe.start();self.addCleanup(probe.stop)
        fake.return_value.__enter__.return_value.connect_ex.return_value=1
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'output/verification');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'engine').mkdir();(self.root/'engine/strata.exe').write_text('fixture')
        (self.root/'pack').mkdir();(self.root/'model.gguf').write_bytes(b'GGUF'+b'\0'*24)
        (self.root/'pack/dense.bin').write_bytes(b'abc');(self.root/'pack/index.txt').write_text('# strata pack index v3\n# pool 3\n');(self.root/'pack/native_experts.txt').write_text('fixture')
        (self.root/'pack/tokenizer').mkdir()
        for name in ('vocab.json','merges.txt','chat_template.jinja'):(self.root/'pack/tokenizer'/name).write_text('fixture')
        self.cfg=dict(exe=str(self.root/'engine/strata.exe'),backend='hip',model_name='qwen-iq3_xxs',api_key='private-fixture',args=['--native',str(self.root/'model.gguf'),'--pack',str(self.root/'pack')])
        (self.root/'strata-iq3_xxs.json').write_text(json.dumps(self.cfg));self.lab=BenchmarkLab(self.root)
    def test_catalog_does_not_expose_config(self):
        catalog=self.lab.models();self.assertTrue(catalog[0]['ready']);self.assertNotIn('private-fixture',json.dumps(catalog))
        self.assertNotIn('exe',catalog[0])

    def test_external_measures_imported_once_and_invalid_samples_rejected(self):
        directory=self.root/'data/benchmarks';directory.mkdir(parents=True)
        protocol=dict(warmup=1,runs=2,tokens=128)
        rows=[dict(warmup=i==0,output_tokens=128,reused=0,decode_tok_s=60+i,prefill_tok_s=200,wall_s=3) for i in range(3)]
        report=dict(engine=dict(model='qwen-iq3_xxs'),protocol=protocol,label='20261010-001342-iq3-memory-a1',started_at='2026-10-10T00:13:42Z',status='complete',rows=rows)
        path=directory/'a1.json';path.write_text(json.dumps(report))
        imported=self.lab.imported_history([])
        self.assertEqual(len(imported),1)
        self.assertEqual(imported[0]['results'][0]['summary']['decode_tok_s']['median'],61.5)
        self.assertEqual(self.lab.imported_history(imported),[])
        report['label']='20261010-001342-iq3-memory-b1'
        report['rows'][2]['output_tokens']=127
        (directory/'b1.json').write_text(json.dumps(report))
        self.assertEqual(len(self.lab.imported_history([])[0]['results']),1)
    def test_external_campaign_tracks_interruption_and_completed_state(self):
        (self.root/'data').mkdir(exist_ok=True)
        path=self.root/'data/optimization-campaign.json'
        path.write_text(json.dumps(dict(id='trial',status='running',completed_arms=1,total_arms=4)))
        self.assertEqual(self.lab.status()['external_campaign']['status'],'interrupted')
        (self.root/'data/benchmark-live.json').write_text(json.dumps(dict(active=True,updated_at=time.time(),source_port=8089,metrics={})))
        state=self.lab.status()
        self.assertTrue(state['external_active'])
        self.assertEqual(state['external_campaign']['completed_arms'],1)
        path.write_text(json.dumps(dict(id='trial',status='complete',completed_arms=4,total_arms=4)))
        self.assertEqual(self.lab.status()['external_campaign']['status'],'complete')

    def test_invalid_parameters_refused(self):
        valid=dict(model='strata-iq3_xxs.json')
        for changes in ({'model':'../other.json'},{'tokens':True},{'tokens':4096},{'runs':0},{'ram_gib':64},{'workers':32},
            {'reserve_mib':0},{'spec':20},{'variants':[]},{'variants':['auto','auto']},{'variants':['shell']},{'prompt':'x'*6001},{'command':'anything'}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):validate_request({**valid,**changes},self.lab.models())

    def test_quality_checks_recomputed_from_completed_cases(self):
        directory=self.root/'output/verification';directory.mkdir(parents=True)
        report=dict(status='complete',model='iq3',started_at='2026-10-10T00:00:00Z',correct=999,cases=[dict(passed=True),dict(passed=False)])
        (directory/'good-tasks.json').write_text(json.dumps(report))
        report['cases'][0]['passed']='true'
        (directory/'invalid-tasks.json').write_text(json.dumps(report))
        checks=self.lab.status()['quality_checks']
        self.assertEqual(len(checks),1);self.assertEqual(checks[0]['correct'],1)
        self.assertEqual(checks[0]['total'],2)
    def test_manual_and_automatic(self):
        self.assertEqual(validate_request({'model':'strata-iq3_xxs.json'},self.lab.models())['tokens'],256)
        request=validate_request({'model':'strata-iq3_xxs.json','mode':'automatic','variants':['auto','pcie20'],'quality':True},self.lab.models())
        self.assertEqual(request['variants'],['auto','pcie20'])
    def test_operational_or_external_job_blocks_start(self):
        with self.assertRaises(RuntimeError):self.lab.start({'model':'strata-iq3_xxs.json'},False)
        (self.root/'data').mkdir();(self.root/'data/benchmark-live.json').write_text(json.dumps(dict(active=True,updated_at=time.time(),source_port=8089,metrics={})))
        with self.assertRaises(RuntimeError):self.lab.start({'model':'strata-iq3_xxs.json'},True)
    def test_one_job_and_stop_are_persisted(self):
        with patch('serve.benchmark_lab.threading.Thread'):
            job=self.lab.start({'model':'strata-iq3_xxs.json'},True)
        self.assertEqual(job['total_samples'],10);self.assertTrue(self.lab.active())
        with self.assertRaises(RuntimeError):self.lab.start({'model':'strata-iq3_xxs.json'},True)
        self.lab.cancel();self.assertTrue((self.lab.directory/'stop').is_file())
        self.assertEqual(json.loads((self.lab.directory/'job.json').read_text())['status'],'cancelling')
    def test_failed_persistence_releases_reservation(self):
        from serve.gpu_lease import reserved
        with patch('serve.benchmark_lab.atomic_json',side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):self.lab.start({'model':'strata-iq3_xxs.json'},True)
        self.assertFalse(reserved(self.root));self.assertFalse(self.lab.active())
    def test_completed_job_recovers_and_history_keeps_protocol(self):
        with patch('serve.benchmark_lab.threading.Thread'):
            job=self.lab.start({'model':'strata-iq3_xxs.json'},True)
        self.lab.update(status='complete',phase='Qualità · completata',finished_at=time.time());self.lab.lease.release()
        recovered=BenchmarkLab(self.root);status=recovered.status()
        self.assertEqual(status['job']['id'],job['id']);self.assertEqual(status['job']['completed_samples'],10)
        self.assertEqual(status['history'][0]['protocol']['tokens'],256)
        self.assertEqual(status['job']['phase'],'Qualità · completata')

if __name__=='__main__':unittest.main()
