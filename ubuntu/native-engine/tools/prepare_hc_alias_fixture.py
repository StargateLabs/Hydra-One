"""Prepare isolated alias coverage; never builds or launches the GPU candidate."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def prepare(text):
    def replace(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError('Unexpected parity source anchor: '+old[:70])
        text=text.replace(old,new,1)
    replace('bool qfuse_check = true) {','bool qfuse_check = true, bool in_place = false) {')
    replace('a.R_out = d_r_out + (size_t) t * D;',
            'a.R_out = (in_place ? d_r : d_r_out) + (size_t) t * D;')
    replace('cudaMemcpy(s.r_out.data(), d_r_out,',
            'cudaMemcpy(s.r_out.data(), in_place ? d_r : d_r_out,')
    replace('    auto close = [](const std::vector<float>& x, const std::vector<float>& y) {',
            '    auto close = [](const std::vector<float>& x, const std::vector<float>& y) {\n        if (x.size() != y.size()) return false;')
    replace('            worst = std::max(worst, (double) std::fabs(x[i] - y[i]));',
            '            if (!std::isfinite(x[i]) || !std::isfinite(y[i])) return false;\n            worst = std::max(worst, std::fabs((double) x[i] - (double) y[i]));')
    reset='''    auto reset_input = [&]() {
        check(cudaMemcpyAsync(d_r, r.data(), r.size() * sizeof(float), cudaMemcpyHostToDevice, stream), "alias reset input");
    };
'''
    replace('    const Snapshot multi = snapshot();\n    for (int t',
            '    const Snapshot multi = snapshot();\n'+reset+'    reset_input();\n    for (int t')
    replace('    check(cudaGraphLaunch(graph_exec, stream), "multi graph initial replay");',
            '    reset_input();\n    check(cudaGraphLaunch(graph_exec, stream), "multi graph initial replay");')
    replace('    for (int t = 0; t < T; ++t) fused_gr_read(args[t], stream);\n    check(cudaStreamSynchronize(stream), "changed single reference sync");',
            '    reset_input();\n    for (int t = 0; t < T; ++t) fused_gr_read(args[t], stream);\n    check(cudaStreamSynchronize(stream), "changed single reference sync");')
    replace('    // S26 STRATA_QFUSE:', '''    // Identical payload, identical captured pointers, independent reset each time.
    for (int repetition = 0; repetition < 3; ++repetition) {
        reset_input();
        check(cudaGraphLaunch(graph_exec, stream), "alias repeated graph");
        check(cudaStreamSynchronize(stream), "alias repeated sync");
        if (!same(replay, snapshot())) {
            std::printf("  repeated graph differs after input reset\\n");
            ++bad;
        }
    }
    // S26 STRATA_QFUSE:''')
    # The existing loop retains separate-buffer checks; add matching engine-alias cases.
    anchor='bad += fused_multi_lds_parity(dN, dD, dU, dJ, eps, window, false);'
    replace(anchor,'{ '+anchor+' bad += fused_multi_lds_parity(dN, dD, dU, dJ, eps, window, false, true); }')
    replace('  fused GR multi max-T=8 LDS launch and changing graph replay %s\\n',
            '  fused GR multi LDS launch and changing graph replay %s\\n')
    return text

if __name__=='__main__':
    source=ROOT/'output/research/source-hc-small-window-01403/src/kernels/gr_parity.cpp'
    original=source.read_text(encoding='utf-8')
    generated=prepare(original)
    directory=ROOT/'output/research/hc-alias-fixture-review'
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/'gr_parity.cpp'
    target.write_text(generated,encoding='utf-8')
    report=dict(scope='Prepared source only; not compiled or GPU executed',
        original_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        generated_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        candidate_source_unchanged=True,quarantine_retained=True,
        coverage=['T=1..6 separate and aliased buffers','Reset before independent scalar reference',
                  'Reset before initial captured replay','Changed inputs before graph replay and scalar reference',
                  'Three replays with identical payload and independent input reset',
                  'Tolerance comparison rejects NaN, infinity and mismatched vector sizes'],
        numerical_passed=None,root_cause_confirmed=False)
    (ROOT/'output/verification/hc-alias-fixture-prepared.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
