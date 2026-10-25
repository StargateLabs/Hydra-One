"""Benchmark summaries only. No benchmark/inference execution entry point."""
import math


def percentile(values, q):
    values = sorted(values)
    return values[max(0, math.ceil(q * len(values)) - 1)] if values else None


def summarize(rows):
    completed = [row for row in rows if row.get('outcome') == 'completed']
    walls = [r['wall_s'] for r in completed]
    first = [r['ttft_s'] for r in completed if r.get('ttft_s') is not None]
    for value in walls + first:
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('Finite nonnegative measured durations required')
    if any(r.get('ttft_s') is not None and r['ttft_s'] > r['wall_s'] for r in completed):
        raise ValueError('TTFT exceeds request duration')
    return dict(requests=len(rows), completed=len(completed), errors=len(rows)-len(completed),
        quantile_method='nearest_rank_descriptive', tail_estimate_robust=False,
        latency_p50_s=percentile(walls, .5), latency_p95_s=percentile(walls, .95),
        ttft_p50_s=percentile(first, .5), ttft_p95_s=percentile(first, .95),
        decode_tokens_per_s=None, ram_peak_bytes=None, vram_peak_bytes=None,
        tier_transfer_bytes=None, bandwidth_bytes_per_s=None,
        note='Token counts and hardware quantities unavailable unless independently measured; no synthetic calibration')
