import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from serve.training_options import training_options
from tools.train_local_lora import validate_checkpoint

class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.model=self.root/'model';self.model.mkdir()
        self.train=self.root/'train.jsonl';self.train.write_text('{"text":"train"}')
        self.validation=self.root/'validation.jsonl';self.validation.write_text('{"text":"validation"}')
        self.checkpoint=self.root/'output/training/run/trainer/checkpoint-2';self.checkpoint.mkdir(parents=True)
        self.options=training_options({'steps':3})
        self.source={'base':str(self.model),'options':self.options,
            'train_sha256':hashlib.sha256(self.train.read_bytes()).hexdigest(),
            'validation_sha256':hashlib.sha256(self.validation.read_bytes()).hexdigest()}
        (self.checkpoint.parent.parent/'workflow.json').write_text(json.dumps(self.source))
        (self.checkpoint/'trainer_state.json').write_text('{"global_step":2}')
        for name in ('optimizer.pt','scheduler.pt','rng_state.pth','adapter_config.json','adapter_model.safetensors'):
            (self.checkpoint/name).write_bytes(b'test fixture')
    def validate(self,**changes):
        return validate_checkpoint(self.root,self.checkpoint,self.model,self.train,self.validation,{**self.options,**changes})
    def test_valid_checkpoint_and_disabled_resume(self):
        self.assertEqual(self.validate(),self.checkpoint)
        self.assertIsNone(validate_checkpoint(self.root,None,None,None,None,{}))
    def test_changed_data_configuration_and_nonforward_target_rejected(self):
        for changes in ({'rank':4},{'steps':2},{'learning_rate':0.002}):
            with self.assertRaises(ValueError):self.validate(**changes)
        self.train.write_text('{"text":"changed"}')
        with self.assertRaisesRegex(ValueError,'dataset differs'):self.validate()
    def test_runner_and_device_mismatch_rejected(self):
        for changes in ({'runner':'unsloth_qlora','device':'cuda'},{'device':'cuda'}):
            with self.assertRaisesRegex(ValueError,'runner or device'):self.validate(**changes)
    def test_native_checkpoint_hashes_are_required_and_checked(self):
        self.options.update(runner='unsloth_qlora',device='cuda');self.source['options']=self.options
        (self.checkpoint.parent.parent/'workflow.json').write_text(json.dumps(self.source),encoding='utf-8')
        with self.assertRaises(FileNotFoundError):self.validate()
        names=('optimizer.pt','scheduler.pt','rng_state.pth','adapter_config.json','adapter_model.safetensors','trainer_state.json')
        manifest={name:{'bytes':(self.checkpoint/name).stat().st_size,'sha256':hashlib.sha256((self.checkpoint/name).read_bytes()).hexdigest()} for name in names}
        (self.checkpoint/'CHECKPOINT-INTEGRITY.json').write_text(json.dumps(manifest),encoding='utf-8')
        self.assertEqual(self.validate(),self.checkpoint)
        (self.checkpoint/'optimizer.pt').write_bytes(b'modified')
        with self.assertRaisesRegex(ValueError,'integrity failure'):self.validate()
    def test_missing_optimizer_rejected(self):
        (self.checkpoint/'optimizer.pt').unlink()
        with self.assertRaisesRegex(ValueError,'Incomplete'):self.validate()
    def test_external_checkpoint_rejected(self):
        with self.assertRaisesRegex(ValueError,'local training workflow'):
            validate_checkpoint(self.root,self.model,self.model,self.train,self.validation,self.options)

if __name__=='__main__':unittest.main()
