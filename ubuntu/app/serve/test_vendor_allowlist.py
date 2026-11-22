import unittest
from serve.vendor_python_update import constraints_text, reconciled_health, validate_report


ORIGINAL = {'torch': '2.11.0+rocm7.14.0', 'certifi': '2026.7.22', 'datasets': '4.3.0'}


class AllowlistHelpers(unittest.TestCase):
    def test_constraints_pin_everything_outside_the_allowlist(self):
        text = constraints_text(ORIGINAL, {'certifi'})
        self.assertIn('torch==2.11.0+rocm7.14.0', text)
        self.assertIn('datasets==4.3.0', text)
        self.assertNotIn('certifi==', text)

    def test_report_may_only_change_allowlisted_packages(self):
        report = [{'metadata': {'name': 'certifi', 'version': '2026.10.23'}}]
        self.assertEqual(validate_report(report, {'certifi'}, {'certifi': None}, ORIGINAL), ['certifi'])

    def test_report_rejects_a_vendor_substitution(self):
        report = [{'metadata': {'name': 'torch', 'version': '2.15.0'}}]
        with self.assertRaises(ValueError):
            validate_report(report, {'certifi'}, {'certifi': None}, ORIGINAL)

    def test_preserved_conflicts_are_allowed_only_when_identical(self):
        self.assertEqual(reconciled_health('a', 'a', False), 'preserved_conflicts')
        self.assertEqual(reconciled_health('a', 'b', False), 'conflicts')
        self.assertEqual(reconciled_health('a', 'a', True), 'healthy')

    def test_report_rejects_a_wrong_requested_version(self):
        report = [{'metadata': {'name': 'certifi', 'version': '2026.7.22'}}]
        with self.assertRaises(ValueError):
            validate_report(report, {'certifi'}, {'certifi': '2026.10.23'}, ORIGINAL)


if __name__ == '__main__':
    unittest.main()
