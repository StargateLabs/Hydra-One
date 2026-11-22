import json,tempfile,unittest
from pathlib import Path
from serve import safetensors_runtime as runtime

class CheckpointBoundaryTests(unittest.TestCase):
    def test_quantization_classification_retains_loader_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            config=dict(architectures=['Qwen2ForCausalLM'],max_position_embeddings=2048,
                        quantization_config={'quant_method':'awq','bits':4})
            (folder/'config.json').write_text(json.dumps(config))
            (folder/'model.safetensors').write_bytes(b'fixture')
            info=runtime.inspect_model(folder,allow_unsupported=True)
            self.assertEqual(info['checkpoint_quantization']['method'],'awq')
            self.assertFalse(info['runtime_supported'])
            with self.assertRaisesRegex(ValueError,'AWQ'):runtime.inspect_model(folder)
            config['quantization_config']={'load_in_4bit':True,'bnb_4bit_quant_type':'nf4'}
            (folder/'config.json').write_text(json.dumps(config))
            info=runtime.inspect_model(folder,allow_unsupported=True)
            self.assertEqual(info['checkpoint_quantization']['method'],'bitsandbytes')
            self.assertEqual(info['checkpoint_quantization']['scheme'],'nf4')
            with self.assertRaises(ValueError):runtime.inspect_model(folder)

    def test_adapter_base_identity_and_safe_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);adapter=folder/'adapter';adapter.mkdir()
            (adapter/'adapter_model.safetensors').write_bytes(b'fixture')
            config=adapter/'adapter_config.json'
            config.write_text(json.dumps({'base_model_name_or_path':str(folder)}))
            self.assertEqual(runtime.validate_adapter(adapter,folder)['base_model_name_or_path'],str(folder))
            for base in ('publisher/model',str(folder/'other'),''):
                config.write_text(json.dumps({'base_model_name_or_path':base}))
                with self.assertRaises(ValueError):runtime.validate_adapter(adapter,folder)

if __name__=='__main__':unittest.main()
