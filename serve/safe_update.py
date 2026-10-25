"""A safe update ladder: free resources, verify, validate, never activate silently.

Updating an integrated app is only safe when the running system is idle and the candidate
has been proved before it replaces anything. This module decides *whether* an update may run
and *what* has to happen first; it never activates anything by itself, because activation is
a separate action the user takes with the evidence in front of them.

The ladder, in order:
  1. pre-flight  - the engine, every harness and every generator must be idle
  2. reclaim     - stop the harnesses that are only idling, to free RAM for the check
  3. headroom    - enough free RAM for a bounded load, or the check would be killed mid-run
  4. stage       - the official asset, verified against the publisher's SHA-256
  5. prepare     - extracted into its own isolated directory, never over live code
  6. validate    - a bounded request first, then the full operating profile
  7. activate    - NOT performed here: it needs the validated proof and a separate decision
"""
from dataclasses import dataclass, field

READY = 'ready'
PREFLIGHT_FAILED = 'preflight_failed'
BLOCKED = 'blocked'

# Free RAM a bounded candidate load needs before the watchdog starts sampling.
HEADROOM_GIB = 10.0
# A harness that is only idling holds RAM with nobody using it.
RECLAIMABLE = ('idle', 'stopped', 'error')
KINDS = ('opencode', 'dsh', 'trueforge', 'hermes', 'claude')


@dataclass
class UpdatePlan:
    state: str = READY
    reason: str = ''
    reclaim: list = field(default_factory=list)
    components: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    activate: bool = False
    steps: list = field(default_factory=list)

    def as_dict(self):
        return {'state': self.state, 'reason': self.reason, 'reclaim': self.reclaim,
                'components': self.components, 'skipped': self.skipped,
                'activate': self.activate, 'steps': self.steps}


def _idle(state):
    return str(state or '').strip().lower() in ('idle', 'unloaded', 'stopped', 'none')


def plan_update(dashboard, headroom_gib=None, components=None, kinds=KINDS):
    """Decide whether an update may run now, and what must happen first."""
    plan = UpdatePlan()
    headroom = HEADROOM_GIB if headroom_gib is None else float(headroom_gib)

    engine = (getattr(dashboard, 'engine_state', lambda: None)()
              if hasattr(dashboard, 'engine_state') else None)
    backend = (getattr(dashboard, 'backend_state', lambda: None)()
               if hasattr(dashboard, 'backend_state') else None)
    if engine is None and hasattr(dashboard, 'engine'):
        engine = getattr(dashboard, 'engine')
    if backend is None and hasattr(dashboard, 'backend'):
        backend = getattr(dashboard, 'backend')

    # 1. pre-flight ---------------------------------------------------------
    if not _idle(engine):
        return UpdatePlan(state=PREFLIGHT_FAILED,
                          reason=f'il motore è "{engine}": scaricalo prima di aggiornare',
                          steps=['preflight'])
    if not _idle(backend):
        return UpdatePlan(state=PREFLIGHT_FAILED,
                          reason=f'il backend opzionale è "{backend}": disconnettilo prima di aggiornare',
                          steps=['preflight'])

    harnesses = getattr(dashboard, 'harnesses', {}) or {}
    busy = [kind for kind, harness in sorted(harnesses.items())
            if str((harness.status() or {}).get('status') or '').strip().lower() not in RECLAIMABLE
            and (harness.status() or {}).get('busy')]
    if busy:
        return UpdatePlan(state=PREFLIGHT_FAILED,
                          reason='agente occupato: ' + ', '.join(busy),
                          steps=['preflight'])

    # 2. reclaim ------------------------------------------------------------
    for kind in kinds:
        harness = harnesses.get(kind)
        if harness is None:
            continue
        state = (harness.status() or {})
        if str(state.get('status') or '').strip().lower() not in RECLAIMABLE:
            plan.reclaim.append(kind)

    # 3. headroom -----------------------------------------------------------
    if headroom < HEADROOM_GIB:
        return UpdatePlan(state=PREFLIGHT_FAILED,
                          reason=f'RAM libera {headroom:.1f} GiB sotto i {HEADROOM_GIB:.0f} GiB '
                                 'necessari alla verifica del candidato',
                          steps=['preflight', 'reclaim'])

    # 4. what to update -----------------------------------------------------
    for row in components or []:
        identifier = row.get('id')
        installed, available = row.get('installed_version'), row.get('version')
        if row.get('automatic_update_supported') is False:
            plan.skipped.append(f'{identifier}: aggiornamento automatico non supportato')
            continue
        if row.get('version_comparable') is False:
            plan.skipped.append(f'{identifier}: versione non confrontabile')
            continue
        if not installed or not available or installed == available:
            plan.skipped.append(f'{identifier}: già alla versione disponibile')
            continue
        if not (row.get('assets') or []):
            plan.skipped.append(f'{identifier}: nessun pacchetto verificabile')
            continue
        plan.components.append(identifier)

    plan.steps = ['preflight', 'reclaim', 'stage', 'prepare', 'validate']
    return plan
