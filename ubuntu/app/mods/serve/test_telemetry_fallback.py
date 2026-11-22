import builtins,struct,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from serve.telemetry import Telemetry,_AmdWindows

class FakePdh:
    def __init__(self,name,value):
        self.name,self.value=name,value
    def PdhGetFormattedCounterArrayW(self,handle,fmt,need,count,buf):
        raw=(self.name+'\x00').encode('utf-16-le');total=24+len(raw)
        need._obj.value=total;count._obj.value=1
        if buf is None:return 0x800007D2
        struct.pack_into('<d',buf,16,self.value);buf[24:24+len(raw)]=raw
        return 0

class TelemetryFallbackTests(unittest.TestCase):
    def probe(self,setup_module=None):
        original=builtins.__import__
        def importing(name,*args,**kwargs):
            if name=='setup':
                if setup_module is None:raise ModuleNotFoundError('Setup unavailable')
                return setup_module
            return original(name,*args,**kwargs)
        gpu=SimpleNamespace(ok=lambda:True,name=lambda:'AMD fixture')
        with patch('serve.telemetry.gpu_reader',return_value=gpu),patch('serve.telemetry.windows_amd_cards',return_value=[]),patch('serve.telemetry.threading.Thread'),patch('builtins.__import__',side_effect=importing):
            return Telemetry(amd=True)
    def test_missing_setup_does_not_break_cpu_and_gpu_name_telemetry(self):
        telemetry=self.probe()
        self.assertEqual(telemetry.static['gpu_archs'],[])
        self.assertEqual(telemetry.static['gpu_name'],'AMD fixture')
        self.assertIn('threads',telemetry.static)
    def test_incomplete_setup_helpers_leave_architecture_unknown(self):
        telemetry=self.probe(SimpleNamespace(ROOT=Path('missing')))
        self.assertEqual(telemetry.static['gpu_archs'],[])
    def test_the_pdh_array_is_parsed(self):
        # a missing `import struct` in telemetry made every _array call return {} (the
        # exception was swallowed), so the Monitor showed no GPU load and no VRAM
        reader=object.__new__(_AmdWindows);reader._PDH_MORE_DATA=0x800007D2
        reader.pdh=FakePdh('luid_0x00000000_0x0001bad7_phys_0',2.5)
        self.assertEqual(reader._array(None),{'luid_0x00000000_0x0001bad7_phys_0':2.5})
    def test_the_adapter_luid_comes_from_the_pdh_instances_when_dxgi_is_blind(self):
        reader=object.__new__(_AmdWindows)
        reader.pdh=None;reader._q_util=reader._q_mem=reader._q_tc=None
        reader._h_util=[1];reader._h_mem=[2];reader._h_tc=[3]
        reader._amd_index=0;reader._vram_total=0;reader._k32=None
        util={'pid_1_luid_0x0_0x1bad7_phys_0_eng_0':12.5}
        mem={'luid_0x0_0x1bad7_phys_0':2*2**30}
        reader._array=lambda handle:util if handle==1 else mem if handle==2 else {}
        with patch('serve.windows_gpu_identity.amd_luid',return_value=None):
            out=reader.read()
        self.assertEqual(out['util'],12.5)
        self.assertEqual(out['mem_used'],2*2**30)
    def test_aida_cpu_sensors_keep_their_own_names(self):
        # the AMD reader also reads AIDA64's CPU sensors; sample() used to rename every
        # one of them gpu_*, so the Monitor's CPU temperature and power were always "-"
        gpu=SimpleNamespace(ok=lambda:True,name=lambda:'AMD fixture',
                            read=lambda:{'util':12.0,'mem_used':0,'cpu_temp':42.0,'cpu_power':100.0})
        with patch('serve.telemetry.gpu_reader',return_value=gpu),patch('serve.telemetry.windows_amd_cards',return_value=[]),patch('serve.telemetry.threading.Thread'):
            telemetry=Telemetry(amd=True)
            sample=telemetry.sample()
        self.assertEqual(sample['cpu_temp'],42.0)
        self.assertEqual(sample['cpu_power'],100.0)
        self.assertEqual(sample['gpu_util'],12.0)
        self.assertNotIn('gpu_cpu_temp',sample)
        self.assertNotIn('gpu_cpu_power',sample)
    def test_the_aida_parser_reads_gpu_and_cpu_sensors(self):
        text=('<temp><id>TGPU1</id><label>GPU</label><value>55</value></temp>'
              '<pwr><id>PGPU1</id><label>GPU</label><value>210.5</value></pwr>'
              '<temp><id>TCPUPKG</id><label>CPU Package</label><value>61</value></temp>')
        self.assertEqual(_AmdWindows._aida_parse(text),{'TGPU1':'55','PGPU1':'210.5','TCPUPKG':'61'})
    def test_the_aida_registry_export_is_used_when_the_page_has_no_gpu(self):
        reader=object.__new__(_AmdWindows);reader._k32=None
        with patch.object(_AmdWindows,'_aida_registry',return_value={'TGPU1':'57','PGPU1':'190'}):
            self.assertEqual(reader._aida_read(),{'TGPU1':'57','PGPU1':'190'})

if __name__=='__main__':unittest.main()
