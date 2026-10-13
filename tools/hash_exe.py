"""Write a stable SHA-256 file next to the release executable."""
import hashlib
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python tools/hash_exe.py dist/MultiEngineAssetBrowser.exe')
    filename = Path(sys.argv[1]).resolve()
    if not filename.is_file():
        raise SystemExit(f'Missing release artifact: {filename}')
    sha = hashlib.sha256()
    with filename.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    checksum = filename.with_suffix(filename.suffix + '.sha256')
    checksum.write_text(f'{sha.hexdigest()}  {filename.name}\n', encoding='utf-8')
    print(checksum)


if __name__ == '__main__':
    main()
