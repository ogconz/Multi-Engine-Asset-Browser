"""Unit checks for release packaging inputs, independent of Windows/GitHub."""
from __future__ import annotations

import hashlib
import os
import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import build_exe, hash_exe
from app_version import __version__
from frozen_pak import import_pakfile


class ReleaseToolingTests(unittest.TestCase):
    def test_windows_build_command_publishes_single_gui_executable(self):
        with patch.object(sys, 'platform', 'win32'):
            command = build_exe.command()
        self.assertIn('--onefile', command)
        self.assertIn('--windowed', command)
        self.assertIn('MultiEngineAssetBrowser', command)
        self.assertIn('--add-data', command)
        self.assertTrue(any('blender_convert.py' in x for x in command))
        self.assertIn('--collect-all', command)
        self.assertIn('--additional-hooks-dir', command)
        self.assertEqual(__version__, '1.0.0')
        self.assertEqual(command[-1], str(build_exe.ROOT / 'multi_engine_browser.py'))

    def test_frozen_unreal_reader_prepares_runtime_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / 'bundle'
            fake_module = types.ModuleType('pyuepak')
            sentinel = object()
            fake_module.PakFile = sentinel
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(bundle), create=True), patch.dict(os.environ, {'LOCALAPPDATA': str(root / 'localapp')}), patch.dict(sys.modules, {'pyuepak': fake_module}):
                self.assertIs(import_pakfile(), sentinel)
                self.assertTrue((bundle / 'pyuepak').is_dir())

    def test_sha256_file_matches_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            exe = Path(temp) / 'MultiEngineAssetBrowser.exe'
            payload = b'MZ' + b'fake-test-executable'  # not a public release binary
            exe.write_bytes(payload)
            with patch.object(sys, 'argv', ['hash_exe.py', str(exe)]):
                hash_exe.main()
            text = exe.with_suffix('.exe.sha256').read_text(encoding='utf-8').strip()
            self.assertEqual(text, f'{hashlib.sha256(payload).hexdigest()}  {exe.name}')


if __name__ == '__main__':
    unittest.main()
