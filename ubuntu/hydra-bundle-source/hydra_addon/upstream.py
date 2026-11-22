"""Explicit local service attachment, including native Strata disk-tier engines."""
import http.client
import json
from urllib.parse import urlsplit
from hydra_hybrid.backend import HydraAdapter


class ServiceAdapter(HydraAdapter):
    def __init__(self,config,*,resources=None):
        self.service_prepared=False
        def transport():
            if not self.service_prepared:
                raise RuntimeError('Local service model discovery required before transport')
            from hydra_lab.adapters import LocalHTTPAdapter
            return LocalHTTPAdapter(config.backend_url,config.timeout_s)
        super().__init__(config,resources=resources,transport_factory=transport)

    def prepare(self):
        # Config already restricts the origin to literal loopback; no model loading.
        parsed = urlsplit(self.engine.config.backend_url)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        try:
            connection.request('GET', '/v1/models')
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 1024 * 1024:
                raise ValueError('Local service model discovery unavailable')
            data = json.loads(raw)
            rows = data.get('data')
            if not isinstance(rows, list) or not any(isinstance(r, dict) and r.get('id') == self.engine.config.model for r in rows):
                raise ValueError('Requested model not advertised by local service')
            self.service_prepared=True
            return dict(state='prepared', source='observed_local_models_api', backend_binary_identity='unknown',
                        tensor_architecture='backend_owned_not_verified', model=self.engine.config.model,
                        model_files_verified=False, physical_nvme_verified=False)
        finally:
            connection.close()


def disk_tier_evidence(row, request_id):
    """Accept correlated logical file reads only; never infer physical NVMe I/O."""
    unknown = dict(correlated=False, file_blobs=None, file_mb=None, ram_blobs=None,
                   physical_nvme_bytes=None, general_model_support=False)
    if not isinstance(row, dict) or not isinstance(request_id, str) or not request_id or row.get('id') != request_id:
        return unknown
    for key in ('file_blobs', 'ram_blobs'):
        if type(row.get(key)) is not int or row[key] < 0:
            return unknown
    value = row.get('file_mb')
    import math
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        return unknown
    return dict(unknown, correlated=True, file_blobs=row['file_blobs'], file_mb=value, ram_blobs=row['ram_blobs'])
