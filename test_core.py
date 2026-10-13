"""Offline core tests; use: python -m unittest discover -v"""
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import trimesh
from PIL import Image

from skaterxl_core import (
    AssetKey, BundleResolver, Indexer, MissingAsset, SceneExtractor,
    connect_db, convert_transform, decode_mesh, decode_texture_image, export_glb, export_png, local_transform,
    query_assets, unity_name, game_data_path,
)


class FakeReader:
    def __init__(self, typ, path_id, value, assets_file, name=None):
        self.type = types.SimpleNamespace(name=typ)
        self.path_id = path_id
        self._value = value
        self.assets_file = assets_file
        self._name = name
    def parse_as_object(self):
        return self._value
    def peek_name(self):
        return self._name


class PPtr:
    def __init__(self, fileid=0, pathid=0):
        self.m_FileID = fileid
        self.m_PathID = pathid


def component(ptr):
    return types.SimpleNamespace(component=ptr)


def vec(x=0, y=0, z=0):
    return types.SimpleNamespace(x=x, y=y, z=z)


def quat():
    return types.SimpleNamespace(x=0, y=0, z=0, w=1)


def go(name, *components):
    return types.SimpleNamespace(m_Name=name, m_Component=[component(PPtr(0, c)) for c in components])


def trans(go_id, children=(), x=0):
    return types.SimpleNamespace(m_GameObject=PPtr(0, go_id), m_Children=list(children),
        m_LocalPosition=vec(x=x), m_LocalScale=vec(1, 1, 1), m_LocalRotation=quat())


class FakeMeshHandler:
    def __init__(self, value):
        self.value = value
        self.m_Vertices = None
    def process(self):
        self.m_Vertices = [(0, 0, 0), (0, 1, 0), (1, 0, 0)]
        self.m_Normals = [(0, 0, 1)] * 3
        self.m_UV0 = [(0, 0), (0, 1), (1, 0)]
        self.m_Colors = None
    def get_triangles(self):
        return [[(0, 1, 2)]]


