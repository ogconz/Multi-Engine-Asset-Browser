"""PyInstaller-safe import of pyuepak without redistributing Oodle.

Upstream pyuepak downloads oo2core_9_win64.dll to Path(__file__).parent.
PyInstaller --onefile may omit that directory (_MEIPASS/pyuepak); create it
and cache a locally obtained, SHA-verified copy for subsequent launches.
Normal Python source runs continue to use pyuepak unchanged.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

_DLL = 'oo2core_9_win64.dll'
# SHA-256 from upstream pyuepak's OodlePlatform declaration.
_EXPECTED_SHA256 = '6f5d41a7892ea6b2db420f2458dad2f84a63901c9a93ce9497337b16c195f457'


def _valid_oodle(path: Path) -> bool:
    try:
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                sha.update(chunk)
        return sha.hexdigest() == _EXPECTED_SHA256
    except OSError:
        return False


def _frozen_oodle_paths() -> tuple[Path, Path] | None:
    if not getattr(sys, 'frozen', False) or not getattr(sys, '_MEIPASS', None):
        return None
    # fetch_oodle writes to __file__'s parent. Ensure it exists first.
    package_dir = Path(sys._MEIPASS) / 'pyuepak'
    package_dir.mkdir(parents=True, exist_ok=True)
    local = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))
    cache = local / 'MultiEngineAssetBrowser' / 'codecs' / _DLL
    return package_dir / _DLL, cache


def import_pakfile():
    """Get PakFile while preparing/caching Oodle for a frozen EXE."""
    paths = _frozen_oodle_paths()
    if paths is not None:
        runtime, cache = paths
        if _valid_oodle(cache) and not _valid_oodle(runtime):
            shutil.copyfile(cache, runtime)

    # On first use pyuepak downloads Oodle to the now-existing runtime folder
    # and verifies the SHA-256 itself. No proprietary DLL is bundled.
    from pyuepak import PakFile

    if paths is not None:
        runtime, cache = paths
        if _valid_oodle(runtime) and not _valid_oodle(cache):
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(runtime, cache)
            except OSError:
                # Cache writes are optional; PAK indexing still works.
                pass
    return PakFile
