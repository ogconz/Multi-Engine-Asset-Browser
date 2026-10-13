"""Offline integration checks for Unreal PAK browser backend.

Mocks the third-party PAK reader and UModel executable so no game assets or
Windows dependencies are needed to validate indexing, dispatch, PNG and GLB.
"""
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import trimesh
from PIL import Image

from multi_core import detect_engine, ui_can_export, ui_can_preview
from skaterxl_core import export_glb, export_png
from unreal_core import (
    UE_PACKAGE_TYPE, UnrealAsset, UnrealExtractor, UnrealIndexer, UnrealAutoInspector,
    find_ue_containers, parse_umodel_list, pending_unreal_packages, query_unreal_assets,
    save_inspected_objects, umodel_package_selector, unreal_default_cache_path,
    unreal_inspection_errors, unreal_known_types, valid_aes_key,
)


class FakePak:
    reads = []
    def __init__(self):
        self.key = ''
    def set_key(self, key):
        self.key = key
    def read(self, path):
        self.reads.append(path)
    def list_files(self):
        return [
            '../../../SessionGame/Content/Shoes/SM_Shoe.uasset',
            '../../../SessionGame/Content/Shoes/T_Shoe.uasset',
            '../../../SessionGame/Content/Shoes/T_Shoe.uexp',
            '../../../SessionGame/Content/Maps/Map.umap',
            '../../../SessionGame/Content/Shoes/SM_Shoe.uasset',
        ]


def fake_umodel_export(args, **kwargs):
    if '-list' in args:
        return subprocess.CompletedProcess(args, 0, '''\nUMODEL: package loaded\n   0      11F     1020 StaticMesh SM_Shoe\n   1     1234     20FF Texture2D T_Shoe\n   2        0        0 Material M_Shoe\n''', '')
    assert '-export' in args
    output = Path(next(s[5:] for s in args if s.startswith('-out=')))
    output.mkdir(parents=True, exist_ok=True)
    obj = args[-2] if args[-1] in ('StaticMesh', 'SkeletalMesh', 'Texture2D') else None
    if obj == 'T_Shoe':
        Image.new('RGBA', (19, 17), (127, 50, 60, 72)).save(output / 'T_Shoe.png')
    else:
        scene = trimesh.Scene()
        scene.add_geometry(trimesh.creation.box(), node_name='SM_Shoe')
        payload = trimesh.exchange.gltf.export_gltf(scene)
        for filename, data in payload.items():
            (output / filename).write_bytes(data)
    return subprocess.CompletedProcess(args, 0, 'Exported assets', '')


class UnrealTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'SessionGame' / 'Content' / 'Paks').mkdir(parents=True)
        self.pak = self.root / 'SessionGame' / 'Content' / 'Paks' / 'pakchunk0-WindowsNoEditor.pak'
        self.pak.write_bytes(b'PAK mock bytes')
        self.db = self.root / 'unreal.sqlite3'
        self.umodel = self.root / 'umodel.exe'
        self.umodel.write_bytes(b'dummy executable placeholder')
        self.fake_module = types.ModuleType('pyuepak')
        self.fake_module.PakFile = FakePak
        self.pyuepak = patch.dict(sys.modules, {'pyuepak': self.fake_module})
        self.pyuepak.start()
        self.addCleanup(self.pyuepak.stop)

    def create_index(self):
        return UnrealIndexer(self.root, self.db).scan()

    def test_detect_and_scan_pak_index(self):
        self.assertEqual(detect_engine(self.root), 'Unreal')
        self.assertEqual(self.create_index(), (1, 1, 0))
        results, count = query_unreal_assets(self.db)
        self.assertEqual(count, 3)
        self.assertEqual({x.type for x in results}, {UE_PACKAGE_TYPE})
        self.assertTrue(any(x.name == 'SM_Shoe' for x in results))
        self.assertEqual(UnrealIndexer(self.root, self.db).scan(), (1, 0, 0))

    def test_unreal_list_and_inspect(self):
        self.create_index()
        asset = query_unreal_assets(self.db, 'SM_Shoe')[0][0]
        self.assertEqual(umodel_package_selector(asset), 'Shoes/SM_Shoe.uasset')
        self.assertEqual(parse_umodel_list('''junk\n 0  F00 FF0 StaticMesh SM_Shoe\n 1 AB 15 Texture2D T_Shoe\n'''),
                         [(1, 'StaticMesh', 'SM_Shoe'), (2, 'Texture2D', 'T_Shoe')])
        with patch('unreal_core.subprocess.run', side_effect=fake_umodel_export):
            extractor = UnrealExtractor(self.root, str(self.umodel))
            found = extractor.inspect(asset)
        self.assertEqual(len(found), 3)
        save_inspected_objects(self.db, asset, found)
        matches, count = query_unreal_assets(self.db, 'shoe', '3D candidates')
        self.assertEqual(count, 1)
        self.assertEqual(matches[0].type, 'StaticMesh')
        self.assertIn('Texture2D', unreal_known_types(self.db))
        images, count = query_unreal_assets(self.db, 'T_Shoe', 'Texture2D')
        self.assertEqual(count, 1)
        self.assertEqual(images[0].name, 'T_Shoe')

    def test_umodel_model_export_glb_roundtrip(self):
        key = UnrealAsset(str(self.pak), '../../../SessionGame/Content/Shoes/SM_Shoe.uasset',
                          1, 'StaticMesh', 'SM_Shoe')
        with patch('unreal_core.subprocess.run', side_effect=fake_umodel_export):
            kind, result, warnings = UnrealExtractor(self.root, str(self.umodel)).extract(key, 'glb')
        self.assertEqual(kind, 'scene')
        self.assertTrue(warnings)
        self.assertGreater(sum(len(x.faces) for x in result.geometry.values()), 0)
        output = self.root / 'shoe.glb'
        export_glb(result, output)
        self.assertTrue(output.is_file())
        reloaded = trimesh.load(output, force='scene')
        self.assertTrue(reloaded.geometry)

    def test_png_export(self):
        key = UnrealAsset(str(self.pak), '../../../SessionGame/Content/Shoes/T_Shoe.uasset',
                          2, 'Texture2D', 'T_Shoe')
        with patch('unreal_core.subprocess.run', side_effect=fake_umodel_export):
            kind, result, warnings = UnrealExtractor(self.root, str(self.umodel)).extract(key, 'png')
        self.assertEqual(kind, 'image')
        self.assertEqual(result.size, (19, 17))
        dest = self.root / 'shoe.png'
        export_png(result, dest)
        with Image.open(dest) as image:
            self.assertEqual(image.getpixel((0, 0)), (127, 50, 60, 72))

    def test_index_matching_type_and_literal_like(self):
        self.create_index()
        items, count = query_unreal_assets(self.db, 'SM_', 'UnrealPackage')
        self.assertEqual(count, 1)
        self.assertEqual(items[0].name, 'SM_Shoe')
        self.assertEqual(query_unreal_assets(self.db, 'SM_')[1], 1)
        self.assertEqual(query_unreal_assets(self.db, 'SMX')[1], 0)

    def test_friendly_failures_for_missing_or_ambiguous_exports(self):
        key = UnrealAsset(str(self.pak), '../../../SessionGame/Content/Content/A.uasset',
                          0, UE_PACKAGE_TYPE, 'A')
        self.assertEqual(umodel_package_selector(key), 'Content/A.uasset')
        with self.assertRaisesRegex(FileNotFoundError, 'UE Viewer'):
            UnrealExtractor(self.root, str(self.root / 'missing.exe'))
        with patch('unreal_core.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'ERROR: data encrypted', '')):
            with self.assertRaisesRegex(RuntimeError, 'encrypted'):
                UnrealExtractor(self.root, str(self.umodel)).inspect(key)
        with self.assertRaisesRegex(RuntimeError, 'Inspect package'):
            UnrealExtractor._candidate_file([self.root / 'A.gltf', self.root / 'B.gltf'], key, 'gltf')

    def test_aes_validation_and_capabilities(self):
        self.assertEqual(valid_aes_key('0x' + 'ab' * 32), '0x' + 'ab' * 32)
        with self.assertRaises(ValueError):
            valid_aes_key('abc')
        self.assertTrue(ui_can_export('Unreal', UE_PACKAGE_TYPE, 'glb'))
        self.assertTrue(ui_can_export('Unreal', 'Texture2D', 'png'))
        self.assertFalse(ui_can_export('Unreal', 'Material', 'glb'))
        self.assertTrue(ui_can_preview('Unity', 'GameObject'))
        self.assertTrue(ui_can_export('Unity', 'Texture2D', 'png'))

    def test_auto_identify_types_and_skip_cached(self):
        self.create_index()
        extractor = UnrealExtractor(self.root, str(self.umodel), 'ue4.27')
        ctx = extractor.inspection_context()
        self.assertEqual(len(pending_unreal_packages(self.db, ctx)), 3)
        with patch('unreal_core.subprocess.run', side_effect=fake_umodel_export) as run:
            result = UnrealAutoInspector(self.db, extractor).inspect_all()
            self.assertEqual(result, (3, 3, 3, 0, 9, False))
            self.assertEqual(run.call_count, 3)
            self.assertEqual(UnrealAutoInspector(self.db, extractor).inspect_all(),
                             (0, 0, 0, 0, 0, False))
            self.assertEqual(run.call_count, 3)
        self.assertEqual(len(pending_unreal_packages(self.db, ctx)), 0)
        records, count = query_unreal_assets(self.db)
        self.assertEqual(count, 9)
        self.assertNotIn('UnrealPackage', {r.type for r in records})
        self.assertIn('Texture2D', {r.type for r in records})
        models, model_count = query_unreal_assets(self.db, typ='3D candidates')
        self.assertEqual(model_count, 3)
        self.assertEqual({r.type for r in models}, {'StaticMesh'})

    def test_auto_resume_after_stop_and_unchanged_scan(self):
        class ManyPak(FakePak):
            def list_files(self):
                return [f'../../../SessionGame/Content/Shoes/T_Shoe_{n}.uasset' for n in range(12)]
        with patch.object(self.fake_module, 'PakFile', ManyPak):
            self.create_index()
        cancel = threading.Event()
        calls = []
        def on_progress(done, total, *_):
            calls.append((done, total))
            if done == 5:
                cancel.set()
        extractor = UnrealExtractor(self.root, str(self.umodel))
        with patch('unreal_core.subprocess.run', side_effect=fake_umodel_export):
            first = UnrealAutoInspector(self.db, extractor).inspect_all(on_progress, cancel)
            self.assertEqual(first, (5, 12, 5, 0, 15, True))
            self.assertEqual(calls, [(i, 12) for i in range(1, 6)])
            # The second scan sees an unchanged PAK and preserves typed objects.
            self.assertEqual(self.create_index(), (1, 0, 0))
            second = UnrealAutoInspector(self.db, extractor).inspect_all()
            self.assertEqual(second, (7, 7, 7, 0, 21, False))
        self.assertEqual(query_unreal_assets(self.db)[1], 36)

    def test_auto_retry_after_failed_key_and_no_key_persisted(self):
        self.create_index()
        secret = '0x' + 'be' * 32
        extractor = UnrealExtractor(self.root, str(self.umodel), aes_key=secret)
        bad_result = subprocess.CompletedProcess([], 1, f'ERROR: PAK key invalid: {secret}', '')
        with patch('unreal_core.subprocess.run', return_value=bad_result):
            first = UnrealAutoInspector(self.db, extractor).inspect_all()
        self.assertEqual(first[3], 3)
        issues = unreal_inspection_errors(self.db, extractor.inspection_context())
        self.assertEqual(len(issues), 3)
        self.assertNotIn(secret, repr(issues))
        with patch('unreal_core.subprocess.run', side_effect=fake_umodel_export):
            second = UnrealAutoInspector(self.db, extractor).inspect_all()
        self.assertEqual(second, (3, 3, 3, 0, 9, False))
        self.assertEqual(unreal_inspection_errors(self.db, extractor.inspection_context()), [])

    def test_legacy_manual_inspection_is_adopted(self):
        self.create_index()
        asset = query_unreal_assets(self.db, 'SM_Shoe')[0][0]
        save_inspected_objects(self.db, asset, [(1, 'StaticMesh', 'SM_Shoe')])
        extractor = UnrealExtractor(self.root, str(self.umodel))
        pending = pending_unreal_packages(self.db, extractor.inspection_context())
        self.assertEqual(len(pending), 2)
        self.assertNotIn(asset.cab, {item.cab for item in pending})
        self.assertEqual(query_unreal_assets(self.db, 'SM_Shoe')[1], 1)

    def test_change_umodel_version_and_pak_invalidates_cached_types(self):
        self.create_index()
        extractor = UnrealExtractor(self.root, str(self.umodel), 'ue4.27')
        with patch('unreal_core.subprocess.run', side_effect=fake_umodel_export):
            UnrealAutoInspector(self.db, extractor).inspect_all()
        different = UnrealExtractor(self.root, str(self.umodel), 'ue4.26')
        self.assertEqual(len(pending_unreal_packages(self.db, different.inspection_context())), 3)
        # Any underlying PAK change clears the stored objects and inspections.
        self.pak.write_bytes(b'PAK changed bytes!')
        self.assertEqual(self.create_index(), (1, 1, 0))
        items, count = query_unreal_assets(self.db)
        self.assertEqual(count, 3)
        self.assertEqual({x.type for x in items}, {UE_PACKAGE_TYPE})
        self.assertEqual(len(pending_unreal_packages(self.db, extractor.inspection_context())), 3)

    def test_iostore_is_not_misreported_as_supported(self):
        self.pak.unlink()
        (self.pak.parent / 'pakchunk0.utoc').write_bytes(b'dummy')
        (self.pak.parent / 'pakchunk0.ucas').write_bytes(b'dummy')
        with self.assertRaisesRegex(RuntimeError, 'I/O Store'):
            self.create_index()


if __name__ == '__main__':
    unittest.main()
