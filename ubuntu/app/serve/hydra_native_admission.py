"""Fail-closed native MoE preflight. Static evidence never grants execution.

RAM/VRAM are distinct domains. A numerical upper bound is not a measurement of
future availability, and caller metadata cannot attest a native runtime build.
"""
import hashlib
import json
from pathlib import Path
from serve.hydra_memory_budget import COMPONENTS, MAX_BYTES, SHARED_MEMORY_BUDGET

V25_INVENTORY_SHA256 = '15c9966c8d57d2f76f6128f11c2264476da0ef824ab315f0d58df5b4ba84d305'

# Exact local build receipts, not a caller-supplied execution allowlist. These
# hashes bind the native target only; the separate Prism overlay is not linked.
SOURCE_BOUND_V32 = dict(
    directory='HYDRA/engine_link_v32_20261020',
    binary_sha256='29bb07fe2d083fccf6993ba9e40ac6f2a5df5a35dc97d1926ecb161494b20946',
    receipts={
        'candidate-manifest.json':'b131ae0f0687b4d24cbd611337d265c7f8569ab9f75e0045a6038ea4c3274f6e',
        'source-inputs.json':'95375ebe5f089ea68f941dc38e5b379685d9302aedbe3b1ba5cef3c4cfa02149',
        'build-bd3c84dd0e/result.json':'a71a579e5bd029a58bc49510e8e86424d9242f19f5973fa804498e021e661651',
    })

SOURCE_BOUND_V36 = dict(
    directory='HYDRA/engine_build_v36', candidate='link-44a6a882db79/strata.exe',
    binary_sha256='2d8106b999bcd470fe9293ea27721b0fde6d7c0d269de45baa95d31ab88e1d35',
    receipts={
        'build-ab153de5b3d1/result.json':'ea0ed6a11b45362d792da8726b17cc28aad72a8eb63ac2393ba5d709ef3746e1',
        'link-44a6a882db79/result.json':'ef095d69936018d474454dcc490537e32cf3cf0552087ef96efe9375a24adb02',
    })


def _inspect_incremental_runtime(root, selected):
    """Consume exact incremental compile/archive/link receipts in the same resolver."""
    spec = SOURCE_BOUND_V36
    delivery = project_path(root.parent / spec['directory'], root.parent)
    candidate = project_path(delivery / spec['candidate'], root.parent)
    if selected != candidate:
        raise ValueError('SOURCE_BUILD_RUNTIME_PATH_MISMATCH')
    receipts = []
    for name, expected in spec['receipts'].items():
        path = project_path(delivery / name, root.parent)
        if path.stat().st_size > 16 * 1024**2:
            raise ValueError('SOURCE_BUILD_PROVENANCE_SIZE')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('SOURCE_BUILD_PROVENANCE_CHANGED: ' + name)
        receipts.append(json.loads(raw))
    build, link = receipts
    if (any(row.get('status') != 'PASS' or row.get('cleanup') is not True for row in receipts) or
        build.get('sources_unchanged') is not True or link.get('sources_unchanged') is not True or
        link.get('protected_unchanged') is not True or link.get('exit_code') != 0 or
        build.get('target') != 'strata_prefill' or
        any(step.get('exit_code') != 0 for step in build.get('steps', [])) or
        link.get('compile_receipt_sha256') != next(iter(spec['receipts'].values())) or
        link.get('archive_receipt_sha256') != next(iter(spec['receipts'].values()))):
        raise ValueError('SOURCE_BUILD_RECEIPT_INCONSISTENT')
    sources = link.get('sources')
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 4096 or build.get('inputs') != sources:
        raise ValueError('SOURCE_BUILD_SOURCE_SET_REQUIRED')
    for name, expected in sources.items():
        path = project_path(name, root.parent)
        if path.stat().st_size > 16 * 1024**2 or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('SOURCE_BUILD_SOURCE_CHANGED: ' + name)
    library = project_path(build['library']['path'], delivery)
    compiler = project_path(link['command'][0], root)
    for path, expected, maximum in (
        (library, build['library']['sha256'], 256 * 1024**2),
        (compiler, link['compiler_sha256'], 512 * 1024**2),
        (candidate, spec['binary_sha256'], 256 * 1024**2),
    ):
        if path.stat().st_size > maximum:
            raise ValueError('SOURCE_BUILD_ARTIFACT_SIZE')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise ValueError('SOURCE_BUILD_ARTIFACT_CHANGED: ' + str(path))
    return dict(status='SOURCE_BOUND_PENDING_RUNTIME_ATTESTATION',
                reason='NATIVE_MOE_RUNTIME_EXECUTION_ATTESTATION_REQUIRED',
                selected=str(selected), sha256=spec['binary_sha256'], backend='HIP gfx1100',
                sources_verified=len(sources), automatic_fallback=False,
                execution_enabled=False, dependency_loading_verified=False)


