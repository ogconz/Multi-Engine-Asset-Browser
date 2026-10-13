"""Read-only Skater XL Unity asset index, cross-bundle resolver, and static mesh export.

The game files are never modified. Tested with mock UnityPy assets; real UnityPy and
Windows graphical testing are required on the target installation.
"""
from __future__ import annotations

import os
import ntpath
import hashlib
import sqlite3
import subprocess
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import trimesh
from trimesh.visual.texture import TextureVisuals
from trimesh.visual.material import PBRMaterial

MODEL_TYPES = ("Mesh", "GameObject", "SkinnedMeshRenderer", "MeshFilter", "MeshRenderer")
IMAGE_TYPES = ("Texture2D", "Sprite")
SUFFIXES = {".bundle", ".unity3d", ".assets", ".asset", ".unity"}
LIMIT = 1500


def unity_name(name) -> str:
    return ntpath.basename(str(name or "").replace("/", "\\")).lower()


def game_data_path(folder: str | Path) -> Path:
    root = Path(folder).expanduser().resolve()
    if (root / "SkaterXL_Data").is_dir():
        return root / "SkaterXL_Data"
    # If the user selects the nested AA/Windows folder, search upwards for the
    # proper game-data root so CAB dependencies in other folders are included.
    for candidate in (root, *root.parents):
        if candidate.name.lower() == "skaterxl_data" and candidate.is_dir():
            return candidate
    return root


def is_container(path: Path) -> bool:
    name = path.name.lower()
    return (
        path.suffix.lower() in SUFFIXES
        or name == "globalgamemanagers"
        or (name.startswith("level") and name[5:].isdigit())
    )


def find_containers(root: Path) -> list[Path]:
    matches = []
    for base, dirs, filenames in os.walk(root):
        # Prevent accidentally scanning giant loose mod caches or backups.
        dirs[:] = [x for x in dirs if x.lower() not in {"__pycache__", ".git"}]
        for filename in filenames:
            p = Path(base) / filename
            if is_container(p):
                matches.append(p)
    return sorted(matches, key=lambda p: str(p).lower())


def default_cache_path(root: Path) -> Path:
    key = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()[:18]
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache"))) / "SkaterXLAssetBrowser"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"index_{key}.sqlite3"


