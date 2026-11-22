"""One bounded 64x64 matrix operation; no model or stress campaign."""
import json
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
report = {'passed': False, 'scope': 'One 64x64 GPU matrix operation; not a stability or throughput certificate',
          'started_at': time.time()}
try:
    import torch
    report.update(torch_version=torch.__version__, hip_version=torch.version.hip,
                  available=torch.cuda.is_available())
    if not torch.cuda.is_available() or not torch.version.hip:
        raise RuntimeError('AMD HIP device is not available')
    report['device'] = torch.cuda.get_device_name(0)
    a = torch.arange(4096, dtype=torch.float32).reshape(64, 64) / 4096
    expected = a @ a.T
    actual = (a.cuda() @ a.T.cuda()).cpu()
    torch.cuda.synchronize()
    report['max_absolute_error'] = float((actual - expected).abs().max())
    report['passed'] = bool(torch.allclose(actual, expected, rtol=1e-4, atol=1e-4))
    report['peak_allocated_bytes'] = torch.cuda.max_memory_allocated()
    if not report['passed']:
        raise RuntimeError('GPU calculation differs from the CPU reference')
except Exception as error:
    report['error'] = str(error)
finally:
    report['finished_at'] = time.time()
    (root / 'output/verification/amd-gpu-bounded-probe.json').write_text(
        json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
raise SystemExit(0 if report['passed'] else 1)
