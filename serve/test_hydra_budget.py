import unittest
from serve import hydra_one


class ControlBudget(unittest.TestCase):
    def test_default_is_control_plane_only_and_does_not_recount_resident_weights(self):
        row=hydra_one.control_budget({})
        self.assertEqual(row['host_required_bytes'],0)
        self.assertEqual(row['request_memory_bytes'],256*1024**2)
        self.assertEqual(row['scope'],'post_load_headroom_not_model_capacity')
        self.assertIsNone(row['kv_required_bytes'])

    def test_custom_headroom_is_validated_before_optional_launch(self):
        p={'mode':'gguf','engine_addon':'hydra-one','hydra_budget':{'host_limit_bytes':128*1024**2}}
        with self.assertRaises(ValueError):hydra_one.requested(p)

    def test_invalid_values_fail_closed(self):
        for value in [None,[],{'request_memory_bytes':True},{'host_limit_bytes':float('inf')},{'kv_bytes':1},{'host_reserve_bytes':-1}]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):hydra_one.control_budget({'hydra_budget':value})

    def test_explicit_limits_preserve_defaults_and_are_not_mutated(self):
        p={'hydra_budget':{'request_memory_bytes':512*1024**2}}
        row=hydra_one.control_budget(p)
        self.assertEqual(row['request_memory_bytes'],512*1024**2)
        self.assertEqual(p['hydra_budget'],{'request_memory_bytes':512*1024**2})
