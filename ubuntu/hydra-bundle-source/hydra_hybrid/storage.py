"""Explicit bounded model-file staging, never inference-time weight offload."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import threading


def stage_model(source, destination, *, expected_sha256, max_bytes, reserve_bytes,
                authorized=False, cancel=None, available_bytes=None, chunk_bytes=1024*1024):
    """Write exclusively to caller-selected NEW path. Return only after hash/fsync.

    Destination is not published as valid until return; never load it while copying.
    Exclusive creation arbitrates callers for that pathname, not global disk capacity.
    """
    if authorized is not True:
        raise PermissionError('Explicit file staging authorization required')
    for name,value in (('max_bytes',max_bytes),('reserve_bytes',reserve_bytes),('chunk_bytes',chunk_bytes)):
        if type(value) is not int or value < 0 or (name != 'reserve_bytes' and not value):
            raise ValueError('Invalid storage budget '+name)
    if chunk_bytes > 8*1024*1024:
        raise ValueError('Chunk buffer exceeds 8 MiB')
    if not isinstance(expected_sha256,str) or not re.fullmatch('[a-fA-F0-9]{64}',expected_sha256):
        raise ValueError('Pinned model SHA256 required')
    source,destination=Path(source).resolve(),Path(destination).resolve()
    if source==destination or not destination.parent.is_dir():
        raise ValueError('Existing distinct destination parent required')
    cancel=cancel if cancel is not None else threading.Event()
    def check(size):
        if cancel.is_set():raise InterruptedError('Model staging cancelled')
        free=available_bytes() if available_bytes is not None else shutil.disk_usage(destination.parent).free
        if type(free) is not int or free < size+reserve_bytes:
            raise ValueError('Insufficient observed storage or reserve')
    with source.open('rb') as reader:
        size=os.fstat(reader.fileno()).st_size
        if size>max_bytes or reader.read(4)!=b'GGUF':
            raise ValueError('Bounded GGUF source required')
        reader.seek(0);check(size)
        created=False
        try:
            with destination.open('xb') as writer:
                created=True;digest=hashlib.sha256();copied=0
                while True:
                    check(0)
                    block=reader.read(chunk_bytes)
                    if not block:break
                    copied+=len(block)
                    if copied>max_bytes or copied>size:raise ValueError('Source size changed during staging')
                    writer.write(block);digest.update(block)
                if copied!=size or digest.hexdigest()!=expected_sha256.lower():
                    raise ValueError('Staged source hash or size mismatch')
                writer.flush();os.fsync(writer.fileno())
            check(0)
            with destination.open('rb') as staged:
                if hashlib.file_digest(staged,'sha256').hexdigest()!=expected_sha256.lower():
                    raise ValueError('Destination verification failed')
            return dict(schema='hydra.hybrid.model-staging.v1',staged_path=str(destination),
                        sha256=expected_sha256.lower(),bytes=copied,fsync_requested=True,
                        storage_kind='file_copy',inference_started=False,nvme_device_verified=False,
                        weight_streaming=False,performance='NOT_MEASURED')
        except BaseException as primary:
            if created:
                try:destination.unlink()
                except OSError as secondary:primary.add_note('Staging cleanup failed; destination remains uncertain: '+str(secondary))
            raise
