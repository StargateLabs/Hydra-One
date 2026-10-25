import unittest
from iq3_memory_ab import pcie55_arms,pcie_arms

class PciePlan(unittest.TestCase):
    def test_one_variable_and_margin(self):
        for plan in ('pcie55-check','pcie55-abba','quality-pcie55-paired'):
            for name,args in pcie55_arms(plan):
                values=dict(zip(args[::2],args[1::2]))
                self.assertEqual(values['--expert-cache'],'6500')
                self.assertEqual(values['--vram-reserve-mib'],'2560')
                self.assertEqual(values['--resident-budget-gib'],'16')
                self.assertEqual(values['--prefill'],'512')
                candidate=name in ('pcie55-check','pcie55-b1','pcie55-b2','quality-pcie55-candidate')
                self.assertEqual(values.get('--pcie-frac'),'0.55' if candidate else None)
                self.assertNotIn('--pool-workers',values)
    def test_abba_order(self):
        self.assertEqual([name for name,_ in pcie55_arms('pcie55-abba')],['pcie-auto-a1','pcie55-b1','pcie55-b2','pcie-auto-a2'])
    def test_pcie20_has_same_control_and_isolated_candidate(self):
        arms=pcie_arms('pcie20-abba',20)
        self.assertEqual([name for name,_ in arms],['pcie-auto-a1','pcie20-b1','pcie20-b2','pcie-auto-a2'])
        self.assertEqual(arms[0][1],pcie55_arms('pcie55-abba')[0][1])
        candidate=list(arms[1][1]);self.assertEqual(candidate[-2:],['--pcie-frac','0.20']);self.assertEqual(candidate[:-2],arms[0][1])
        self.assertEqual(arms[1][1],arms[2][1]);self.assertEqual(arms[0][1],arms[3][1])

if __name__=='__main__':unittest.main()
