"""Logical memory tiers, not an allocator or hardware capability probe."""
from dataclasses import dataclass, asdict
from .disk_backing import describe_disk_backing


@dataclass(frozen=True)
class MemoryTier:
    name: str
    state: str
    available_bytes: int | None
    responsibility: str


def describe(config, resources=None):
    # Even when caller supplies observations, OFF does not inspect or allocate.
    active = config.enabled
    host = None if not active or resources is None else resources.host_available_bytes
    vram = None if not active or resources is None else resources.vram_available_bytes
    tiers = [MemoryTier('RAM', 'observed' if host is not None else 'unknown', host, 'backend allocation; engine admission only'),
             MemoryTier('VRAM', 'observed' if vram is not None else 'unknown', vram, 'backend allocation; no unified memory'),
             MemoryTier('NVMe', 'unavailable', None, 'model storage only; no engine staging or streaming'),
             MemoryTier('remote', 'unsupported', None, 'no transport or node discovery')]
    return dict(schema='hydra.hybrid.memory-tiers.v1', feature_enabled=active,
                disk_backing=describe_disk_backing(config),
                tiers=[asdict(t) for t in tiers], real_inference_verified=False,
                observations_source='caller supplied; authenticity/freshness not attested',
                paged_attention='unknown', prefix_caching='unknown')
