"""Compile the prepared fixture's actual comparator, CPU only, no HIP linkage."""
import json
import shutil
import subprocess
from tools.prepare_hc_alias_fixture import ROOT, prepare

def main():
    original=(ROOT/'output/research/source-hc-small-window-01403/src/kernels/gr_parity.cpp').read_text(encoding='utf-8')
    generated=prepare(original)
    start=generated.index('    auto close = []')
    end=generated.index('    auto same =',start)
    comparator=generated[start:end]
    folder=ROOT/'output/research/hc-alias-fixture-review'
    folder.mkdir(parents=True,exist_ok=True)
    source=folder/'comparator_cpu.cpp'
    source.write_text('''#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <vector>
int main() {
'''+comparator+'''
    const float nan=std::numeric_limits<float>::quiet_NaN();
    const float inf=std::numeric_limits<float>::infinity();
    if (!close({1.0f},{1.0f})) return 1;
    if (!close({1.000001f},{1.0f})) return 2;
    if (close({1.01f},{1.0f})) return 3;
    if (close({nan},{1.0f})) return 4;
    if (close({1.0f},{nan})) return 5;
    if (close({inf},{inf})) return 6;
    if (close({1.0f},{})) return 7;
    if (close({},{1.0f})) return 8;
    std::puts("CPU comparator: 8 cases passed");
}
''',encoding='utf-8')
    compiler=shutil.which('g++')
    if not compiler:raise RuntimeError('CPU C++ compiler unavailable')
    executable=folder/'comparator_cpu.exe'
    subprocess.run([compiler,'-std=c++17','-O2','-static',str(source),'-o',str(executable)],check=True,capture_output=True,text=True)
    result=subprocess.run([str(executable)],check=True,capture_output=True,text=True)
    report=dict(scope='Actual tolerance lambda compiled and executed on CPU; no GPU code linked',passed=True,cases=8,output=result.stdout.strip(),root_cause_confirmed=False)
    (ROOT/'output/verification/hc-comparator-cpu.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
