"""Measured startup stages from engine logs, never inferred disk timings."""
import math,re
from pathlib import Path

def snapshot(path,total_s=None,offset=0):
    if not path:return None
    try:
        with Path(path).open('rb') as source:
            source.seek(0,2);end=source.tell();source.seek(max(int(offset),end-262144));text=source.read().decode('utf-8','replace')
    except OSError:return None
    phases=[]
    gpu=list(re.finditer(r'pre-filled (\d+) of \d+ slots .*? in ([\d.]+) s',text))
    ram=list(re.finditer(r'mapped pinned cache complement ready: resident ([\d.]+) GiB.*? in ([\d.]+) s',text))
    cache=list(re.finditer(r'expert cache (\d+) slots, ([\d.]+) GiB of VRAM',text))
    if gpu:
        match=gpu[-1];seconds=float(match[2]);gib=float(cache[-1][2]) if cache else None
        if math.isfinite(seconds) and seconds>=0:phases.append(dict(key='gpu',seconds=seconds,gib=gib,source='Engine profile fill timer; includes source reads and GPU upload'))
    if ram:
        match=ram[-1];seconds=float(match[2])
        if math.isfinite(seconds) and seconds>=0:phases.append(dict(key='ram',seconds=seconds,gib=float(match[1]),source='Engine resident cache timer; includes reads, copying and host mapping'))
    if not phases:return None
    return dict(phases=phases,total_s=total_s if isinstance(total_s,(int,float)) and math.isfinite(total_s) and total_s>=0 else None,
                disk_separately_measured=False,scope='Last engine startup; cache-stage timers include disk reads. Stages are not summed into total startup time.')
