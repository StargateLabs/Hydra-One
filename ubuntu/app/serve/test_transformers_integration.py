import unittest
from serve.transformers_integration import installed_environments,release_from_metadata,runtime_versions


class TransformersIntegration(unittest.TestCase):
    def test_versions_remain_per_environment(self):
        rows=installed_environments([{'name':'Strata','python':'a','packages':[]},
             {'name':'Unsloth','python':'b','python_version':'3.12.10','packages':[{'name':'transformers','version':'4.57.1'}]},
             {'name':'Soup','python':'c','packages':[{'name':'transformers','version':'5.0.0'}]}])
        self.assertEqual([row['version'] for row in rows],['4.57.1','5.0.0'])
        self.assertEqual(rows[0]['environment'],'Unsloth')

    def test_release_rejects_wrong_package_and_prerelease(self):
        for name,version in [('other','5.0.0'),('transformers','5.0.0rc1')]:
            with self.assertRaises(ValueError):release_from_metadata({'info':{'name':name,'version':version}})

    def test_python_requirement_is_preserved_not_certified(self):
        row=release_from_metadata({'info':{'name':'transformers','version':'5.19.0','requires_python':'>=3.10'},'urls':[]})
        self.assertEqual(row['requires_python'],'>=3.10')
        self.assertEqual(row['update_method'],'isolated_python_dependencies')
        self.assertFalse(row['runtime_validated'])

    def test_training_provenance_keeps_unavailable_packages_null(self):
        from unittest.mock import patch
        from importlib.metadata import PackageNotFoundError
        with patch('importlib.metadata.version',side_effect=PackageNotFoundError):
            versions=runtime_versions()
        self.assertTrue(versions['python'])
        self.assertEqual(versions['packages']['transformers'],None)
        self.assertIn('torch',versions['packages'])
