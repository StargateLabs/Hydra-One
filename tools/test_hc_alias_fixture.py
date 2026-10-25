import unittest
from tools.prepare_hc_alias_fixture import prepare, ROOT

class AliasFixtureTest(unittest.TestCase):
    def test_prepared_coverage_and_resets(self):
        original=(ROOT/'output/research/source-hc-small-window-01403/src/kernels/gr_parity.cpp').read_text(encoding='utf-8')
        generated=prepare(original)
        self.assertIn('in_place ? d_r : d_r_out',generated)
        self.assertIn('eps, window, false, true)',generated)
        self.assertEqual(generated.count('    reset_input();'),4)
        self.assertIn('repetition < 3',generated)
        self.assertIn('if (x.size() != y.size()) return false;',generated)
        self.assertIn('!std::isfinite(x[i]) || !std::isfinite(y[i])',generated)
        self.assertIn('std::fabs((double) x[i] - (double) y[i])',generated)
        self.assertNotEqual(original,generated)
        with self.assertRaises(ValueError):prepare(generated)

if __name__=='__main__':unittest.main()
