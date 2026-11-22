"""The visual worker declares the families it can prepare, and each source matches one."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'serve' / 'local_visual_generation.py'
PREPARE = ROOT / 'tools' / 'prepare_local_visual_model.py'


class VisualSourceTests(unittest.TestCase):
    def test_every_declared_family_has_a_preparable_source(self):
        """A family the worker supports must not be unreachable by design."""
        worker = WORKER.read_text(encoding='utf-8')
        prepare = PREPARE.read_text(encoding='utf-8')
        families = {'StableDiffusionPipeline': 'segmind/tiny-sd',
                    'StableDiffusionXLPipeline': None,
                    'TextToVideoSDPipeline': 'damo-vilab/text-to-video-ms-1.7b'}
        for family, expected in families.items():
            with self.subTest(family=family):
                self.assertIn(family, worker)
                if expected:
                    self.assertIn(expected, prepare)

    def test_sdxl_family_can_be_prepared(self):
        prepare = PREPARE.read_text(encoding='utf-8')
        self.assertIn('stabilityai/stable-diffusion-xl-base-1.0', prepare,
                      'no way to obtain SDXL weights for the declared StableDiffusionXLPipeline family')

    def test_plan_excludes_duplicate_and_unused_sdxl_weights(self):
        from tools.prepare_local_visual_model import select_files
        metadata={'siblings':[{'rfilename':name,'size':size} for name,size in [
            ('model_index.json',50),('unet/config.json',60),('unet/diffusion_pytorch_model.fp16.safetensors',300),
            ('unet/diffusion_pytorch_model.safetensors',600),('unet/diffusion_pytorch_model.bin',600),
            ('vae_1_0/diffusion_pytorch_model.fp16.safetensors',200),('sd_xl_base_1.0.safetensors',900)]]}
        files=select_files('stabilityai/stable-diffusion-xl-base-1.0',metadata)
        self.assertEqual([row[0] for row in files],['model_index.json','unet/config.json','unet/diffusion_pytorch_model.fp16.safetensors'])

    def test_unknown_repository_is_rejected(self):
        from tools.prepare_local_visual_model import prepare
        with self.assertRaises(ValueError):
            prepare('some/unchecked-repo', str(ROOT / 'models' / 'rejected'))


if __name__ == '__main__':
    unittest.main()