def inspect_source_bound_runtime(root, selected):
    """Verify the linked local candidate, without selecting or executing it.

    Recheck the small source set: build success is not a binding to subsequently
    edited native sources. DLL loading, driver allocation and inference remain
    separate attestations and cannot be inferred from these build receipts.
    """
    root = Path(root).absolute()
    try:
        selected = project_path(selected, root.parent)
        incremental = root.parent / SOURCE_BOUND_V36['directory'] / SOURCE_BOUND_V36['candidate']
        if selected == incremental:
            return _inspect_incremental_runtime(root, selected)
        delivery = project_path(root.parent / SOURCE_BOUND_V32['directory'], root.parent)
        candidate = project_path(delivery / 'candidate-source-bound/strata.exe', root.parent)
        if selected != candidate:
            raise ValueError('SOURCE_BUILD_RUNTIME_PATH_MISMATCH')
        receipts = {}
        for name, expected in SOURCE_BOUND_V32['receipts'].items():
            path = project_path(delivery / name, root.parent)
            if path.stat().st_size > 16 * 1024**2:
                raise ValueError('SOURCE_BUILD_PROVENANCE_SIZE')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('SOURCE_BUILD_PROVENANCE_CHANGED: ' + name)
            receipts[name] = json.loads(raw)
        manifest = receipts['candidate-manifest.json']
        result = receipts['build-bd3c84dd0e/result.json']
        sources = receipts['source-inputs.json']
        if (manifest.get('kind') != 'FULL_NATIVE_HIP_BUILD_AND_LINK_ONLY' or
            manifest.get('backend') != 'HIP gfx1100' or
            manifest.get('runtime_sha256') != SOURCE_BOUND_V32['binary_sha256'] or
            result.get('exit_code') != 0 or result.get('cleanup') is not True or
            result.get('sources_unchanged') is not True):
            raise ValueError('SOURCE_BUILD_RECEIPT_INCONSISTENT')
        if not isinstance(sources, dict) or not 1 <= len(sources) <= 4096:
            raise ValueError('SOURCE_BUILD_SOURCE_SET_REQUIRED')
        for name, expected in sources.items():
            path = project_path(name, root.parent)
            if path.stat().st_size > 16 * 1024**2:
                raise ValueError('SOURCE_BUILD_SOURCE_SIZE')
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('SOURCE_BUILD_SOURCE_CHANGED: ' + name)
        for name, expected in (
            ('build/compile_commands.json', manifest.get('compile_commands_sha256')),
            ('build/CMakeCache.txt', manifest.get('cmake_cache_sha256')),
        ):
            path = project_path(delivery / name, root.parent)
            if path.stat().st_size > 16 * 1024**2 or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('SOURCE_BUILD_CONFIGURATION_CHANGED: ' + name)
        if candidate.stat().st_size > 256 * 1024**2:
            raise ValueError('SOURCE_BUILD_RUNTIME_SIZE')
        with candidate.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != SOURCE_BOUND_V32['binary_sha256']:
            raise ValueError('SOURCE_BUILD_RUNTIME_CHANGED')
        return dict(status='SOURCE_BOUND_PENDING_RUNTIME_ATTESTATION',
                    reason='NATIVE_MOE_RUNTIME_EXECUTION_ATTESTATION_REQUIRED',
                    selected=str(selected), sha256=actual, backend=manifest['backend'],
                    sources_verified=len(sources), automatic_fallback=False,
                    execution_enabled=False, dependency_loading_verified=False)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return dict(status='BLOCKED', reason='SOURCE_BOUND_RUNTIME_IDENTITY_REQUIRED',
                    detail=str(exc), automatic_fallback=False, execution_enabled=False)


def memory_admission(plan, limits, available):
    """Validate already enforced bounds; never infer residency from disk size."""
    reasons, totals, known = [], {}, {}
    for domain in ('ram', 'vram'):
        rows = plan.get(domain) if isinstance(plan, dict) else None
        if not isinstance(rows, dict) or set(rows) != set(COMPONENTS):
            reasons.append(domain + ':COMPLETE_COMPONENTS_REQUIRED')
            continue
        total, complete = 0, True
        for name, size in rows.items():
            if type(size) is not int or not 0 <= size <= MAX_BYTES:
                complete = False
                reasons.append(domain + ':' + name + ':VERIFIED_UPPER_BOUND_REQUIRED')
            elif size > MAX_BYTES - total:
                complete = False
                reasons.append(domain + ':OVERFLOW')
            else:
                total += size
        known[domain] = total
        totals[domain] = total if complete else None
        limit = limits.get(domain) if isinstance(limits, dict) else None
        free = available.get(domain) if isinstance(available, dict) else None
        if type(limit) is not int or not 0 < limit <= MAX_BYTES:
            reasons.append(domain + ':ENFORCEABLE_LIMIT_REQUIRED')
        elif total > limit:
            reasons.append(domain + ':BUDGET_EXCEEDED')
        if type(free) is not int or not 0 <= free <= MAX_BYTES:
            reasons.append(domain + ':CURRENT_AVAILABILITY_REQUIRED')
        elif total > free:
            reasons.append(domain + ':AVAILABLE_MEMORY_EXCEEDED')
    return dict(status='BLOCKED' if reasons else 'BOUNDED_METADATA_ONLY',
                totals=totals, partial_known_bytes=known, reasons=reasons,
                execution_enabled=False)


