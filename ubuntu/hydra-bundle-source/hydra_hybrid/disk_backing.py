"""Backend-owned disk reads, not a second allocator or universal weight pager."""


def describe_disk_backing(config):
    requested = config.enabled and config.lazy_mode == 'on'
    return dict(
        schema='hydra.hybrid.disk-backing.v1',
        loading=config.load_mode,
        lazy_mode=config.lazy_mode,
        selective_tensor_reads='requested_not_observed' if requested else 'not_requested',
        tensor_eligibility='backend_and_model_dependent_not_verified',
        implementation_owner='native_backend',
        general_layer_weight_streaming='unsupported',
        engine_prefetch_eviction='unsupported',
        nvme_device_verified=False,
        physical_storage_bus=None,
        resident_bytes=None,
        disk_read_bytes=None,
        transfer_bytes=None,
        performance='NOT_MEASURED',
        note='mmap and lazy-mode can read eligible tensor rows; neither proves NVMe I/O or general layer streaming')
