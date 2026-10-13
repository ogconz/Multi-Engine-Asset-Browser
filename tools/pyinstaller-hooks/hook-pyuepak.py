"""Bundle a directory marker for pyuepak's writable frozen runtime.

The Oodle DLL is proprietary and is intentionally not packaged here.
"""
from pathlib import Path

datas = [(str(Path(__file__).with_name('runtime-placeholder.txt')), 'pyuepak')]
