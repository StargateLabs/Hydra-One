import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from serve.update_center import UpdateCenter


class VendorAllowlistPlan(unittest.TestCase):
    def test_job_keeps_the_source_python_for_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            center = UpdateCenter.__new__(UpdateCenter)
            center.root = root
            center.folder = root / 'output/updates'
            center.lock = threading.RLock()
            center.job = {'state': 'idle'}
            python = str(root / 'env/Scripts/python.exe')
            center.result = {'environments': [{'name': 'Visuale', 'python': python}]}
            center.operational_idle = lambda: True
            center._persist_job = lambda: None
            center.status = lambda: {}
            with patch('serve.update_center.threading.Thread') as thread:
                center.prepare_vendor_allowlist('Visuale', {'certifi': None})
            self.assertEqual(center.job['source_python'], python)
            thread.return_value.start.assert_called_once()


class ConservativePlan(unittest.TestCase):
    def test_major_updates_are_pinned_and_torch_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            center = UpdateCenter.__new__(UpdateCenter)
            center.root = root
            center.folder = root / 'output/updates'
            center.folder.mkdir(parents=True)
            center.lock = threading.RLock()
            center.job = {'state': 'idle'}
            center.result = {'environments': [{'name': 'Visuale', 'python': str(root / 'python.exe'),
                                               'update_check': {'state': 'checked'}, 'packages': [
                {'name': 'datasets', 'version': '4.3.0', 'available_version': '5.1.0'},
                {'name': 'certifi', 'version': '2026.7.22', 'available_version': '2026.10.23'},
                {'name': 'torch', 'version': '2.11.0+rocm7.14.0', 'available_version': '2.15.0'}]}]}
            center._persist_job = lambda: None
            center.status = lambda: {}
            with patch('serve.update_center.threading.Thread') as thread:
                center.dependency_plan('Visuale', conservative=True)
            requirements = (Path(center.job['plan_directory']) / 'requirements.txt').read_text(encoding='utf-8')
            self.assertIn('datasets==4.3.0', requirements)
            self.assertIn('certifi>=2026.7.22', requirements)
            self.assertIn('torch==2.11.0+rocm7.14.0', requirements)
            thread.return_value.start.assert_called_once()


class ValidatedStackPlan(unittest.TestCase):
    def _center(self, root):
        center = UpdateCenter.__new__(UpdateCenter)
        center.root = root
        center.folder = root / 'output/updates'
        center.folder.mkdir(parents=True)
        center.lock = threading.RLock()
        center.job = {'state': 'idle'}
        center.result = {'environments': [{'name': 'Unsloth', 'python': str(root / 'python.exe'),
                                           'update_check': {'state': 'checked'}, 'packages': [
            {'name': 'transformers', 'version': '5.17.0', 'available_version': '5.22.2'},
            {'name': 'torchao', 'version': '0.17.0', 'available_version': '0.18.0'},
            {'name': 'trl', 'version': '1.15.0', 'available_version': '1.17.1'},
            {'name': 'datasets', 'version': '4.8.5', 'available_version': '5.1.0'},
            {'name': 'torch', 'version': '2.9.1+cu126', 'available_version': '2.15.0'},
            {'name': 'certifi', 'version': '2026.10.23', 'available_version': '2026.10.23'},
        ]}]}
        center._persist_job = lambda: None
        center.status = lambda: {}
        return center

    def test_unsloth_validated_runtime_blocks_dependency_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            center = self._center(root)
            with self.assertRaisesRegex(ValueError, 'Runtime di inferenza validato'):
                center.dependency_plan('Unsloth')

    def test_shared_runtime_rejects_transformers_component_update(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            center = self._center(root)
            center.result['environments'][0]['name'] = 'Visuale'
            with patch('serve.python_inference_update.selected_python', return_value=root / 'python.exe'), \
                 self.assertRaisesRegex(ValueError, 'Runtime di inferenza validato'):
                center.dependency_plan('Visuale', 'transformers', '5.22.2')

    def test_airllm_rejects_generic_component_update(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            center = self._center(root)
            center.result['environments'][0]['name'] = 'AirLLM'
            with self.assertRaisesRegex(ValueError, 'Runtime di inferenza validato'):
                center.dependency_plan('AirLLM', 'airllm', '4.1.0')


if __name__ == '__main__':
    unittest.main()
