"""Owned HYDRA memory reservations, inside the existing exclusive coordinator.

Reservations describe enforced upper bounds, not disk sizes or physical free
memory. The coordinator's private Job enforces RAM commit for child processes.
No GPU backend currently supplies a complete enforceable VRAM contract.
"""
from copy import deepcopy
import threading
import uuid

MAX_BYTES = 2**63 - 1
DOMAINS = ('ram', 'vram')
COMPONENTS = ('weights', 'expert_cache', 'sequence_state', 'kv_cache',
              'workspace', 'staging', 'runtime_buffers', 'safety_margin')


class BudgetError(ValueError):
    pass


def byte_count(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_BYTES:
        raise BudgetError('VERIFIED_MEMORY_BOUND_REQUIRED')
    return value


def checked_sum(values):
    total = 0
    for value in values:
        value = byte_count(value)
        if value > MAX_BYTES - total:
            raise BudgetError('MEMORY_BUDGET_OVERFLOW')
        total += value
    return total


def component_totals(plan):
    if not isinstance(plan, dict) or set(plan) != set(DOMAINS):
        raise BudgetError('SEPARATE_RAM_VRAM_PLAN_REQUIRED')
    totals = {}
    for domain in DOMAINS:
        rows = plan[domain]
        if not isinstance(rows, dict) or set(rows) != set(COMPONENTS):
            raise BudgetError(domain + ':COMPLETE_COMPONENTS_REQUIRED')
        totals[domain] = checked_sum(rows.values())
    return totals


class MemoryBudget:
    """One ledger shared by owners; subclaims consume an existing envelope.

    All methods serialize under one lock. A missing bound never becomes zero.
    Failed cleanup retains reservations. Destruction does not release anything.
    Cross-process exclusion remains the existing named coordinator mutex/Job;
    this object is not an independent process admission mechanism.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._owners = {}
        self._used = dict.fromkeys(DOMAINS, 0)

    def reserve(self, owner, plan, limits, available):
        totals = component_totals(plan)
        if not isinstance(limits, dict) or set(limits) != set(DOMAINS):
            raise BudgetError('ENFORCEABLE_RAM_VRAM_LIMITS_REQUIRED')
        if not isinstance(available, dict) or set(available) != set(DOMAINS):
            raise BudgetError('CURRENT_RAM_VRAM_AVAILABILITY_REQUIRED')
        if not isinstance(owner, str) or not owner:
            raise BudgetError('MEMORY_OWNER_REQUIRED')
        with self._lock:
            if owner in self._owners:
                raise BudgetError('MEMORY_OWNER_ALREADY_RESERVED')
            for domain in DOMAINS:
                limit = byte_count(limits.get(domain), positive=True)
                free = byte_count(available.get(domain))
                wanted = checked_sum((self._used[domain], totals[domain]))
                if wanted > limit or wanted > free:
                    raise BudgetError(domain + ':MEMORY_RESERVATION_EXCEEDED')
            token = uuid.uuid4().hex
            self._owners[owner] = dict(token=token, plan=deepcopy(plan), totals=totals,
                                       claims={}, attached=False)
            for domain in DOMAINS:
                self._used[domain] += totals[domain]
            return MemoryLease(self, owner, token)

    def _row(self, lease):
        row = self._owners.get(lease.owner)
        if row is None or row['token'] != lease._token:
            raise BudgetError('STALE_MEMORY_LEASE')
        return row

    def snapshot(self):
        with self._lock:
            owners = {name: {k: v for k, v in row.items() if k != 'token'}
                      for name, row in self._owners.items()}
            return deepcopy(dict(reserved=self._used, owners=owners))


class MemoryLease:
    def __init__(self, manager, owner, token):
        self._manager, self.owner, self._token = manager, owner, token

    def __copy__(self):
        raise BudgetError('MEMORY_LEASE_NOT_COPYABLE')

    def __deepcopy__(self, memo):
        raise BudgetError('MEMORY_LEASE_NOT_COPYABLE')

    def attach(self):
        with self._manager._lock:
            row = self._manager._row(self)
            if row['attached']:
                raise BudgetError('MEMORY_LEASE_ALREADY_ATTACHED')
            row['attached'] = True

    def native_environment(self):
        """Export suballocation ceilings, not a second global reservation.

        The private Job still enforces the outer RAM commit envelope. Current
        adapters cannot enforce external GPU library allocations, so a nonzero
        VRAM envelope cannot be handed to a child by this interface.
        """
        with self._manager._lock:
            row = self._manager._row(self)
            if not row['attached']:
                raise BudgetError('NATIVE_MEMORY_OWNER_NOT_ATTACHED')
            if row['totals']['vram']:
                raise BudgetError('NATIVE_EXTERNAL_VRAM_CONTRACT_REQUIRED')
            values = [row['plan'][d][c] for d in DOMAINS for c in COMPONENTS]
            return dict(HYDRA_MEMORY_OWNER=self.owner,
                        HYDRA_NATIVE_MEMORY_ENVELOPE=';'.join(map(str, values)))

    def claim(self, domain, component, allocation_id, size):
        """Reserve inside the process envelope before an owned allocation.

        The outer reservation is already counted: claims are never added to
        global totals again. The identity must remain live until completion.
        """
        size = byte_count(size, positive=True)
        if domain not in DOMAINS or component not in COMPONENTS:
            raise BudgetError('MEMORY_COMPONENT_REQUIRED')
        if not isinstance(allocation_id, str) or not allocation_id:
            raise BudgetError('ALLOCATION_ID_REQUIRED')
        with self._manager._lock:
            row = self._manager._row(self)
            if allocation_id in row['claims']:
                raise BudgetError('ALLOCATION_ALREADY_RESERVED')
            used = checked_sum(c['bytes'] for c in row['claims'].values()
                               if c['domain'] == domain and c['component'] == component)
            if checked_sum((used, size)) > row['plan'][domain][component]:
                raise BudgetError('COMPONENT_MEMORY_LIMIT_EXCEEDED')
            row['claims'][allocation_id] = dict(domain=domain, component=component, bytes=size)

    def finish_claim(self, allocation_id, completion):
        # completion must be a backend-owned callable that attests both operation
        # termination and buffer cleanup. Exceptions retain the claim.
        with self._manager._lock:
            row = self._manager._row(self)
            if allocation_id not in row['claims']:
                raise BudgetError('ALLOCATION_NOT_RESERVED')
            if not callable(completion) or completion() is not True:
                raise BudgetError('ALLOCATION_COMPLETION_UNATTESTED')
            del row['claims'][allocation_id]

    def release(self, cleanup):
        with self._manager._lock:
            row = self._manager._row(self)
            if not callable(cleanup) or cleanup() is not True:
                raise BudgetError('MEMORY_CLEANUP_UNATTESTED')
            # Whole process termination attests all of its child allocations.
            # An unattached envelope can only be rolled back before any claims.
            if not row['attached'] and row['claims']:
                raise BudgetError('MEMORY_CLAIMS_STILL_OWNED')
            for domain in DOMAINS:
                self._manager._used[domain] -= row['totals'][domain]
            del self._manager._owners[self.owner]


SHARED_MEMORY_BUDGET = MemoryBudget()


def reserve_job_commit(owner, limit, available_ram, components=None):
    """Actual Windows Job commit envelope; not a native MoE/RSS admission.

    Components are charged to one process envelope, avoiding double counting.
    VRAM is zero because this function grants no GPU allocation capability.
    """
    limit = byte_count(limit, positive=True)
    plan = {d: dict.fromkeys(COMPONENTS, 0) for d in DOMAINS}
    plan['ram']['runtime_buffers'] = limit
    if components is not None:
        totals = component_totals(components)
        if totals['ram'] != limit or totals['vram'] != 0:
            raise BudgetError('JOB_COMPONENT_ENVELOPE_MISMATCH_OR_VRAM_UNENFORCED')
        plan = deepcopy(components)
    return SHARED_MEMORY_BUDGET.reserve(owner, plan,
        dict(ram=128 * 1024**3, vram=1), dict(ram=available_ram, vram=0))
