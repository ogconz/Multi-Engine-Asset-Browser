"""Build the portable Windows GUI EXE from project root with PyInstaller.

Run from Windows with Python 3.11, requirements.txt and PyInstaller installed:
    python tools/build_exe.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / 'dist' / 'MultiEngineAssetBrowser.exe'


def command() -> list[str]:
    if sys.platform != 'win32':
        raise SystemExit('Windows EXE builds must run on Windows. Use GitHub Actions windows-latest.')

    return [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--clean', '--onefile', '--windowed',
        '--name', 'MultiEngineAssetBrowser',
        '--distpath', str(ROOT / 'dist'),
        '--workpath', str(ROOT / 'build'),
        '--specpath', str(ROOT),
        # The Blender helper is executed by Blender's bundled Python, so it
        # must remain an actual .py file rather than a PyInstaller code module.
        '--add-data', f'{ROOT / "blender_convert.py"}{os.pathsep}.',
        # UnityPy uses importlib.resources to open lzma.tpk during asset reads.
        # Frozen builds must include its resource package AND its data files.
        '--collect-all', 'UnityPy',
        '--hidden-import', 'UnityPy.resources',
        # UnityPy.export imports AudioClipConverter even for textures. Audio
        # extraction is outside this browser's features, so do not package
        # the proprietary FMOD audio engine just to preview PNG textures.
        # The runtime hook supplies a narrowly scoped optional-audio stub.
        '--exclude-module', 'fmod_toolkit',
        '--exclude-module', 'pyfmodex',
        '--runtime-hook', str(ROOT / 'tools' / 'runtime-hooks' / 'disable_unused_fmod.py'),
        # Qt is handled by PyInstaller's PySide6 hooks. These collect options
        # cover the VTK/PyVista modules that are imported dynamically by the viewer.
        '--collect-all', 'vtkmodules',
        '--collect-all', 'pyvista',
        '--collect-all', 'pyvistaqt',
        '--collect-submodules', 'trimesh',
        # Bundles only a tiny directory marker, not proprietary Oodle binaries.
        '--additional-hooks-dir', str(ROOT / 'tools' / 'pyinstaller-hooks'),
        '--hidden-import', 'pyuepak',
        '--hidden-import', 'cryptography',
        str(ROOT / 'multi_engine_browser.py'),
    ]


def main():
    subprocess.run(command(), cwd=ROOT, check=True)
    if not EXE.is_file() or EXE.stat().st_size < 100_000:
        raise SystemExit(f'Build did not produce a valid-sized EXE: {EXE}')
    with EXE.open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise SystemExit('Output does not begin with a Windows PE MZ header.')
    print(f'Build complete: {EXE} ({EXE.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
