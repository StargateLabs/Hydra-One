"""Read the installed Whisper language table through its public C API, without a model."""
import ctypes
import os
import re
from functools import lru_cache
from pathlib import Path

FALLBACK = ('it', 'en', 'fr', 'de', 'es', 'pt', 'zh', 'ja')


@lru_cache(maxsize=8)
def _read_table(path, size, modified):
    # The identity includes file metadata, so selecting an updated runtime refreshes the table.
    context = os.add_dll_directory(str(Path(path).parent)) if os.name == 'nt' else None
    try:
        library = ctypes.CDLL(path)
        maximum = library.whisper_lang_max_id
        maximum.argtypes = []
        maximum.restype = ctypes.c_int
        code = library.whisper_lang_str
        code.argtypes = [ctypes.c_int]
        code.restype = ctypes.c_char_p
        last = maximum()
        if not 0 <= last <= 255:
            raise ValueError('Invalid native language table size')
        result = []
        for index in range(last + 1):
            value = code(index)
            if not value:
                raise ValueError('Incomplete native language table')
            value = value.decode('ascii')
            if not re.fullmatch('[a-z]{2,3}', value):
                raise ValueError('Invalid native language code')
            result.append(value)
        return tuple(result)
    finally:
        if context:
            context.close()


def language_inventory(binary):
    directory = Path(binary).parent
    for name in ('whisper.dll', 'libwhisper.dll', 'libwhisper.so', 'libwhisper.dylib'):
        library = directory / name
        try:
            info = library.stat()
            codes = _read_table(str(library.resolve()), info.st_size, info.st_mtime_ns)
            return {'languages': list(codes), 'languages_source': 'installed-runtime'}
        except (OSError, AttributeError, ValueError, UnicodeError):
            continue
    return {'languages': list(FALLBACK), 'languages_source': 'compatibility-fallback'}
