"""Validated static placement and admission budgets; no native imports."""
from dataclasses import dataclass, field, fields
import hashlib
import json
import math
from pathlib import Path
import tomllib
from urllib.parse import urlsplit

GiB = 1024 ** 3


@dataclass(frozen=True)
class Budget:
    host_limit_bytes: int = 32 * GiB
    host_reserve_bytes: int = 12 * GiB
    vram_limit_bytes: int = 20 * GiB
    request_bytes: int = 1024 * 1024
    output_bytes: int = 4 * 1024 * 1024
    vram_reserve_bytes: int = 0

    def __post_init__(self):
        for f in fields(self):
            if type(getattr(self, f.name)) is not int or getattr(self, f.name) < 0:
                raise ValueError('Invalid budget: ' + f.name)
        if not self.host_limit_bytes or not self.request_bytes or not self.output_bytes:
            raise ValueError('Nonzero host/request/output budgets required')


@dataclass(frozen=True)
class Resources:
    host_available_bytes: int | None = None
    vram_available_bytes: int | None = None
    cpu_available_threads: int | None = None

    def __post_init__(self):
        for value in (self.host_available_bytes, self.vram_available_bytes):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError('Invalid available resource measurement')
        if self.cpu_available_threads is not None and (type(self.cpu_available_threads) is not int or self.cpu_available_threads <= 0):
            raise ValueError('Positive observed CPU thread count required')


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    live_io_authorized: bool = False
    native_execution_authorized: bool = False
    remote: bool = False
    model: str = 'unset'
    binary: str = ''
    binary_sha256: str = ''
    backend_revision: str = ''
    model_path: str = ''
    model_sha256: str = ''
    backend_url: str = 'http://127.0.0.1:19291'
    threads: int = 8
    context: int = 2048
    max_concurrent: int = 1
    gpu_layers: int = 0
    host_required_bytes: int = GiB
    vram_required_bytes: int = 0
    request_memory_bytes: int = 256 * 1024 ** 2
    timeout_s: float = 60
    breaker_failures: int = 3
    budget: Budget = field(default_factory=Budget)
    request_vram_bytes: int = 0
    prompt_cache_policy: str = 'inherit'
    batch_size: int | None = None
    ubatch_size: int | None = None
    load_mode: str = 'inherit'
    speculative: str = 'none'
    lazy_mode: str = 'inherit'

    def __post_init__(self):
        if self.lazy_mode not in ('inherit', 'on', 'off'):
            raise ValueError('Explicit supported native lazy mode required')
        if self.lazy_mode == 'on' and self.load_mode != 'mmap':
            raise ValueError('Native lazy reads require explicit mmap loading')
        if self.prompt_cache_policy not in ('inherit', 'off', 'native'):
            raise ValueError('Invalid prompt cache policy')
        if self.load_mode not in ('inherit', 'mmap', 'none') or self.speculative not in ('none', 'ngram-simple'):
            raise ValueError('Unsupported native execution option')
        for value in (self.batch_size, self.ubatch_size):
            if value is not None and (type(value) is not int or not 1 <= value <= 65536):
                raise ValueError('Bounded native batch size required')
        if self.ubatch_size is not None and (self.batch_size is None or self.ubatch_size > self.batch_size):
            raise ValueError('Explicit logical batch >= microbatch required')
        for name in ('enabled', 'live_io_authorized', 'native_execution_authorized', 'remote'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('Boolean required: ' + name)
        if self.remote:
            raise ValueError('Remote node support unavailable')
        for name in ('threads', 'context', 'max_concurrent', 'breaker_failures'):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError('Positive integer required: ' + name)
        if self.threads > 256 or self.context > 1048576 or self.max_concurrent > 64:
            raise ValueError('Configuration outside software limits')
        for name in ('gpu_layers', 'host_required_bytes', 'vram_required_bytes', 'request_memory_bytes', 'request_vram_bytes'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError('Nonnegative integer required: ' + name)
        if type(self.timeout_s) not in (int, float) or not math.isfinite(self.timeout_s) or not 0 < self.timeout_s <= 600:
            raise ValueError('Timeout must be finite and 0..600 seconds')
        if not isinstance(self.budget, Budget):
            raise ValueError('Validated Budget required')
        for name in ('model', 'binary', 'binary_sha256', 'backend_revision', 'model_path', 'model_sha256', 'backend_url'):
            if not isinstance(getattr(self, name), str):
                raise ValueError('String required: ' + name)
        if not self.model or len(self.model) > 256:
            raise ValueError('Explicit bounded model identifier required')
        u = urlsplit(self.backend_url)
        if u.scheme != 'http' or u.hostname != '127.0.0.1' or u.username or u.password or u.query or u.fragment or u.path not in ('', '/'):
            raise ValueError('Only explicit IPv4 loopback HTTP endpoints supported')
        if u.port is None or not 1024 <= u.port <= 65535:
            raise ValueError('Explicit unprivileged backend port required')

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, dict) or set(value) - {f.name for f in fields(cls)}:
            raise ValueError('Unknown or invalid configuration fields')
        value = dict(value)
        if 'budget' in value:
            if not isinstance(value['budget'], dict):
                raise ValueError('Budget table required')
            try:
                value['budget'] = Budget(**value['budget'])
            except TypeError as exc:
                raise ValueError('Unknown budget field') from exc
        return cls(**value)

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 65536:
            raise ValueError('Configuration exceeds 64 KiB')
        return cls.from_mapping(tomllib.loads(path.read_text(encoding='utf-8')))


def host_resources():
    # Optional existing dependency; never imported in the default OFF path.
    try:
        import psutil
        import os
        count = os.cpu_count()
        try:
            count = len(psutil.Process().cpu_affinity())
        except (AttributeError, OSError, psutil.Error):
            pass
        return Resources(host_available_bytes=int(psutil.virtual_memory().available), cpu_available_threads=count)
    except ImportError:
        return Resources()


def static_profile(config):
    """Operator-declared placement identity, not a tokenizer/GGUF/hardware probe."""
    from dataclasses import asdict
    # Paths and local endpoints influence the fingerprint but are never exported.
    canonical = json.dumps(asdict(config), sort_keys=True, separators=(',', ':'), allow_nan=False)
    return dict(schema='hydra.hybrid.static-profile.v1',
                fingerprint=hashlib.sha256(canonical.encode()).hexdigest(),
                backend='llama.cpp', backend_revision=config.backend_revision or None,
                binary_sha256=config.binary_sha256 or None, model=config.model,
                model_sha256=config.model_sha256 or None, quantization='unknown',
                context_per_slot=config.context, slots=config.max_concurrent,
                threads=config.threads, gpu_layers=config.gpu_layers,
                memory_requirements_source='operator_estimates_not_measured',
                host_required_bytes=config.host_required_bytes,
                vram_required_bytes=config.vram_required_bytes,
                request_vram_bytes=config.request_vram_bytes,
                prompt_cache_policy=config.prompt_cache_policy,
                native_options=dict(batch_size=config.batch_size, ubatch_size=config.ubatch_size,
                                    load_mode=config.load_mode, speculative=config.speculative,
                                    lazy_mode=config.lazy_mode),
                budget=asdict(config.budget), performance='NOT_MEASURED')
