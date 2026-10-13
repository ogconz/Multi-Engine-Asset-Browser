"""Unit checks for release packaging inputs, independent of Windows/GitHub."""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import build_exe, hash_exe


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
        self.assertEqual(command[-1], str(build_exe.ROOT / 'multi_engine_browser.py'))

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
