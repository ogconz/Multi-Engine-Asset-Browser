"""Unreal Engine 4 PAK asset browser backend.

PAK indexing: pyuepak parses the package DIRECTORY, without extracting a large PAK.
Selected package object listing / mesh & texture conversion: official UE Viewer (umodel).
Unreal I/O Store (.utoc/.ucas) is deliberately NOT treated as supported.
This code only reads game files and uses a temporary folder for decoded exports.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import trimesh
from PIL import Image

from skaterxl_core import export_fbx, export_glb, export_png

UE_PACKAGE_TYPE = 'UnrealPackage'
UE_MODEL_TYPES = ('StaticMesh', 'SkeletalMesh')
UE_IMAGE_TYPES = ('Texture2D',)
UE_EXPORTABLE_TYPES = UE_MODEL_TYPES + UE_IMAGE_TYPES + (UE_PACKAGE_TYPE,)
UE_SUFFIXES = {'.uasset', '.umap'}
RESULT_LIMIT = 1500


@dataclass(frozen=True)
class UnrealAsset:
    bundle: str              # PAK path (or loose .uasset)
    cab: str                 # virtual path inside PAK (not a Unity CAB)
    path_id: int             # UModel export-table entry + 1, 0 = uninspected package
    type: str
    name: str


def unreal_default_cache_path(root: Path) -> Path:
    key = hashlib.sha256(os.path.normcase(str(root.resolve())).encode('utf-8')).hexdigest()[:18]
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.cache'))) / 'MultiEngineAssetBrowser'
    base.mkdir(parents=True, exist_ok=True)
    return base / f'unreal_{key}.sqlite3'


def connect_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS containers (
          path TEXT PRIMARY KEY, file_size INTEGER NOT NULL, modified_ns INTEGER NOT NULL,
          scan_id INTEGER NOT NULL, error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS packages (
          source TEXT NOT NULL, asset_path TEXT NOT NULL, name TEXT NOT NULL,
          PRIMARY KEY(source, asset_path)
        );
        CREATE TABLE IF NOT EXISTS objects (
          source TEXT NOT NULL, asset_path TEXT NOT NULL,
          ordinal INTEGER NOT NULL, type TEXT NOT NULL, name TEXT NOT NULL,
          PRIMARY KEY(source, asset_path, ordinal)
        );
        CREATE INDEX IF NOT EXISTS pkg_search ON packages(name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS pkg_source ON packages(source);
        CREATE INDEX IF NOT EXISTS obj_search ON objects(name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS obj_type ON objects(type);
        CREATE INDEX IF NOT EXISTS obj_source ON objects(source, asset_path);
        CREATE TABLE IF NOT EXISTS inspections (
          source TEXT NOT NULL, asset_path TEXT NOT NULL,
          context TEXT NOT NULL, status TEXT NOT NULL,
          error TEXT NOT NULL DEFAULT '', inspected_ns INTEGER NOT NULL,
          PRIMARY KEY(source, asset_path)
        );
        CREATE INDEX IF NOT EXISTS inspections_context ON inspections(context, status);
    ''')
    return conn


def find_ue_containers(root: Path) -> tuple[list[Path], int]:
    """Returns .pak plus loose .uasset/.umap; .utoc count is diagnostic only."""
    found = []
    iostore = 0
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in {'.git', '__pycache__', '.venv'}]
        for name in names:
            p = Path(base) / name
            ext = p.suffix.lower()
            if ext == '.pak' or ext in UE_SUFFIXES:
                found.append(p)
            if ext == '.utoc':
                iostore += 1
    return sorted(found, key=lambda p: str(p).lower()), iostore


def valid_aes_key(key: str) -> str:
    """Never persist AES keys. Pass only a user-provided 256-bit key to tools."""
    raw = key.strip()
    if not raw:
        return ''
    if raw.lower().startswith('0x'):
        raw = raw[2:]
    if not re.fullmatch(r'[0-9a-fA-F]{64}', raw):
        raise ValueError('A PAK AES key must contain exactly 64 hexadecimal characters (32 bytes).')
    return '0x' + raw.lower()


class UnrealIndexer:
    def __init__(self, root: Path, db_path: Path, aes_key: str = ''):
        self.root, self.db_path = root, db_path
        self.aes_key = valid_aes_key(aes_key)
        self.iostore_count = 0

    def scan(self, progress: Optional[Callable] = None,
             cancel: Optional[threading.Event] = None) -> tuple[int, int, int]:
        containers, self.iostore_count = find_ue_containers(self.root)
        if not containers and self.iostore_count:
            raise RuntimeError('This installation uses .utoc/.ucas (Unreal I/O Store), which this backend cannot read yet. ' 
                               'For UE4 .pak games such as Session, choose the folder containing the .pak file.')
        if not containers:
            raise RuntimeError('No Unreal .pak or loose .uasset/.umap files found. Select the game root or Content/Paks folder.')
        completed = changed = errors = 0
        scan_id = time.time_ns()
        conn = connect_db(self.db_path)
        try:
            for source in containers:
                if cancel and cancel.is_set():
                    break
                source_string = str(source)
                try:
                    st = source.stat()
                    prev = conn.execute('SELECT file_size,modified_ns,error FROM containers WHERE path=?',
                                        (source_string,)).fetchone()
                    if prev and prev['file_size'] == st.st_size and prev['modified_ns'] == st.st_mtime_ns and not prev['error']:
                        with conn:
                            conn.execute('UPDATE containers SET scan_id=? WHERE path=?', (scan_id, source_string))
                    else:
                        if source.suffix.lower() == '.pak':
                            try:
                                from pyuepak import PakFile
                            except ImportError as exc:
                                raise RuntimeError(f'PAK indexing could not import pyuepak: {exc}. Run install_windows.bat to install pyuepak and cryptography.') from exc
                            pak = PakFile()
                            if self.aes_key:
                                pak.set_key(self.aes_key)
                            pak.read(source_string)   # reads PAK footer and index, not 16 GB of data
                            package_paths = [p.replace('\\', '/') for p in pak.list_files()
                                             if Path(p).suffix.lower() in UE_SUFFIXES]
                        else:
                            package_paths = [source.relative_to(self.root).as_posix()]
                        # Avoid storing duplicate paths within a single archive.
                        package_paths = list(dict.fromkeys(package_paths))
                        rows = [(source_string, p, Path(p).stem) for p in package_paths]
                        with conn:
                            conn.execute('DELETE FROM objects WHERE source=?', (source_string,))
                            conn.execute('DELETE FROM inspections WHERE source=?', (source_string,))
                            conn.execute('DELETE FROM packages WHERE source=?', (source_string,))
                            conn.executemany('INSERT INTO packages VALUES (?,?,?)', rows)
                            conn.execute('INSERT OR REPLACE INTO containers VALUES (?,?,?,?,?)',
                                         (source_string, st.st_size, st.st_mtime_ns, scan_id, ''))
                        changed += 1
                except Exception as exc:
                    errors += 1
                    # Do not delete a previously working index when a file temporarily fails.
                    try:
                        st = source.stat()
                        with conn:
                            conn.execute('INSERT OR REPLACE INTO containers VALUES (?,?,?,?,?)',
                                         (source_string, st.st_size, st.st_mtime_ns, scan_id,
                                          f'{type(exc).__name__}: {exc}'[:700]))
                    except OSError:
                        pass
                completed += 1
                if progress and (completed % 10 == 0 or completed == len(containers)):
                    progress(completed, len(containers), changed, errors, source.name)
            if not (cancel and cancel.is_set()):
                with conn:
                    conn.execute('DELETE FROM objects WHERE source IN (SELECT path FROM containers WHERE scan_id != ?)', (scan_id,))
                    conn.execute('DELETE FROM inspections WHERE source IN (SELECT path FROM containers WHERE scan_id != ?)', (scan_id,))
                    conn.execute('DELETE FROM packages WHERE source IN (SELECT path FROM containers WHERE scan_id != ?)', (scan_id,))
                    conn.execute('DELETE FROM containers WHERE scan_id != ?', (scan_id,))
            return completed, changed, errors
        finally:
            conn.close()


def _filter_clause(search: str, typ: str, alias: str) -> tuple[str, list]:
    where, vals = [], []
    if typ != 'All':
        if typ == '3D candidates':
            if alias == 'p':
                # Do not guess types from a package filename.
                where.append('0')
            else:
                where.append("o.type IN ('StaticMesh', 'SkeletalMesh')")
        else:
            where.append(('? = ?' if alias == 'p' else 'o.type = ?'))
            vals.extend(([UE_PACKAGE_TYPE, typ] if alias == 'p' else [typ]))
    if search.strip():
        # Use LIKE rather than an unbounded Python in-memory list.
        term = search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        text = f'%{term}%'
        if alias == 'p':
            where.append("(p.name LIKE ? ESCAPE '\\' OR p.asset_path LIKE ? ESCAPE '\\')")
        else:
            where.append("(o.name LIKE ? ESCAPE '\\' OR o.asset_path LIKE ? ESCAPE '\\')")
        vals.extend([text, text])
    return (' AND '.join(where) if where else '1'), vals


def query_unreal_assets(db_path: Path, search: str = '', typ: str = 'All', limit: int = RESULT_LIMIT):
    if not db_path.is_file():
        return [], 0
    conn = connect_db(db_path)
    try:
        wp, pp = _filter_clause(search, typ, 'p')
        wo, po = _filter_clause(search, typ, 'o')
        # After a successful inspection, show real object types in the default list,
        # not the redundant UnrealPackage placeholder. Failed/uninspected packages
        # remain visible so the user can retry or inspect them manually.
        package_select = (f"SELECT p.source AS bundle,p.asset_path AS cab,0 AS path_id,"
                          f"'UnrealPackage' AS type,p.name AS name FROM packages p "
                          f"WHERE {wp} AND NOT EXISTS "
                          f"(SELECT 1 FROM inspections i WHERE i.source=p.source "
                          f"AND i.asset_path=p.asset_path AND i.status='ok')")
        object_select = f'SELECT o.source AS bundle,o.asset_path AS cab,o.ordinal AS path_id,o.type AS type,o.name AS name FROM objects o WHERE {wo}'
        union = f'{package_select} UNION ALL {object_select}'
        params = pp + po
        count = conn.execute(f'SELECT COUNT(*) FROM ({union})', params).fetchone()[0]
        results = conn.execute(f'SELECT * FROM ({union}) ORDER BY name COLLATE NOCASE,type LIMIT ?',
                               params + [int(limit)]).fetchall()
        return [UnrealAsset(**dict(r)) for r in results], count
    finally:
        conn.close()


def unreal_known_types(db_path: Path) -> list[str]:
    if not db_path.is_file():
        return []
    conn = connect_db(db_path)
    try:
        rows = conn.execute('SELECT DISTINCT type FROM objects ORDER BY type').fetchall()
        return [UE_PACKAGE_TYPE, *(r[0] for r in rows)]
    finally:
        conn.close()


def unreal_errors(db_path: Path, limit: int = 12) -> list[str]:
    if not db_path.is_file():
        return []
    conn = connect_db(db_path)
    try:
        return [f'{Path(r[0]).name}: {r[1]}' for r in conn.execute(
            'SELECT path,error FROM containers WHERE error != ? LIMIT ?', ('', int(limit)))]
    finally:
        conn.close()


# UModel -list prints: '   0     12AB     14AF StaticMesh SM_Chair'
UMODEL_EXPORT_LINE = re.compile(r'^\s*(\d+)\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+([A-Za-z]\w*)\s+(\S[^\r\n]*)\s*$')


def parse_umodel_list(output: str) -> list[tuple[int, str, str]]:
    rows = []
    for line in output.splitlines():
        match = UMODEL_EXPORT_LINE.match(line)
        if match:
            idx, class_name, object_name = match.groups()
            rows.append((int(idx) + 1, class_name, object_name.strip()))
    return rows


def save_inspected_objects(db_path: Path, asset: UnrealAsset, rows: list[tuple[int, str, str]],
                           context: str = '') -> None:
    conn = connect_db(db_path)
    try:
        match = conn.execute('SELECT 1 FROM packages WHERE source=? AND asset_path=?',
                             (asset.bundle, asset.cab)).fetchone()
        if not match:
            raise RuntimeError('Package disappeared from index. Re-scan the game folder.')
        with conn:
            conn.execute('DELETE FROM objects WHERE source=? AND asset_path=?', (asset.bundle, asset.cab))
            conn.executemany('INSERT INTO objects VALUES (?,?,?,?,?)',
                             [(asset.bundle, asset.cab, idx, typ, name) for idx, typ, name in rows])
            conn.execute('INSERT OR REPLACE INTO inspections VALUES (?,?,?,?,?,?)',
                         (asset.bundle, asset.cab, context, 'ok', '', time.time_ns()))
    finally:
        conn.close()


def record_inspection_error(db_path: Path, asset: UnrealAsset, context: str, error: str) -> None:
    """Retain failures for diagnostics; an explicit Retry can revisit them."""
    conn = connect_db(db_path)
    try:
        with conn:
            conn.execute('INSERT OR REPLACE INTO inspections VALUES (?,?,?,?,?,?)',
                         (asset.bundle, asset.cab, context, 'error', error[:900], time.time_ns()))
    finally:
        conn.close()


def pending_unreal_packages(db_path: Path, context: str, retry_errors: bool = False) -> list[UnrealAsset]:
    """Get packages needing true class inspection without opening the whole PAK.

    Older v2.0 manual inspections have object rows but no inspections table records;
    adopt those into the current context to avoid throwing away work on upgrade.
    """
    conn = connect_db(db_path)
    try:
        with conn:
            conn.execute("""INSERT OR IGNORE INTO inspections
                SELECT o.source, o.asset_path, ?, 'ok', '', ? FROM objects o
                GROUP BY o.source,o.asset_path""", (context, time.time_ns()))
            # Manual inspections from older versions had no version context.
            conn.execute("""UPDATE inspections SET context=?
                WHERE status='ok' AND context=''""", (context,))
        where = """NOT EXISTS (
            SELECT 1 FROM inspections i WHERE i.source=p.source AND i.asset_path=p.asset_path
            AND i.context=? AND (i.status='ok' OR (?=0 AND i.status='error'))
        )"""
        rows = conn.execute(f"""SELECT p.source AS bundle,p.asset_path AS cab,0 AS path_id,
            'UnrealPackage' AS type,p.name AS name FROM packages p
            JOIN containers c ON p.source=c.path
            WHERE c.error='' AND {where}
            ORDER BY p.name COLLATE NOCASE""", (context, int(retry_errors))).fetchall()
        return [UnrealAsset(**dict(r)) for r in rows]
    finally:
        conn.close()


def unreal_inspection_errors(db_path: Path, context: str, limit: int = 8) -> list[str]:
    if not db_path.is_file():
        return []
    conn = connect_db(db_path)
    try:
        return [f"{Path(r['asset_path']).name}: {r['error']}" for r in conn.execute(
            """SELECT asset_path,error FROM inspections
               WHERE context=? AND status='error' ORDER BY inspected_ns DESC LIMIT ?""",
            (context, limit))]
    finally:
        conn.close()


class UnrealAutoInspector:
    """Bulk package class identification; call from a worker, never on the UI thread.

    This intentionally uses the real UModel export table, not filename heuristics.
    Individual -list calls can be slow for large encrypted PAKs; completed packages
    are cached, and Stop is checked between packages. Failed packages are
    retried on the next batch; this accommodates an AES key entered later.
    """
    def __init__(self, db_path: Path, extractor: 'UnrealExtractor'):
        self.db_path, self.extractor = db_path, extractor

    def inspect_all(self, progress: Optional[Callable] = None,
                    cancel: Optional[threading.Event] = None,
                    retry_errors: bool = True) -> tuple[int, int, int, int, int, bool]:
        ctx = self.extractor.inspection_context()
        assets = pending_unreal_packages(self.db_path, ctx, retry_errors=retry_errors)
        identified = failures = num_objects = completed = 0
        for asset in assets:
            if cancel is not None and cancel.is_set():
                break
            try:
                rows = self.extractor.inspect(asset)
                save_inspected_objects(self.db_path, asset, rows, ctx)
                identified += 1
                num_objects += len(rows)
            except Exception as exc:
                failures += 1
                # Suppress the AES key in diagnostics and never save it to disk.
                message = f'{type(exc).__name__}: {exc}'
                if self.extractor.aes_key:
                    message = message.replace(self.extractor.aes_key, '<redacted AES key>')
                record_inspection_error(self.db_path, asset, ctx, message)
            completed += 1
            if progress:
                progress(completed, len(assets), identified, failures, num_objects, asset.name)
        return completed, len(assets), identified, failures, num_objects, bool(cancel and cancel.is_set())


def find_umodel_exe() -> str:
    local = Path(__file__).parent
    candidates = [local / 'umodel.exe', local / 'tools' / 'umodel.exe']
    candidates.extend(Path(p) / 'umodel.exe' for p in (os.environ.get('USERPROFILE', ''),) if p)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which('umodel.exe') or shutil.which('umodel') or ''


def umodel_package_selector(asset: UnrealAsset) -> str:
    """Package selector accepted by UE Viewer, relative to a game Content root.

    UModel maintains an index over the selected -path's packages (including PAKs),
    so it can resolve the relative Unreal asset pathname without unpacking.
    """
    if Path(asset.bundle).suffix.lower() in UE_SUFFIXES:
        return str(Path(asset.bundle))
    name = asset.cab.replace('\\', '/').lstrip('/')
    while name.startswith('../'):
        name = name[3:]
    # Archive virtual paths often include ../../../Project/Content/..
    if '/Content/' in name:
        name = name.split('/Content/', 1)[1]
    elif name.startswith('Content/'):
        name = name[8:]
    return name


class UnrealExtractor:
    """On-demand UModel exporter; no permanent unpacking, no writes to game files."""
    def __init__(self, root: Path, exe: str, game_override: str = '', aes_key: str = ''):
        self.root = Path(root)
        self.exe = Path(exe)
        if not self.exe.is_file():
            raise FileNotFoundError('UE Viewer (umodel.exe) not found. Download UE Viewer, then select umodel.exe in Settings.')
        self.game_override = game_override.strip()
        if self.game_override and not re.fullmatch(r'[A-Za-z0-9_.-]{1,35}', self.game_override):
            raise ValueError('Engine override contains unsupported characters. Example: ue4.27')
        self.aes_key = valid_aes_key(aes_key)

    def inspection_context(self) -> str:
        """Invalidates classification cache when UModel or game override changes.

        Secret AES keys are never serialized, hashed into the key, or saved to disk.
        """
        st = self.exe.stat()
        return f'{self.exe.resolve()}|{st.st_size}|{st.st_mtime_ns}|{self.game_override.lower()}'

    def _call(self, mode: str, asset: UnrealAsset, tmp: Path | None = None) -> str:
        if mode not in ('list', 'export'):
            raise ValueError('Invalid UE Viewer operation')
        common = [str(self.exe), '-' + mode, '-path=' + str(self.root)]
        if self.game_override:
            common.append('-game=' + self.game_override)
        if self.aes_key:
            common.append('-aes=' + self.aes_key)
        if mode == 'export':
            assert tmp is not None
            common += ['-gltf', '-png', '-out=' + str(tmp)]
        selector = umodel_package_selector(asset)
        selectors = [selector]
        if Path(asset.bundle).suffix.lower() == '.pak':
            # UE Viewer builds differ in how they match cooked virtual package paths.
            # Try the relative directory path first (avoids duplicate basenames), then
            # the package basename and bare stem if UModel could not FIND the package.
            selectors.extend([Path(selector).name, Path(selector).stem])
        selectors = list(dict.fromkeys(selectors))
        for n, package in enumerate(selectors):
            args = [*common, package]
            if mode == 'export' and asset.path_id > 0:
                args += [asset.name, asset.type]
            result = subprocess.run(args, cwd=str(tmp or self.root), stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, errors='replace',
                                    timeout=360 if mode == 'export' else 120)
            output = (result.stdout or '') + '\n' + (result.stderr or '')
            # UModel sometimes returns 0 when it could not find the named package.
            package_missing = ('unable to find package' in output.lower() or
                               'failed to load provided packages' in output.lower())
            if package_missing and n + 1 < len(selectors):
                continue
            errors = [line for line in output.splitlines()
                      if line.lstrip().startswith(('ERROR:', 'FATAL ERROR:'))]
            # Do not expose a user-supplied AES key in a captured subprocess message.
            if self.aes_key:
                output = output.replace(self.aes_key, '<redacted AES key>')
                errors = [e.replace(self.aes_key, '<redacted AES key>') for e in errors]
            if result.returncode != 0 or errors or package_missing:
                raise RuntimeError('UE Viewer failed:\n' + ('\n'.join(errors[:6]) or output[-2200:]))
            return output
        raise RuntimeError('UE Viewer could not find this Unreal package.')

    def inspect(self, asset: UnrealAsset) -> list[tuple[int, str, str]]:
        output = self._call('list', asset)
        rows = parse_umodel_list(output)
        if not rows:
            raise RuntimeError('UE Viewer did not return a readable object list for this package.\n'
                               'It may require a different UE version override or be unsupported.\n\n' + output[-900:])
        return rows

    @staticmethod
    def _candidate_file(files: list[Path], asset: UnrealAsset, kind: str) -> Path:
        if not files:
            raise RuntimeError(f'UE Viewer did not export a {kind.upper()} for {asset.name}. '
                               'This item may not contain a supported mesh/texture, or its UE4 format is unsupported.')
        if len(files) == 1:
            return files[0]
        if asset.path_id == 0:
            raise RuntimeError(f'This Unreal package contains {len(files)} {kind.upper()} candidates. '
                               'Click Inspect package and select the specific StaticMesh, SkeletalMesh, or Texture2D.')
        matching = [p for p in files if p.stem.lower() == asset.name.lower()]
        if len(matching) == 1:
            return matching[0]
        raise RuntimeError(f'This Unreal package produced {len(files)} {kind.upper()} files. '
                           'Click Inspect package to identify a StaticMesh, SkeletalMesh, or Texture2D child, '
                           'then select that object for a precise export.')

    def extract(self, asset: UnrealAsset, requested: str = 'preview'):
        """Return (kind, result, warnings), kind='scene' or 'image'."""
        if asset.type not in UE_EXPORTABLE_TYPES:
            raise RuntimeError(f'{asset.type} is indexed, but model/texture extraction is not supported for that class.')
        with tempfile.TemporaryDirectory(prefix='unreal_asset_view_') as td:
            tmp = Path(td)
            self._call('export', asset, tmp)
            model_files = [p for p in tmp.rglob('*') if p.suffix.lower() in ('.gltf', '.glb')]
            texture_files = [p for p in tmp.rglob('*') if p.suffix.lower() in ('.png', '.tga')]
            wants_image = requested == 'png' or asset.type == 'Texture2D'
            if requested in ('glb', 'fbx'):
                wants_image = False
            if requested == 'preview' and asset.type == UE_PACKAGE_TYPE and not model_files and texture_files:
                wants_image = True
            if wants_image:
                file = self._candidate_file(texture_files, asset, 'png')
                with Image.open(file) as img:
                    img.load()
                    image = img.copy()
                return 'image', image, []
            file = self._candidate_file(model_files, asset, 'gltf')
            try:
                scene = trimesh.load(str(file), force='scene', process=False)
            except Exception as exc:
                raise RuntimeError(f'UE Viewer exported {file.name}, but Trimesh could not load its glTF: {exc}') from exc
            if not isinstance(scene, trimesh.Scene) or not scene.geometry or not any(
                getattr(g, 'faces', None) is not None and len(g.faces) for g in scene.geometry.values()
            ):
                raise RuntimeError('Unreal export contained no mesh triangles; no empty model will be returned.')
            warnings = ['Unreal meshes are exported as static glTF geometry; skeletal rigs/animation may not survive conversion.']
            return 'scene', scene, warnings


def unreal_asset_details(asset: UnrealAsset) -> str:
    common = (f'Name:     {asset.name}\nType:     {asset.type}\n'
              f'PAK/file: {asset.bundle}\nUnreal path: {asset.cab}\n')
    if asset.type == UE_PACKAGE_TYPE:
        return common + ('\nThis is a package entry from the PAK index, not yet a typed asset.\n'
                         'Click Inspect package to list individual StaticMesh, SkeletalMesh, and Texture2D objects.\n'
                         'If only one mesh/texture is present, package-level preview/export may also work.')
    return common + f'UE Viewer table index: {asset.path_id - 1}\n\nThis object was identified by UE Viewer.'
