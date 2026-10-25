"""Pure static feasibility selector. No reservations, fitting or dispatch."""
from .config import Config, Resources, static_profile


def select_static_profile(profiles, resources, *, preferred=None):
    if not isinstance(profiles, dict) or not profiles or not isinstance(resources, Resources):
        raise ValueError('Explicit profiles and resource snapshot required')
    if any(not isinstance(name,str) or not name or not isinstance(c,Config) for name,c in profiles.items()):
        raise ValueError('Named validated Config profiles required')
    if preferred is not None and preferred not in profiles:
        raise ValueError('Preferred profile not present')
    rejected={};eligible=[]
    for name,c in profiles.items():
        reason=None;host=c.host_required_bytes+c.request_memory_bytes
        if not c.enabled:reason='disabled'
        elif resources.host_available_bytes is None:reason='unknown_host_memory'
        elif host>c.budget.host_limit_bytes:reason='host_budget'
        elif host+c.budget.host_reserve_bytes>resources.host_available_bytes:reason='host_reserve'
        elif resources.cpu_available_threads is not None and c.threads>resources.cpu_available_threads:reason='cpu_threads'
        elif c.gpu_layers:
            vram=c.vram_required_bytes+c.request_vram_bytes+c.budget.vram_reserve_bytes
            if not c.vram_required_bytes or resources.vram_available_bytes is None:reason='unknown_vram'
            elif vram>min(c.budget.vram_limit_bytes,resources.vram_available_bytes):reason='vram_budget'
        if reason:rejected[name]=reason
        else:eligible.append(name)
    chosen=preferred if preferred in eligible else (eligible[0] if eligible else None)
    return dict(schema='hydra.hybrid.static-selection.v1',selected=chosen,rejected=rejected,
                eligible=eligible,profile=None if chosen is None else static_profile(profiles[chosen]),
                reason='explicit_preference_or_insertion_order_among_feasible_profiles',
                reserved=False,adaptive=False,performance='NOT_MEASURED',
                note='Snapshot only; Engine revalidates resources and owns admission. No dispatch or runtime identity attestation.')


def create_static_engine(profiles, backend_factories, resource_provider, *, preferred=None):
    """Operational startup selection, not per-token scheduling or fallback."""
    from .core import Engine, ResourceDenied
    if not callable(resource_provider) or not isinstance(backend_factories, dict):
        raise ValueError('Resource provider and explicit backend factories required')
    if set(backend_factories) != set(profiles) or any(not callable(f) for f in backend_factories.values()):
        raise ValueError('Exactly one lazy backend factory per static profile required')
    decision = select_static_profile(profiles, resource_provider(), preferred=preferred)
    name = decision['selected']
    if name is None:
        raise ResourceDenied('No admissible static profile: '+str(decision['rejected']))
    # Engine alone admits and reserves later; snapshot feasibility is not a lease.
    return Engine(profiles[name], backend_factories[name], resource_provider), decision