def project_path(value, root):
    """Reject external/network/reparse paths before resolving or opening them."""
    import os
    root = Path(root).absolute()
    path = Path(value)
    if str(value).startswith(('\\\\', '//')) or not path.is_absolute():
        raise ValueError('NATIVE_MOE_LOCAL_ABSOLUTE_PATH_REQUIRED')
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root):
        raise ValueError('NATIVE_MOE_ASSET_OUTSIDE_PROJECT')
    for node in (path, *path.parents):
        if node == root.parent:
            break
        stat = node.lstat()
        if node.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
            raise ValueError('NATIVE_MOE_REPARSE_PATH_REFUSED')
    return path


def native_preflight(root):
    """Bind the sealed v25 asset snapshot to the current local selection.

    Large unchanged artifacts reuse v25 SHA identities with size/mtime checks.
    This is freshness evidence for a blocked target, never execution admission.
    Source dependencies are deliberately excluded from the frozen asset set:
    v26 changes sources and does not pretend they match the prebuilt binary.
    """
    root = Path(root).absolute()
    blockers = ['NATIVE_MOE_RUNTIME_SOURCE_BINDING_REQUIRED',
                'NATIVE_MOE_COMPLETE_RAM_VRAM_UPPER_BOUND_REQUIRED']
    assets, error = [], None
    try:
        inventory = project_path(root.parent / 'HYDRA/native_moe_static_v25/inventory.json', root.parent)
        if inventory.stat().st_size > 1024**2:
            raise ValueError('NATIVE_MOE_INVENTORY_SIZE')
        raw = inventory.read_bytes()
        if hashlib.sha256(raw).hexdigest() != V25_INVENTORY_SHA256:
            raise ValueError('NATIVE_MOE_SEALED_INVENTORY_CHANGED')
        for row in json.loads(raw):
            if row['role'] == 'source dependency':
                continue
            path = project_path(row['absolute_path'], root.parent)
            stat = path.stat()
            if stat.st_size != row['bytes'] or ('mtime_ns' in row and stat.st_mtime_ns != row['mtime_ns']):
                raise ValueError('NATIVE_MOE_ASSET_CHANGED: ' + row['path'])
            if stat.st_size <= 16 * 1024**2:
                if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                    raise ValueError('NATIVE_MOE_METADATA_IDENTITY_CHANGED: ' + row['path'])
            assets.append(dict(path=row['path'], sha256=row['sha256'], bytes=row['bytes']))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        error = str(exc)
        blockers.insert(0, 'NATIVE_MOE_ASSET_IDENTITY_REQUIRED')
    # No aggregate bound is asserted: these partial payloads cannot cover the
    # native dense/head, MTP, prefill workspace and driver/runtime allocations.
    plan = {d: {name: None for name in COMPONENTS} for d in ('ram', 'vram')}
    plan['ram'].update(expert_cache=16 * 1024**3, kv_cache=1660944384,
                       sequence_state=117669888, safety_margin=4 * 1024**3)
    plan['vram'].update(kv_cache=415236096, safety_margin=1536 * 1024**2)
    budget = memory_admission(plan, None, None)
    runtime = runtime_provenance(root)
    if runtime['status'] == 'SOURCE_BOUND_PENDING_RUNTIME_ATTESTATION':
        blockers.remove('NATIVE_MOE_RUNTIME_SOURCE_BINDING_REQUIRED')
        blockers.insert(0, runtime['reason'])
    if runtime['status'] == 'BLOCKED':
        blockers.insert(0, runtime['reason'])
    return dict(target='hf_85a248b2_q2_0', status='BLOCKED', execution_enabled=False,
                blockers=blockers, dependency=blockers[0], assets=assets,
                identity_error=error, memory=budget, component_bounds=plan,
                runtime_provenance=runtime,
                owned_memory=SHARED_MEMORY_BUDGET.snapshot(),
                future_availability_check_required=True,
                scope='No runtime, device, network, weight parser or model is invoked')


