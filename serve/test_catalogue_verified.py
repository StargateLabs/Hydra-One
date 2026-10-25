import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from serve import catalogue_verified as cat
from serve.gpu_lease import GpuLease,reserved
from serve.model_inventory import inspect_config

def metadata(arch='qwen4exp',experts=512):
    rows={'general.architecture':arch,'qwen4exp.block_count':48,'qwen4exp.expert_count':experts,'qwen4exp.embedding_length':2560}
    def string(s):b=s.encode();return struct.pack('<Q',len(b))+b
    body=b''
    for key,value in rows.items():body+=string(key)+(struct.pack('<I',8)+string(value) if isinstance(value,str) else struct.pack('<II',4,value))
    return b'GGUF'+struct.pack('<IQQ',3,1,len(rows))+body

class CatalogueTests(unittest.TestCase):
    def test_actual_tensor_layout_rejects_wrong_formats_shapes_and_missing_roles(self):
        records=[]
        for layer in range(48):
            records.append(dict(name=f'blk.{layer}.ffn_gate_inp.weight',shape=[2560,512],type=30))
            for role in ('gate','up','down'):
                records.append(dict(name=f'blk.{layer}.ffn_{role}_exps.weight',shape=[640,2560,512] if role=='down' else [2560,640,512],type=42))
        records.append(dict(name='per_layer_token_embd.weight',shape=[256,1000],type=20))
        h={'general.architecture':'qwen4exp','__tensors':records}
        self.assertEqual(cat.validate_layout([h],512)['expert_tensors'],144)
        for replacement in ({'type':40},{'shape':[2560,640,256]}):
            altered=json.loads(json.dumps(h));altered['__tensors'][1].update(replacement)
            with self.assertRaises(ValueError):cat.validate_layout([altered],512)
        altered=json.loads(json.dumps(h));altered['__tensors'].pop(1)
        with self.assertRaises(ValueError):cat.validate_layout([altered],512)
        with self.assertRaises(ValueError):cat.validate_layout([h,h],512)

    def test_hybrid_is_curated_as_q2_experts_with_complete_shards(self):
        self.assertIn(dict(repo='shefowl/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-Hybrid-GGUF',quant='Q2_0'),cat.CURATED)
        repo=Path(__file__).resolve().parents[1]/'output/research/hf-models-20261009/shefowl--Qwen3.8-Flash-Next-GSQ-RCO-abliterated-Hybrid-GGUF.json'
        data=json.loads(repo.read_text())
        with patch.object(cat,'get_json',return_value=data):
            cat._cache.pop(data['id'],None)
            group=cat.repo_info(data['id'])['groups']['Q2_0']
        self.assertEqual(len(group),2)
        self.assertTrue(cat.complete_group(group))

    def test_metadata_and_truncation(self):
        self.assertEqual(cat.parse_metadata(metadata())['qwen4exp.expert_count'],512)
        self.assertEqual(cat.parse_metadata(metadata('llama'))['general.architecture'],'llama')
        with self.assertRaises(EOFError):cat.parse_metadata(metadata()[:-2])
        with self.assertRaises(ValueError):cat.parse_metadata(b'no GGUF')
    def test_missing_or_duplicate_shards_rejected(self):
        items=[{'path':f'IQ3_XXS/model-IQ3_XXS-{i:05}-of-00003.gguf'} for i in range(1,4)]
        self.assertTrue(cat.complete_group(items));self.assertFalse(cat.complete_group(items[:2]))
        self.assertFalse(cat.complete_group([items[0],items[0],items[2]]))
        self.assertTrue(cat.complete_group([{'path':'model-IQ3_XXS.gguf'}]))
    def test_host_checks_fail_closed(self):
        host=dict(ram_total_gib=64,ram_free_gib=32,vram_total_gib=24,free_gib=200)
        self.assertTrue(cat.fit_host('IQ3_XXS',70,host,'hip')[0])
        for changes in ({'ram_total_gib':32},{'vram_total_gib':None},{'free_gib':1},{'ram_free_gib':1}):
            self.assertFalse(cat.fit_host('IQ3_XXS',70,{**host,**changes},'hip')[0])
        self.assertFalse(cat.fit_host('UD-IQ3_XXS',70,host,'hip')[0])
        self.assertFalse(cat.fit_host('Q2_0',50,host,'hip',family='swift')[0])
        self.assertFalse(cat.fit_host('IQ3_XXS',70,host,'cuda')[0])
        self.assertTrue(cat.fit_host('IQ3_XXS',70,{**host,'free_gib':1},'hip',installed=True)[0])
    def test_architecture_rejected_before_registration(self):
        info=dict(revision='a'*40,groups={'IQ3_XXS':[dict(path='m-IQ3_XXS.gguf',size=70*2**30,sha256='a'*64)]},headers={'IQ3_XXS':cat.parse_metadata(metadata('llama'))},author='test')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'output/verification') as root,patch.object(cat,'repo_info',return_value=info):
            with self.assertRaisesRegex(ValueError,'Architettura'):cat.inspect('test/model','IQ3_XXS',{},'hip',Path(root))
    def test_reservation_exclusive_and_owned_cleanup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'output/verification') as root:
            first=GpuLease(root,'first').acquire();self.assertTrue(reserved(root))
            with self.assertRaises(RuntimeError):GpuLease(root,'other').acquire()
            first.release();self.assertFalse(reserved(root))
            with GpuLease(root,'next'):self.assertTrue(reserved(root))
            self.assertFalse(reserved(root))
    def test_readiness_rejects_missing_native(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'output/verification') as root:
            path=Path(root)/'strata-example.json';path.write_text(json.dumps(dict(exe=__file__,args=['--native','missing','--pack','missing'])))
            self.assertFalse(inspect_config(path)['ready'])

if __name__=='__main__':unittest.main()