def connect_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=20000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bundles (
            path TEXT PRIMARY KEY, file_size INTEGER NOT NULL, modified_ns INTEGER NOT NULL,
            scan_id INTEGER NOT NULL, error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS cabs (
            cab TEXT NOT NULL, bundle TEXT NOT NULL,
            PRIMARY KEY(cab, bundle)
        );
        CREATE INDEX IF NOT EXISTS cabs_by_bundle ON cabs(bundle);
        CREATE TABLE IF NOT EXISTS assets (
            bundle TEXT NOT NULL, cab TEXT NOT NULL, path_id INTEGER NOT NULL,
            type TEXT NOT NULL, name TEXT NOT NULL,
            PRIMARY KEY(bundle, cab, path_id)
        );
        CREATE INDEX IF NOT EXISTS assets_by_type ON assets(type);
        CREATE INDEX IF NOT EXISTS assets_by_bundle ON assets(bundle);
        CREATE INDEX IF NOT EXISTS assets_by_name ON assets(name COLLATE NOCASE);
    """)
    return conn


@dataclass(frozen=True)
class AssetKey:
    bundle: str
    cab: str
    path_id: int
    type: str
    name: str


class MissingAsset(RuntimeError):
    """A referenced Unity serialized file or PathID is missing from the index."""


class Indexer:
    """Scan each Unity container one at a time, caching metadata in SQLite."""

    def __init__(self, root: Path, db_path: Path):
        self.root, self.db_path = root, db_path

    def scan(
        self, progress: Optional[Callable[[int, int, int, int, str], None]] = None,
        cancel: Optional[threading.Event] = None,
    ) -> tuple[int, int, int]:
        import UnityPy

        files = find_containers(self.root)
        completed = 0
        errors = 0
        new_files = 0
        scan_id = int(__import__("time").time_ns())
        conn = connect_db(self.db_path)
        try:
            for path in files:
                if cancel and cancel.is_set():
                    break
                bundle_path = str(path)
                try:
                    stat = path.stat()
                    prev = conn.execute(
                        "SELECT file_size,modified_ns,error FROM bundles WHERE path=?", (bundle_path,)
                    ).fetchone()
                    if prev and prev[0] == stat.st_size and prev[1] == stat.st_mtime_ns and not prev[2]:
                        conn.execute("UPDATE bundles SET scan_id=? WHERE path=?", (scan_id, bundle_path))
                    else:
                        env = UnityPy.load(bundle_path)
                        rows = []
                        cab_rows = []
                        for assets_file in env.assets:
                            cab = unity_name(getattr(assets_file, "name", path.name))
                            cab_rows.append((cab, bundle_path))
                            for obj in assets_file.objects.values():
                                typ = obj.type.name
                                try:
                                    name = str(obj.peek_name()) if typ in (
                                        "Mesh", "GameObject", "Material", "Texture2D", "Sprite",
                                        "TextAsset", "AudioClip", "Shader", "AnimationClip", "MonoBehaviour",
                                        "AnimatorController", "Font", "Avatar", "Cubemap",
                                    ) else ""
                                except Exception:
                                    name = ""
                                name = name.strip() or f"<{typ} #{int(obj.path_id)}>"
                                rows.append((bundle_path, cab, int(obj.path_id), typ, name))
                        # Replace only after a bundle was decoded successfully.
                        with conn:
                            conn.execute("DELETE FROM assets WHERE bundle=?", (bundle_path,))
                            conn.execute("DELETE FROM cabs WHERE bundle=?", (bundle_path,))
                            conn.executemany("INSERT INTO assets VALUES (?,?,?,?,?)", rows)
                            conn.executemany("INSERT OR IGNORE INTO cabs VALUES (?,?)", cab_rows)
                            conn.execute(
                                "INSERT OR REPLACE INTO bundles VALUES (?,?,?,?,?)",
                                (bundle_path, stat.st_size, stat.st_mtime_ns, scan_id, ""),
                            )
                        new_files += 1
                        del env
                except Exception as exc:
                    errors += 1
                    error_text = f"{type(exc).__name__}: {exc}"
                    try:
                        stat = path.stat()
                        with conn:
                            conn.execute("DELETE FROM assets WHERE bundle=?", (bundle_path,))
                            conn.execute("DELETE FROM cabs WHERE bundle=?", (bundle_path,))
                            conn.execute(
                                "INSERT OR REPLACE INTO bundles VALUES (?,?,?,?,?)",
                                (bundle_path, stat.st_size, stat.st_mtime_ns, scan_id, error_text[:600]),
                            )
                    except OSError:
                        pass
                completed += 1
                if progress and (completed % 10 == 0 or completed == len(files)):
                    progress(completed, len(files), new_files, errors, path.name)
            # Prune only after a FULL scan (cancellation must keep the prior cache).
            if not (cancel and cancel.is_set()):
                with conn:
                    conn.execute("DELETE FROM assets WHERE bundle IN (SELECT path FROM bundles WHERE scan_id!=?)", (scan_id,))
                    conn.execute("DELETE FROM cabs WHERE bundle IN (SELECT path FROM bundles WHERE scan_id!=?)", (scan_id,))
                    conn.execute("DELETE FROM bundles WHERE scan_id!=?", (scan_id,))
            return completed, new_files, errors
        finally:
            conn.close()


def query_assets(db_path: Path, search: str = "", typ: str = "All", limit: int = LIMIT):
    if not db_path.is_file():
        return [], 0
    conn = connect_db(db_path)
    try:
        where, params = [], []
        if typ != "All":
            if typ == "3D candidates":
                where.append("type IN (?,?,?,?,?)")
                params.extend(MODEL_TYPES)
            else:
                where.append("type=?")
                params.append(typ)
        if search.strip():
            # The raw percent/underscore wildcards are escaped to make searches literal.
            term = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("(name LIKE ? ESCAPE '\\' OR bundle LIKE ? ESCAPE '\\' OR cab LIKE ? ESCAPE '\\')")
            params.extend([f"%{term}%"] * 3)
        clause = "WHERE " + " AND ".join(where) if where else ""
        count = conn.execute(f"SELECT COUNT(*) FROM assets {clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT bundle,cab,path_id,type,name FROM assets {clause} "
            "ORDER BY name COLLATE NOCASE, type LIMIT ?", [*params, int(limit)]
        ).fetchall()
        return [AssetKey(**dict(r)) for r in rows], count
    finally:
        conn.close()


def known_types(db_path: Path) -> list[str]:
    if not db_path.is_file():
        return []
    conn = connect_db(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT type FROM assets ORDER BY type")]
    finally:
        conn.close()


def error_summary(db_path: Path, limit: int = 8) -> list[str]:
    if not db_path.is_file():
        return []
    conn = connect_db(db_path)
    try:
        return [f"{Path(r[0]).name}: {r[1]}" for r in conn.execute(
            "SELECT path,error FROM bundles WHERE error!='' LIMIT ?", (limit,)
        )]
    finally:
        conn.close()


def _pptr_id(ptr) -> int:
    return int(getattr(ptr, "m_PathID", 0) or 0)


def _attr(obj, attr: str, default=None):
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


class BundleResolver:
    """Resolve references across separately packaged Unity CABs, even in other folders."""

    def __init__(self, db_path: Path, max_loaded: int = 4):
        self.cabs = {}
        self._loaded: OrderedDict[str, object] = OrderedDict()
        self.max_loaded = max_loaded
        conn = connect_db(db_path)
        try:
            for row in conn.execute("SELECT cab,bundle FROM cabs ORDER BY bundle"):
                self.cabs.setdefault(unity_name(row[0]), row[1])
        finally:
            conn.close()

    def load_bundle(self, filename: str):
        if filename in self._loaded:
            self._loaded.move_to_end(filename)
            return self._loaded[filename]
        import UnityPy

        env = UnityPy.load(filename)
        self._loaded[filename] = env
        if len(self._loaded) > self.max_loaded:
            self._loaded.popitem(last=False)
        return env

    def get_file(self, cab: str, bundle_hint: Optional[str] = None):
        cab_norm = unity_name(cab)
        location = bundle_hint or self.cabs.get(cab_norm)
        if not location:
            raise MissingAsset(f"Missing dependency: {cab}. Scan the full SkaterXL_Data directory.")
        env = self.load_bundle(location)
        for file in env.assets:
            if unity_name(getattr(file, "name", "")) == cab_norm:
                return file
        if len(env.assets) == 1:
            return env.assets[0]
        raise MissingAsset(f"CAB '{cab}' was not found inside {Path(location).name}.")

    def lookup(self, key: AssetKey):
        file = self.get_file(key.cab, key.bundle)
        result = file.objects.get(key.path_id)
        if result is None:
            raise MissingAsset(f"Object Path ID {key.path_id} not found in CAB {key.cab}.")
        return result

    def resolve(self, owner_reader, ptr):
        """owner_reader is the reader containing this PPtr, NOT its target."""
        path_id = _pptr_id(ptr)
        if path_id == 0:
            return None
        fileid = int(getattr(ptr, "m_FileID", 0) or 0)
        owner_file = owner_reader.assets_file
        if fileid == 0:
            target_file = owner_file
        else:
            external_index = fileid - 1
            externals = owner_file.externals
            if external_index < 0 or external_index >= len(externals):
                raise MissingAsset(f"Invalid external file ID {fileid} (mesh Path ID {path_id}).")
            filename = externals[external_index].path
            name = unity_name(filename)
            if name not in self.cabs:
                raise MissingAsset(
                    f"Unresolved CAB: {name}\nMesh/object Path ID: {path_id}\n"
                    "The reference points outside the scanned assets. "
                    "Choose the full SkaterXL_Data folder and scan again."
                )
            target_file = self.get_file(name)
        result = target_file.objects.get(path_id)
        if result is None:
            raise MissingAsset(
                f"Missing Path ID {path_id} in {getattr(target_file, 'name', '?')}. "
                "The dependent asset may be absent or have a different game version."
            )
        return result


def _vec3(value, default):
    if value is None:
        return np.asarray(default, dtype=float)
    if hasattr(value, "x"):
        return np.asarray([value.x, value.y, value.z], dtype=float)
    return np.asarray(list(value)[:3], dtype=float)


def _quat4(value):
    if value is None:
        return [0.0, 0.0, 0.0, 1.0]
    if hasattr(value, "w"):
        return [value.x, value.y, value.z, value.w]
    return list(value)[:4]


def local_transform(transform) -> np.ndarray:
    """Unity transform matrix in Unity's left-handed coordinate system."""
    qx, qy, qz, qw = [float(v) for v in _quat4(_attr(transform, "m_LocalRotation"))]
    norm = np.linalg.norm([qw, qx, qy, qz])
    if norm < 1e-12:
        rotation = np.eye(4)
    else:
        rotation = trimesh.transformations.quaternion_matrix([qw/norm, qx/norm, qy/norm, qz/norm])
    scale = np.eye(4)
    scale[:3, :3] = np.diag(_vec3(_attr(transform, "m_LocalScale"), [1, 1, 1]))
    translation = trimesh.transformations.translation_matrix(
        _vec3(_attr(transform, "m_LocalPosition"), [0, 0, 0])
    )
    return translation @ rotation @ scale


# Blender and the glTF ecosystem use right-handed coordinates.
FLIP_X = np.diag([-1.0, 1.0, 1.0, 1.0])


def convert_transform(unity_matrix: np.ndarray) -> np.ndarray:
    return FLIP_X @ unity_matrix @ FLIP_X


def _color_rgba(value):
    try:
        vals = [float(_attr(value, k)) for k in ("r", "g", "b", "a")]
        return [max(0, min(255, round(v * (255 if max(vals) <= 1.00001 else 1)))) for v in vals]
    except Exception:
        return None


def load_material(resolver: BundleResolver, renderer_reader, material_ptr):
    """Extract diffuse texture when possible; unsupported Unity shaders fall back to gray."""
    if not material_ptr or _pptr_id(material_ptr) == 0:
        return None
    try:
        material_reader = resolver.resolve(renderer_reader, material_ptr)
        material = material_reader.parse_as_object()
        props = _attr(material, "m_SavedProperties")
        if props is None:
            return None
        color = None
        for name, c in _attr(props, "m_Colors", []) or []:
            if str(name).lower().strip() in {"_color", "_basecolor"}:
                color = _color_rgba(c)
                break
        entries = []
        for name, tex_env in _attr(props, "m_TexEnvs", []) or []:
            s = str(name).lower()
            # Only color textures, not normals/roughness/etc.
            rank = 0 if any(x in s for x in ("maintex", "basemap", "albedo", "basecolor", "diffuse")) else 1
            if any(x in s for x in ("bump", "normal", "metal", "rough", "occl", "mask")):
                continue
            entries.append((rank, name, _attr(tex_env, "m_Texture")))
        entries.sort(key=lambda e: e[0])
        for _rank, _name, ptr in entries:
            if _pptr_id(ptr) == 0:
                continue
            try:
                reader = resolver.resolve(material_reader, ptr)
                image = reader.parse_as_object().image
                if image is not None:
                    # Avoid lazy image references to an evicted UnityPy environment.
                    return PBRMaterial(
                        name=str(_attr(material, "m_Name", "UnityMaterial")),
                        baseColorTexture=image.convert("RGBA").copy(),
                        baseColorFactor=color or [255, 255, 255, 255],
                    )
            except Exception:
                continue
        return PBRMaterial(
            name=str(_attr(material, "m_Name", "UnityMaterial")),
            baseColorFactor=color or [190, 195, 205, 255],
        )
    except Exception:
        return None


def decode_mesh(reader, materials=None) -> list[trimesh.Trimesh]:
    """UnityPy MeshHandler supports compressed meshes, submeshes, UVs, and normals."""
    from UnityPy.helpers.MeshHelper import MeshHandler

    data = reader.parse_as_object()
    handler = MeshHandler(data)
    handler.process()
    if not handler.m_Vertices:
        return []
    vertices = np.asarray(handler.m_Vertices, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] < 3:
        raise ValueError("Mesh has invalid vertex data")
    vertices = vertices[:, :3].copy()
    vertices[:, 0] *= -1  # Unity (LH) -> glTF / Blender (RH)
    vertices = np.nan_to_num(vertices, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    normals = None
    if handler.m_Normals is not None and len(handler.m_Normals) == len(vertices):
        normals = np.asarray(handler.m_Normals, dtype=float)[:, :3].copy()
        normals[:, 0] *= -1
    uvs = None
    if handler.m_UV0 is not None and len(handler.m_UV0) == len(vertices):
        uvs = np.asarray(handler.m_UV0, dtype=float)[:, :2].copy()
    colors = None
    if handler.m_Colors is not None and len(handler.m_Colors) == len(vertices):
        colors = np.clip(np.asarray(handler.m_Colors, dtype=float)[:, :4] * 255, 0, 255).astype(np.uint8)
    pieces = []
    for i, group in enumerate(handler.get_triangles()):
        if not group:
            continue
        faces = np.asarray(group, dtype=np.int64)
        if faces.ndim != 2 or faces.shape[1] != 3:
            continue
        faces = faces[:, ::-1].copy()  # Reverse winding after mirroring x
        good = (faces >= 0).all(axis=1) & (faces < len(vertices)).all(axis=1)
        faces = faces[good]
        if not len(faces):
            continue
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        if normals is not None:
            try:
                mesh.vertex_normals = normals
            except Exception:
                pass
        mat = materials[i] if materials is not None and i < len(materials) else None
        if uvs is not None:
            mesh.visual = TextureVisuals(uv=uvs.copy(), material=mat or PBRMaterial())
        elif colors is not None:
            mesh.visual.vertex_colors = colors
        elif mat is not None:
            mesh.visual = TextureVisuals(material=mat)
        mesh.metadata["submesh"] = i
        pieces.append(mesh)
    return pieces


class SceneExtractor:
    """Build a *static* trimesh.Scene from Unity meshes and GameObject hierarchies."""

    def __init__(self, resolver: BundleResolver):
        self.resolver = resolver
        self.messages: list[str] = []
        self._seen = set()
        self.scene = trimesh.Scene()
        self.geometry_count = 0
        self.node_count = 0

    def _build_reader(self, key: AssetKey):
        return self.resolver.lookup(key)

    def _add_mesh(self, mesh_reader, label: str, unity_xform: np.ndarray, material_ptrs=None, renderer_reader=None):
        mats = None
        if renderer_reader and material_ptrs:
            mats = [load_material(self.resolver, renderer_reader, ptr) for ptr in material_ptrs]
        try:
            pieces = decode_mesh(mesh_reader, mats)
        except Exception as e:
            self.messages.append(f"Failed mesh {label}: {type(e).__name__}: {e}")
            return
        for i, mesh in enumerate(pieces):
            idx = self.geometry_count
            self.scene.add_geometry(
                mesh,
                geom_name=f"{label}_sub{i}_{idx}",
                node_name=f"{label}_sub{i}_{idx}",
                transform=convert_transform(unity_xform),
            )
            self.geometry_count += 1

    def _visit_game_object(self, reader, parent_matrix, depth=0):
        if depth > 100 or self.node_count > 3000:
            self.messages.append("Object hierarchy too deep/large; stopped traversing.")
            return
        fingerprint = (unity_name(reader.assets_file.name), reader.path_id)
        if fingerprint in self._seen:
            return
        self._seen.add(fingerprint)
        self.node_count += 1
        game_object = reader.parse_as_object()
        obj_name = str(_attr(game_object, "m_Name", f"GameObject_{reader.path_id}"))
        components = []
        for pair in _attr(game_object, "m_Component", []) or []:
            ptr = pair[1] if isinstance(pair, (tuple, list)) else _attr(pair, "component", _attr(pair, "m_Component"))
            if not ptr or _pptr_id(ptr) == 0:
                continue
            try:
                component_reader = self.resolver.resolve(reader, ptr)
                components.append((component_reader.type.name, component_reader, component_reader.parse_as_object()))
            except Exception as e:
                self.messages.append(f"{obj_name}: component not found: {e}")
        transform_info = next(((r, d) for typ, r, d in components if typ in ("Transform", "RectTransform")), None)
        own_matrix = parent_matrix
        if transform_info:
            _trans_reader, transform = transform_info
            own_matrix = parent_matrix @ local_transform(transform)
        mesh_filter = next(((r, d) for typ, r, d in components if typ == "MeshFilter"), None)
        mesh_renderer = next(((r, d) for typ, r, d in components if typ == "MeshRenderer"), None)
        if mesh_filter:
            filter_reader, filter_obj = mesh_filter
            ref = _attr(filter_obj, "m_Mesh")
            if _pptr_id(ref):
                try:
                    mesh_reader = self.resolver.resolve(filter_reader, ref)
                    render_reader, render_obj = mesh_renderer if mesh_renderer else (None, None)
                    self._add_mesh(
                        mesh_reader, obj_name, own_matrix,
                        _attr(render_obj, "m_Materials", []) if render_obj else [], render_reader,
                    )
                except MissingAsset as e:
                    self.messages.append(f"{obj_name}: {e}")
        for typ, renderer_reader, renderer in components:
            if typ != "SkinnedMeshRenderer":
                continue
            mesh_ptr = _attr(renderer, "m_Mesh")
            if not _pptr_id(mesh_ptr):
                continue
            try:
                mesh_reader = self.resolver.resolve(renderer_reader, mesh_ptr)
                self._add_mesh(
                    mesh_reader, obj_name, own_matrix,
                    _attr(renderer, "m_Materials", []), renderer_reader,
                )
                self.messages.append("SkinnedMeshRenderer: static bind/rest-pose geometry only (no rig/animation).")
            except MissingAsset as e:
                self.messages.append(f"{obj_name}: {e}")
        if transform_info:
            trans_reader, transform = transform_info
            for child_ptr in _attr(transform, "m_Children", []) or []:
                if not _pptr_id(child_ptr):
                    continue
                try:
                    child_trans_reader = self.resolver.resolve(trans_reader, child_ptr)
                    child_trans = child_trans_reader.parse_as_object()
                    child_go_ptr = _attr(child_trans, "m_GameObject")
                    child_go_reader = self.resolver.resolve(child_trans_reader, child_go_ptr)
                    if child_go_reader:
                        self._visit_game_object(child_go_reader, own_matrix, depth+1)
                except Exception as e:
                    self.messages.append(f"{obj_name}: missing child: {e}")

    def extract(self, key: AssetKey):
        reader = self._build_reader(key)
        identity = np.eye(4)
        if key.type == "Mesh":
            self._add_mesh(reader, key.name, identity)
        elif key.type == "GameObject":
            self._visit_game_object(reader, identity)
        elif key.type in ("MeshFilter", "MeshRenderer", "SkinnedMeshRenderer"):
            obj = reader.parse_as_object()
            go_ptr = _attr(obj, "m_GameObject")
            if not _pptr_id(go_ptr):
                raise MissingAsset("Selected component does not reference a GameObject.")
            go_reader = self.resolver.resolve(reader, go_ptr)
            self._visit_game_object(go_reader, identity)
        else:
            raise ValueError(f"{key.type} is not a 3D asset. Select a Mesh or GameObject.")
        if self.geometry_count == 0:
            details = "\n".join(dict.fromkeys(self.messages))
            raise MissingAsset(
                "No triangles could be extracted from this asset.\n\n"
                + (details or "This GameObject may be an empty/prefab-only hierarchy. ")
                + "\n\nTip: scan the entire SkaterXL_Data folder, not only one bundle."
            )
        return self.scene, list(dict.fromkeys(self.messages))


def decode_texture_image(reader):
    """Decode Texture2D / Sprite pixels and detach them from UnityPy's bundle lifetime.

    UnityPy normally exposes a PIL Image through its image property. External
    streaming resources or unsupported texture codecs can cause decoding to fail.
    """
    if reader.type.name not in IMAGE_TYPES:
        raise ValueError(f"{reader.type.name} is not a texture or sprite")
    try:
        image = reader.parse_as_object().image
        if image is None:
            raise ValueError("This texture has no readable pixels")
        image.load()
        return image.copy()
    except Exception as exc:
        raise ValueError(
            f"Cannot decode {reader.type.name} pixels: {exc}. "
            "The texture might use an unsupported compression format or external stream data."
        ) from exc


def export_png(image, target: str | Path) -> None:
    """Save original-size decoded texture pixels as PNG, without modifying game files.

    Atomic replacement avoids leaving half-written exports. RGBA, grayscale,
    palette transparency and 16-bit grayscale images are kept where supported.
    """
    if image is None:
        raise ValueError("Cannot export PNG: no decoded texture image")
    output = Path(target)
    if output.suffix.lower() != ".png":
        raise ValueError("PNG export requires a .png output filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    if image.mode not in {"1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16", "I;16B", "I;16L"}:
        image = image.convert("RGBA")
    fd, path = tempfile.mkstemp(prefix="skaterxl_tex_", suffix=".png", dir=str(output.parent))
    os.close(fd)
    try:
        image.save(path, format="PNG")
        with open(path, "rb") as check:
            if check.read(8) != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError("PNG encoder did not produce a valid PNG header")
        os.replace(path, output)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def export_glb(scene: trimesh.Scene, target: str | Path) -> None:
    if not scene.geometry:
        raise ValueError("The scene is empty; refusing to export an empty GLB")
    output = Path(target)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: don't leave a corrupted export if the user cancels/retries.
    fd, path = tempfile.mkstemp(prefix="skaterxl_", suffix=".glb", dir=str(output.parent))
    os.close(fd)
    try:
        scene.export(path, file_type="glb")
        if os.path.getsize(path) < 128:
            raise RuntimeError("GLB export unexpectedly small")
        os.replace(path, output)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def export_fbx(scene: trimesh.Scene, output: str | Path, blender_exe: str | Path, converter: Path) -> None:
    blender = Path(blender_exe)
    if not blender.is_file():
        raise FileNotFoundError(f"Blender not found: {blender}")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="skaterxl_fbx_") as tmp:
        input_glb = Path(tmp) / "source.glb"
        intermediate_fbx = Path(tmp) / "result.fbx"
        export_glb(scene, input_glb)
        cmd = [str(blender), "--background", "--factory-startup", "--python", str(converter),
               "--", str(input_glb), str(intermediate_fbx)]
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=300)
        if result.returncode != 0 or not intermediate_fbx.is_file() or intermediate_fbx.stat().st_size == 0:
            msg = (result.stderr or "")[-2500:] + "\n" + (result.stdout or "")[-2500:]
            raise RuntimeError("Blender FBX conversion failed:\n" + msg)
        os.replace(intermediate_fbx, target)


def find_blender_exe() -> Optional[str]:
    import shutil
    via_path = shutil.which("blender")
    if via_path:
        return via_path
    if os.name == "nt":
        base = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Blender Foundation"
        if base.is_dir():
            options = sorted(base.glob("Blender */blender.exe"), reverse=True)
            if options:
                return str(options[0])
    return None
