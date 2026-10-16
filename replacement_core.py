"""Replacement selection, previews and the first supported in-game installation adapter.

Unity Texture2D can be installed into supported Unity game archives with an
immutable backup. Meshes and Unreal assets currently support preview only:
no automatic in-game replacement is claimed for these combinations.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

IMAGE_EXTS = frozenset({'.png', '.jpg', '.jpeg'})
MESH_EXTS = frozenset({'.fbx', '.glb'})
UNITY_MESH_TYPES = frozenset({'Mesh', 'GameObject', 'SkinnedMeshRenderer', 'MeshFilter', 'MeshRenderer'})
UNREAL_MESH_TYPES = frozenset({'StaticMesh', 'SkeletalMesh'})


class ReplacementError(RuntimeError):
    """An asset replacement cannot be prepared or safely installed."""


@dataclass(frozen=True)
class InstallResult:
    game_file: Path
    backup_file: Path
    operation: str


def replacement_kind(engine: str, asset_type: str) -> Optional[str]:
    if asset_type == 'Texture2D' and engine in {'Unity', 'Unreal'}:
        return 'texture'
    if engine == 'Unity' and asset_type in UNITY_MESH_TYPES:
        return 'mesh'
    if engine == 'Unreal' and asset_type in UNREAL_MESH_TYPES:
        return 'mesh'
    return None


def can_install(engine: str, asset_type: str) -> bool:
    """Never claim installation capability where only preview exists."""
    return engine == 'Unity' and asset_type == 'Texture2D'


def validate_replacement_file(source: str | Path, kind: str) -> Path:
    try:
        path = Path(source).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReplacementError('Replacement file does not exist or cannot be opened.') from exc
    allowed = IMAGE_EXTS if kind == 'texture' else MESH_EXTS if kind == 'mesh' else ()
    if not path.is_file() or path.suffix.lower() not in allowed:
        raise ReplacementError(f'Choose a {"PNG/JPG texture" if kind == "texture" else "FBX/GLB mesh"}.')
    if path.stat().st_size <= 0:
        raise ReplacementError('The replacement file is empty.')
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ReplacementError('Replacement files over 512 MB are not supported yet.')
    return path


def load_replacement_image(source: str | Path):
    from PIL import Image

    path = validate_replacement_file(source, 'texture')
    with Image.open(path) as image:
        image.load()
        if image.width < 1 or image.height < 1:
            raise ReplacementError('The replacement texture has invalid dimensions.')
        if image.width * image.height > 75_000_000:
            raise ReplacementError('The replacement texture is too large (over 75 million pixels).')
        return image.convert('RGBA')


def load_replacement_mesh(source: str | Path, blender_exe: str = '', converter_script: str | Path = ''):
    """Load a GLB scene, or use Blender to convert an FBX for preview only."""
    import subprocess
    import trimesh

    path = validate_replacement_file(source, 'mesh')
    if path.suffix.lower() == '.glb':
        scene = trimesh.load(str(path), force='scene', process=False)
    else:
        blender = Path(blender_exe) if blender_exe else None
        helper = Path(converter_script) if converter_script else None
        if not blender or not blender.is_file() or not helper or not helper.is_file():
            raise ReplacementError('Previewing FBX requires Blender. Select blender.exe first, or use a GLB model.')
        with tempfile.TemporaryDirectory(prefix='meab_fbx_preview_') as folder:
            target = Path(folder) / 'preview.glb'
            cmd = [str(blender), '--background', '--python', str(helper), '--', str(path), str(target)]
            try:
                process = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ReplacementError('Blender timed out while reading FBX.') from exc
            if process.returncode or not target.is_file():
                raise ReplacementError('Blender could not import the FBX: ' + (process.stderr or process.stdout)[-700:])
            scene = trimesh.load(str(target), force='scene', process=False)
    valid = [g for g in scene.geometry.values() if isinstance(g, trimesh.Trimesh) and len(g.vertices) and len(g.faces)]
    if not valid:
        raise ReplacementError('This file does not contain a usable triangle mesh.')
    return scene


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_atomically(path: Path, data: bytes) -> None:
    """Use a temp file in the destination folder and an atomic file replace."""
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.meab-', suffix='.tmp', dir=path.parent, delete=False) as tmp:
            tmp_name = tmp.name
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()


def _backup_paths(target: Path, backup_root: Optional[Path]) -> tuple[Path, Path]:
    if backup_root is None:
        base = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / '.local' / 'share'))
        backup_root = base / 'MultiEngineAssetBrowser' / 'replacement_backups'
    identity = hashlib.sha256(os.path.normcase(str(target)).casefold().encode('utf-8')).hexdigest()
    location = Path(backup_root) / identity
    return location / 'original.bin', location / 'manifest.json'


def _target_path(game_root: str | Path, game_file: str | Path) -> Path:
    root = Path(game_root).expanduser().resolve(strict=True)
    requested = Path(game_file).expanduser()
    if requested.is_symlink():
        raise ReplacementError('Replacing through symlinks is not supported.')
    target = requested.resolve(strict=True)
    if not root.is_dir() or not target.is_file() or not target.is_relative_to(root):
        raise ReplacementError('Selected asset container is outside the chosen game folder.')
    return target


def _read_manifest(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ReplacementError('Backup manifest cannot be read. Refusing to modify a game file.') from exc
    if not isinstance(manifest, dict) or manifest.get('schema') != 1:
        raise ReplacementError('Backup manifest format is unsupported.')
    return manifest


def has_installed_replacement(game_root: str | Path, game_file: str | Path, backup_root: Optional[Path] = None) -> bool:
    try:
        target = _target_path(game_root, game_file)
        _, manifest_path = _backup_paths(target, backup_root)
        manifest = _read_manifest(manifest_path)
        return bool(manifest and manifest.get('status') == 'installed')
    except (OSError, ReplacementError):
        return False


def _find_unity_reader(env, cab: str, path_id: int):
    """Path IDs can repeat across CABs; match both the CAB and the PathID."""
    from skaterxl_core import unity_name

    matches = [item for item in env.objects if int(item.path_id) == int(path_id)
               and unity_name(getattr(item.assets_file, 'name', '')) == unity_name(cab)
               and item.type.name == 'Texture2D']
    if len(matches) != 1:
        raise ReplacementError(f'Could not uniquely locate Texture2D path {path_id} in Unity CAB {cab}.')
    return matches[0]


def install_unity_texture(
    game_root: str | Path, asset, replacement: str | Path, backup_root: Optional[Path] = None
) -> InstallResult:
    """Rewrite a supported Unity Texture2D container with full backup and validation.

    Caller must require explicit consent and ask that the game be closed. Only
    suitable for local game modding where the player is authorized to modify
    files; it cannot guarantee an arbitrary game will accept the new container.
    """
    if getattr(asset, 'type', None) != 'Texture2D':
        raise ReplacementError('In-game installation currently supports only Unity Texture2D.')
    target = _target_path(game_root, asset.bundle)
    source = validate_replacement_file(replacement, 'texture')
    if source == target:
        raise ReplacementError('Replacement input must not be the original game file.')
    image = load_replacement_image(source)
    original_bytes = target.read_bytes()
    original_hash = _hash_bytes(original_bytes)
    backup_path, manifest_path = _backup_paths(target, backup_root)
    current_manifest = _read_manifest(manifest_path)
    if current_manifest:
        if current_manifest.get('game_file') != str(target) or not backup_path.is_file():
            raise ReplacementError('A previous backup is incomplete. Refusing to overwrite the game file.')
        if _hash_bytes(backup_path.read_bytes()) != current_manifest.get('original_sha256'):
            raise ReplacementError('Original backup has changed; refusing to continue.')
        expected = current_manifest.get('installed_sha256') if current_manifest.get('status') == 'installed' else current_manifest.get('original_sha256')
        if original_hash != expected:
            raise ReplacementError('The game archive changed since our last backup (perhaps from a game update). Restore manually or re-scan; refusing to overwrite it.')
    # Convert, serialize, and verify before writing anything in the game.
    try:
        import UnityPy
        from UnityPy.enums import TextureFormat

        env = UnityPy.load(io.BytesIO(original_bytes))
        reader = _find_unity_reader(env, asset.cab, asset.path_id)
        texture = reader.parse_as_object()
        if not hasattr(texture, 'set_image'):
            raise ReplacementError('This UnityPy version cannot encode the selected texture.')
        # Avoid guessing a game's original compression codec; RGBA32 is a
        # widely supported Unity texture format, though larger on disk.
        texture.set_image(image, target_format=TextureFormat.RGBA32, mipmap_count=1)
        texture.save()
        modified_bytes = env.file.save(packer='original')
        if not isinstance(modified_bytes, bytes) or not modified_bytes:
            raise ReplacementError('UnityPy returned an invalid rebuilt game container.')
        modified = UnityPy.load(io.BytesIO(modified_bytes))
        verified_reader = _find_unity_reader(modified, asset.cab, asset.path_id)
        verified_texture = verified_reader.parse_as_object()
        if (int(verified_texture.m_Width), int(verified_texture.m_Height)) != image.size:
            raise ReplacementError('Rebuilt Unity texture does not have the expected dimensions.')
    except ReplacementError:
        raise
    except Exception as exc:
        raise ReplacementError(f'UnityPy could not rewrite this texture container: {type(exc).__name__}: {exc}') from exc
    if modified_bytes == original_bytes:
        raise ReplacementError('UnityPy did not change the container; replacement was not installed.')
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if not backup_path.exists():
        _write_atomically(backup_path, original_bytes)
    if _hash_bytes(backup_path.read_bytes()) != (current_manifest or {}).get('original_sha256', original_hash):
        raise ReplacementError('Backup hash mismatch. Game file was not changed.')
    new_manifest = {
        'schema': 1, 'game_file': str(target), 'original_sha256': _hash_bytes(backup_path.read_bytes()),
        'installed_sha256': _hash_bytes(modified_bytes), 'status': 'installed',
        'asset_name': str(asset.name), 'asset_cab': str(asset.cab), 'asset_path_id': int(asset.path_id),
    }
    try:
        _write_atomically(target, modified_bytes)
        _write_atomically(manifest_path, json.dumps(new_manifest, indent=2).encode('utf-8'))
    except OSError as exc:
        if target.is_file() and _hash_bytes(target.read_bytes()) == new_manifest['installed_sha256']:
            _write_atomically(target, original_bytes)
        raise ReplacementError(f'Unable to install the replacement: {exc}') from exc
    return InstallResult(target, backup_path, 'installed')


def restore_unity_texture(
    game_root: str | Path, game_file: str | Path, backup_root: Optional[Path] = None
) -> InstallResult:
    target = _target_path(game_root, game_file)
    backup_path, manifest_path = _backup_paths(target, backup_root)
    manifest = _read_manifest(manifest_path)
    if not manifest or manifest.get('status') != 'installed' or manifest.get('game_file') != str(target):
        raise ReplacementError('No active replacement/backup was found for this game archive.')
    if not backup_path.is_file():
        raise ReplacementError('Original game archive backup is missing. Nothing was modified.')
    original_bytes = backup_path.read_bytes()
    if _hash_bytes(original_bytes) != manifest.get('original_sha256'):
        raise ReplacementError('Original backup failed integrity validation. Nothing was modified.')
    if _hash_bytes(target.read_bytes()) != manifest.get('installed_sha256'):
        raise ReplacementError("The installed game archive was modified externally. Refusing to erase someone else's changes.")
    _write_atomically(target, original_bytes)
    manifest['status'] = 'restored'
    _write_atomically(manifest_path, json.dumps(manifest, indent=2).encode('utf-8'))
    return InstallResult(target, backup_path, 'restored')