class TestCore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        a = self.root / "gear_assets_mshoesesaccel.bundle"
        b = self.root / "other_shoe_mesh.bundle"
        a.write_bytes(b"UnityFS-test1")
        b.write_bytes(b"UnityFS-test2")
        cab_a = types.SimpleNamespace(name="CAB-PREFAB", externals=[types.SimpleNamespace(path="archive:/other_shoe_mesh.bundle/CAB-MESH")], objects={})
        cab_b = types.SimpleNamespace(name="CAB-MESH", externals=[], objects={})
        def add(file, typ, pid, val, name=None):
            file.objects[pid] = FakeReader(typ, pid, val, file, name)
        add(cab_a, "GameObject", 10, go("ESAccel", 11), "ESAccel")
        add(cab_a, "Transform", 11, trans(10, [PPtr(0, 21), PPtr(0, 31)]))
        add(cab_a, "GameObject", 20, go("ESAccel_L", 21, 22), "ESAccel_L")
        add(cab_a, "Transform", 21, trans(20, x=1))
        add(cab_a, "SkinnedMeshRenderer", 22, types.SimpleNamespace(m_Mesh=PPtr(1, 200), m_Materials=[]))
        add(cab_a, "GameObject", 30, go("ESAccel_R", 31, 32), "ESAccel_R")
        add(cab_a, "Transform", 31, trans(30, x=-1))
        add(cab_a, "SkinnedMeshRenderer", 32, types.SimpleNamespace(m_Mesh=PPtr(1, 201), m_Materials=[]))
        add(cab_b, "Mesh", 200, types.SimpleNamespace(m_Name="ESAccel_L"), "ESAccelMeshL")
        add(cab_b, "Mesh", 201, types.SimpleNamespace(m_Name="ESAccel_R"), "ESAccelMeshR")
        self.data = {
            str(a): types.SimpleNamespace(assets=[cab_a]),
            str(b): types.SimpleNamespace(assets=[cab_b]),
        }
        self.loaded = []
        def load(path):
            self.loaded.append(path)
            return self.data[path]
        unitypy = types.ModuleType("UnityPy")
        unitypy.load = load
        helpers = types.ModuleType("UnityPy.helpers")
        mesh_module = types.ModuleType("UnityPy.helpers.MeshHelper")
        mesh_module.MeshHandler = FakeMeshHandler
        self.patch = patch.dict(sys.modules, {
            "UnityPy": unitypy, "UnityPy.helpers": helpers,
            "UnityPy.helpers.MeshHelper": mesh_module,
        })
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.db = self.root / "index.sqlite"

    def test_scan_cache_and_query(self):
        progress = []
        complete = Indexer(self.root, self.db).scan(lambda *args: progress.append(args))
        self.assertEqual(complete, (2, 2, 0))
        keys, count = query_assets(self.db, "esaccel", "All")
        self.assertEqual(count, 10)
        self.assertTrue(any(k.type == "Mesh" for k in keys))
        self.assertTrue(any(k.type == "GameObject" for k in keys))
        self.assertEqual(Indexer(self.root, self.db).scan(), (2, 0, 0))
        self.assertEqual(len(self.loaded), 2)
        self.assertEqual(len(progress), 1)

    def test_cross_bundle_scene_and_glb(self):
        Indexer(self.root, self.db).scan()
        matches, _ = query_assets(self.db, "ESAccel", "GameObject")
        key = next(k for k in matches if k.name == "ESAccel")
        scene, warnings = SceneExtractor(BundleResolver(self.db)).extract(key)
        self.assertEqual(len(scene.geometry), 2)
        self.assertTrue(any("static" in w for w in warnings))
        expected_x = []
        for node in scene.graph.nodes_geometry:
            mat, mesh_name = scene.graph.get(node)
            self.assertEqual(len(scene.geometry[mesh_name].faces), 1)
            world_pts = scene.geometry[mesh_name].vertices @ mat[:3, :3].T + mat[:3, 3]
            expected_x.append(round(world_pts[:, 0].mean(), 2))
        self.assertEqual(sorted(expected_x), [-1.33, 0.67])
        output = self.root / "test.glb"
        export_glb(scene, output)
        self.assertGreater(output.stat().st_size, 100)
        loaded = trimesh.load(output, force="scene")
        self.assertEqual(len(loaded.geometry), 2)

    def test_missing_cab_error(self):
        Indexer(self.root, self.db).scan()
        conn = connect_db(self.db)
        try:
            conn.execute("DELETE FROM cabs WHERE cab='cab-mesh'")
            conn.commit()
        finally:
            conn.close()
        key = next(k for k in query_assets(self.db, "ESAccel", "GameObject")[0] if k.name == "ESAccel")
        with self.assertRaises(MissingAsset) as raised:
            SceneExtractor(BundleResolver(self.db)).extract(key)
        self.assertIn("cab-mesh", str(raised.exception))
        self.assertIn("full SkaterXL_Data", str(raised.exception))

    def test_game_data_path_finds_parent(self):
        skater_data = self.root / "SkaterXL_Data"
        nested = skater_data / "StreamingAssets" / "aa" / "Windows" / "StandaloneWindows64"
        nested.mkdir(parents=True)
        self.assertTrue(game_data_path(nested).samefile(skater_data))
        self.assertTrue(game_data_path(self.root).samefile(skater_data))

    def test_png_export_preserves_rgba_and_pixels(self):
        image = Image.new("RGBA", (64, 32), (14, 80, 216, 113))
        image.putpixel((5, 10), (242, 5, 7, 0))
        path = self.root / "exported_texture.png"
        export_png(image, path)
        self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        with Image.open(path) as loaded:
            self.assertEqual(loaded.size, (64, 32))
            self.assertEqual(loaded.mode, "RGBA")
            self.assertEqual(loaded.getpixel((0, 0)), (14, 80, 216, 113))
            self.assertEqual(loaded.getpixel((5, 10)), (242, 5, 7, 0))
        self.assertEqual(image.getpixel((5, 10)), (242, 5, 7, 0))
        self.assertEqual(list(self.root.glob("skaterxl_tex_*")), [])

    def test_texture_decode_then_export(self):
        source = Image.new("RGB", (4, 8), (21, 63, 124))
        reader = FakeReader("Texture2D", 501, types.SimpleNamespace(image=source), None, "ShoeAlbedo")
        decoded = decode_texture_image(reader)
        self.assertEqual(decoded.size, (4, 8))
        self.assertIsNot(decoded, source)
        export_png(decoded, self.root / "decoded.png")
        with Image.open(self.root / "decoded.png") as imported:
            self.assertEqual(imported.getpixel((1, 1)), (21, 63, 124))

    def test_png_export_errors_leave_existing_file_untouched(self):
        target = self.root / "already_there.png"
        target.write_bytes(b"original-data")
        with self.assertRaises(ValueError):
            export_png(None, target)
        self.assertEqual(target.read_bytes(), b"original-data")
        with self.assertRaises(ValueError):
            export_png(Image.new("RGBA", (2, 2)), self.root / "wrong_extension.jpg")
        self.assertFalse((self.root / "wrong_extension.jpg").exists())
        reader = FakeReader("Texture2D", 502, types.SimpleNamespace(image=None), None)
        with self.assertRaisesRegex(ValueError, "no readable pixels"):
            decode_texture_image(reader)

    def test_quaternion_matrix_and_normals(self):
        M = local_transform(trans(0, x=2))
        self.assertTrue(np.allclose(convert_transform(M)[:3, 3], [-2, 0, 0]))
        source = self.data[list(self.data)[1]].assets[0].objects[200]
        meshes = decode_mesh(source)
        self.assertEqual(len(meshes), 1)
        self.assertEqual(len(meshes[0].faces), 1)
        self.assertEqual(len(meshes[0].visual.uv), 3)


if __name__ == "__main__":
    unittest.main()
