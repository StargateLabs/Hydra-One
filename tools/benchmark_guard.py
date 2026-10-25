"""Validate actual answers before a benchmark may send its next request."""
import math

def require_startup_vram_margin(engine, minimum_mib=1536):
    free = engine.get('vram_free_mib')
    if (isinstance(free, bool) or not isinstance(free, (int, float))
        or not math.isfinite(free) or free < minimum_mib):
        raise RuntimeError('Insufficient or unavailable startup VRAM margin; no prompts submitted')
    return free

def require_completed(record):
    rate = record.get('engine_decode_tps')
    count = record.get('completion_tokens')
    if (record.get('error') or isinstance(count, bool) or not isinstance(count, int)
        or count <= 0 or not record.get('answer_head')
        or isinstance(rate, bool) or not isinstance(rate, (float, int))
        or not math.isfinite(rate) or rate <= 0):
        raise RuntimeError('Benchmark interrupted: request failed or has no valid answer/timing')
    return record

def require_run_result(result):
    record, checkpoint = result
    require_completed(record)
    return record, checkpoint