def require_native_moe(root):
    from serve.hydra_capability_contracts import CapabilityError
    row = native_preflight(root)
    raise CapabilityError('; '.join(row['blockers']))


def guard_owned_launch(root, argv, request=None, environment=None):
    """Gate the actual resolved command, including equals-form arguments.

    Mandatory even without FCC persistence. No backend is selected here and
    ordinary CPU commands do not inherit the native MoE dependency block.
    """
    from serve.hydra_capability_contracts import CapabilityError, BLOCKERS, guard_request
    if not isinstance(argv, (tuple, list)) or not argv or not all(isinstance(v, str) for v in argv):
        raise CapabilityError('RESOLVED_LAUNCH_ARGUMENTS_REQUIRED')
    if request is not None:
        guard_request(request)
    normalized = []
    for value in argv:
        if value.startswith('--') and '=' in value:
            normalized.extend(value.split('=', 1))
        else:
            normalized.append(value)
    labels = [value.casefold() for value in normalized]
    executable = Path(normalized[0]).stem.casefold()
    if ('--pack' in normalized and '--native' in normalized) or any('hf_85a248b2_q2_0' in value for value in labels):
        require_native_moe(root)
    if any('colibri' in value and ('35b' in value or 'full' in value) for value in labels):
        raise CapabilityError(BLOCKERS['full35b'])
    if any(flag in normalized for flag in ('--model-draft', '--spec-draft-model', '-md')) or (
            ('llama' in executable or 'prism' in executable) and
            isinstance(environment, dict) and environment.get('LLAMA_ARG_SPEC_DRAFT_MODEL')):
        raise CapabilityError(BLOCKERS['speculative'])


def runtime_provenance(root):
    """Bind the actual configured runtime, never substitute the v26 candidate.

    This consumes the existing delivery identities. A historical source-bound
    candidate is not a build of later overlays, nor execution authorization.
    """
    root = Path(root).absolute()
    try:
        config = project_path(root / 'strata-hf_85a248b2_q2_0.json', root.parent)
        if config.stat().st_size > 65536:
            raise ValueError('RUNTIME_METADATA_SIZE')
        selected = project_path(json.loads(config.read_text(encoding='utf8'))['exe'], root.parent)
        linked = root.parent / SOURCE_BOUND_V32['directory'] / 'candidate-source-bound/strata.exe'
        incremental = root.parent / SOURCE_BOUND_V36['directory'] / SOURCE_BOUND_V36['candidate']
        if selected in (linked, incremental):
            return inspect_source_bound_runtime(root, selected)
        evidence = project_path(root.parent / 'HYDRA/engine_completion_v27/candidate-status-v27.json', root.parent)
        if evidence.stat().st_size > 1024**2:
            raise ValueError('RUNTIME_METADATA_SIZE')
        prior = json.loads(evidence.read_text(encoding='utf8'))
        candidate = project_path(prior['candidate'], root.parent)
        expected = '5403aedb47626d97d362f053c6e1def8dd4471de05d23bf8d70416a6f3117e42'
        if prior.get('sha256') != expected or prior.get('selected') is not False:
            raise ValueError('CANDIDATE_DELIVERY_IDENTITY_MISMATCH')
        provenance = prior.get('baseline_provenance')
        required = ('hip-source-build-inputs.json', 'hip-source-build-result.json',
                    'hip-actual-dependency-sha256.json', 'runtime-provenance-v26.json')
        if not isinstance(provenance, dict) or set(provenance) != set(required):
            raise ValueError('SOURCE_BUILD_PROVENANCE_REQUIRED')
        for name in required:
            path = project_path(root.parent / 'HYDRA/engine_completion_v26' / name, root.parent)
            if path.stat().st_size > 16 * 1024**2:
                raise ValueError('SOURCE_BUILD_PROVENANCE_SIZE')
            if hashlib.sha256(path.read_bytes()).hexdigest() != provenance[name]:
                raise ValueError('SOURCE_BUILD_PROVENANCE_CHANGED')
        # Only this exact historical artifact can carry the v26 source mapping.
        # No other executable inherits it from a filename or version label.
        reason = ('V26_CANDIDATE_NOT_BOUND_TO_CURRENT_SOURCE_OVERLAY' if selected == candidate
                  else 'SELECTED_PREBUILT_BINARY_TO_SOURCE_MAPPING_REQUIRED')
        return dict(status='BLOCKED', reason=reason, selected=str(selected),
                    historical_candidate=str(candidate), historical_sha256=expected,
                    source_build_manifests=provenance, automatic_fallback=False,
                    execution_enabled=False)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return dict(status='BLOCKED', reason='RUNTIME_PROVENANCE_REQUIRED',
                    detail=str(exc), automatic_fallback=False, execution_enabled=False)
