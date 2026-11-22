"""GPU instantaneous throughput/power ratio, from contemporaneous samples only."""
import math

def capture(sample, at):
    speed, power = sample.get('tok_s'), sample.get('gpu_power')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in (speed,power)):
        return None
    return {'value':speed/power,'tok_s':speed,'power_w':power,'time':at}
