import unittest
from serve import pytorch_integration as integration

class PytorchIntegrationTests(unittest.TestCase):
    def test_flavor_preserves_exact_local_version_and_avoids_guessing(self):
        for version,flavor in [('2.8.0+cpu','cpu'),('2.9.1+cu128','cuda'),('2.9.0+rocm6.4','rocm'),('2.9.0','unknown')]:
            row=integration.torch_build(version)
            self.assertEqual(row['version'],version)
            self.assertEqual(row['flavor'],flavor)
        self.assertTrue(integration.torch_build('2.9.0+rocm6.4')['requires_vendor_channel'])

    def test_inventory_stays_environment_scoped(self):
        rows=integration.installed_environments([{'name':'Unsloth','packages':[{'name':'torch','version':'2.9.0+rocm6.4'}]},
             {'name':'Soup','packages':[{'name':'torch','version':'2.8.0+cpu'}]}])
        self.assertEqual([row['flavor'] for row in rows],['rocm','cpu'])
        self.assertEqual(integration.installed_metadata([{'name':'Unsloth','packages':[{'name':'torch','version':'2.9.0+rocm6.4'}]}])['installed_version'],'2.9.0+rocm6.4')

    def test_generic_release_is_not_an_actionable_build_update(self):
        for version in ("2.11.0+rocm7.14.0", "2.9.1+cu128", "2.8.0+cpu", "2.9.0"):
            row=integration.installed_metadata([{"name":"Unsloth","packages":[{"name":"torch","version":version}]}])
            self.assertFalse(row["version_comparable"])
            self.assertFalse(row["automatic_update_supported"])

    def test_official_release_not_a_device_compatibility_claim(self):
        row=integration.release_from_metadata({'info':{'name':'torch','version':'2.9.1','requires_python':'>=3.10'},'urls':[]})
        self.assertEqual(row['repository'],'pytorch/pytorch')
        self.assertFalse(row['runtime_validated'])
        self.assertFalse(row['flavor_compatibility_verified'])
        for name,version in [('pytorch','2.9.1'),('torch','2.10.0rc1')]:
            with self.assertRaises(ValueError):integration.release_from_metadata({'info':{'name':name,'version':version}})

if __name__=='__main__':unittest.main()
