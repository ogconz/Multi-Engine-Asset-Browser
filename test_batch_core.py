"""Offline batch-export regressions (no Windows, Qt, game, or UModel required)."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import trimesh
from PIL import Image

from batch_core import (
    can_batch_export, multi_select_allowed, plan_export_paths,
    run_batch_exports, safe_export_stem,
)
from skaterxl_core import AssetKey
from unreal_core import UnrealAsset


class BatchCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'exports'
        self.folder.mkdir()
        self.tex = [AssetKey('bundle-a', 'CAB-a', x, 'Texture2D', 'T_Shoe') for x in (1, 2, 3)]
        self.ue = [UnrealAsset('pack.pak', 'Shoes/SM_Shoe.uasset', x, 'StaticMesh', 'SM_Shoe') for x in (1, 2)]

    def test_multi_selection_only_under_a_specific_asset_type(self):
        for kind in ('', 'All', '3D candidates', 'UnrealPackage'):
            self.assertFalse(multi_select_allowed(kind))
            self.assertFalse(can_batch_export('Unity', self.tex[:2], kind, 'png'))
        for kind in ('Texture2D', 'StaticMesh', 'SkeletalMesh', 'Mesh', 'GameObject'):
            self.assertTrue(multi_select_allowed(kind))
        self.assertTrue(can_batch_export('Unity', self.tex[:2], 'Texture2D', 'png'))
        self.assertFalse(can_batch_export('Unity', self.tex[:1], 'Texture2D', 'png'))
        self.assertFalse(can_batch_export('Unity', self.tex[:2], 'Texture2D', 'fbx'))
        self.assertTrue(can_batch_export('Unreal', self.ue, 'StaticMesh', 'glb'))
        self.assertTrue(can_batch_export('Unreal', self.ue, 'StaticMesh', 'fbx'))
        self.assertFalse(can_batch_export('Unreal', self.ue, 'Texture2D', 'glb'))
        self.assertFalse(can_batch_export('Unreal', [self.ue[0], UnrealAsset('pak', 't', 1, 'Texture2D', 'T')],
                                          'StaticMesh', 'glb'))
        packages = [UnrealAsset('pak', 'p', x, 'UnrealPackage', 'P') for x in (0, 1)]
        self.assertFalse(can_batch_export('Unreal', packages, 'UnrealPackage', 'glb'))

    def test_export_filenames_unique_even_with_existing_case_variant(self):
        (self.folder / 't_shoe.png').write_bytes(b'existing')
        jobs = plan_export_paths(self.tex, self.folder, 'png')
        self.assertEqual([p.name for _, p in jobs], ['T_Shoe_2.png', 'T_Shoe_3.png', 'T_Shoe_4.png'])
        self.assertEqual((self.folder / 't_shoe.png').read_bytes(), b'existing')
        jobs2 = plan_export_paths(self.tex, self.folder, 'png')
        self.assertEqual(jobs, jobs2)
        with self.assertRaises(ValueError):
            plan_export_paths(self.tex, self.folder, 'exe')

    def test_unsafe_windows_filenames_are_made_safe(self):
        self.assertEqual(safe_export_stem('CON'), '_CON')
        self.assertEqual(safe_export_stem('lpt1.txt'), '_lpt1.txt')
        self.assertEqual(safe_export_stem('../foo\\bar:*?'), 'foo_bar')
        self.assertEqual(safe_export_stem(' ...  '), 'Asset')
        self.assertTrue(all(p.parent == self.folder for _, p in
                            plan_export_paths([AssetKey('a', 'CAB', 1, 'Mesh', '..\\bad:name')], self.folder, 'glb')))

    def test_unity_batch_png_continues_after_bad_texture(self):
        def fake_decode(reader):
            if reader.path_id == 2:
                raise ValueError('unsupported codec')
            return Image.new('RGBA', (7, 5), (10, 20, 30, 40))

        with (patch('batch_core.BundleResolver') as mock_resolver,
              patch('batch_core.decode_texture_image', side_effect=fake_decode)):
            mock_resolver.return_value.lookup.side_effect = lambda asset: asset
            events = []
            result = run_batch_exports('Unity', self.root, self.root / 'fake.sqlite',
                                       plan_export_paths(self.tex, self.folder, 'png'), 'png',
                                       progress=lambda *event: events.append(event))
        self.assertEqual(result.total, 3)
        self.assertEqual(result.attempted, 3)
        self.assertFalse(result.cancelled)
        self.assertEqual(len(result.successful), 2)
        self.assertEqual(len(result.failures), 1)
        self.assertIn('unsupported codec', result.failures[0][1])
        self.assertEqual([event[:4] for event in events], [(1, 3, 1, 0), (2, 3, 1, 1), (3, 3, 2, 1)])
        for path in result.successful:
            with Image.open(path) as image:
                self.assertEqual(image.size, (7, 5))
                self.assertEqual(image.getpixel((0, 0)), (10, 20, 30, 40))
        self.assertFalse((self.folder / 'T_Shoe_2.png').is_file())

    def test_unity_stop_is_checked_between_items(self):
        cancel = threading.Event()
        with (patch('batch_core.BundleResolver') as mock_resolver,
              patch('batch_core.decode_texture_image', return_value=Image.new('RGBA', (1, 1), 'red'))):
            mock_resolver.return_value.lookup.side_effect = lambda asset: asset
            result = run_batch_exports('Unity', self.root, self.root / 'fake.sqlite',
                                       plan_export_paths(self.tex, self.folder, 'png'), 'png',
                                       cancel=cancel,
                                       progress=lambda done, *_: cancel.set() if done == 1 else None)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.attempted, 1)
        self.assertEqual(len(result.successful), 1)
        self.assertEqual(len(result.failures), 0)
        self.assertEqual(len(list(self.folder.glob('*.png'))), 1)

    def test_unreal_batch_mesh_export_and_one_failure(self):
        def extract(asset, kind):
            if asset.path_id == 2:
                raise RuntimeError('unsupported material')
            scene = trimesh.Scene()
            scene.add_geometry(trimesh.creation.box(), node_name='SM_Shoe')
            return 'scene', scene, []
        with patch('batch_core.UnrealExtractor') as cls:
            cls.return_value.extract.side_effect = extract
            result = run_batch_exports('Unreal', self.root, self.root / 'cache.sqlite',
                                       plan_export_paths(self.ue, self.folder, 'glb'), 'glb',
                                       umodel='ignored.exe', ue_override='ue4.27')
        self.assertEqual(len(result.successful), 1)
        self.assertEqual(len(result.failures), 1)
        saved = trimesh.load(result.successful[0], force='scene')
        self.assertTrue(saved.geometry)
        self.assertGreater(sum(len(g.faces) for g in saved.geometry.values()), 0)
        cls.assert_called_once_with(self.root, 'ignored.exe', 'ue4.27', '')

    def test_unreal_batch_texture_png(self):
        items = [UnrealAsset('pack.pak', 'Textures/T_Shoe.uasset', x,
                             'Texture2D', 'T_Shoe') for x in (1, 2)]
        with patch('batch_core.UnrealExtractor') as cls:
            cls.return_value.extract.return_value = (
                'image', Image.new('RGBA', (4, 6), (11, 22, 33, 44)), [])
            result = run_batch_exports('Unreal', self.root, self.root / 'cache.sqlite',
                                       plan_export_paths(items, self.folder, 'png'), 'png',
                                       umodel='umodel.exe')
        self.assertEqual(len(result.successful), 2)
        self.assertEqual(len(result.failures), 0)
        self.assertEqual(cls.return_value.extract.call_count, 2)
        for file in result.successful:
            with Image.open(file) as image:
                self.assertEqual(image.getpixel((0, 0)), (11, 22, 33, 44))

    def test_unity_batch_fbx_uses_blender_path_for_each_asset(self):
        meshes = [AssetKey('bundle-a', 'CAB-a', x, 'Mesh', 'Shoe') for x in (1, 2)]
        with (patch('batch_core.BundleResolver'),
              patch('batch_core.SceneExtractor') as scene_extractor,
              patch('batch_core.export_fbx') as export_fbx):
            scene_extractor.return_value.extract.return_value = ('scene-data', [])
            export_fbx.side_effect = lambda scene, target, blender, script: target.write_bytes(b'fbx')
            result = run_batch_exports('Unity', self.root, self.root / 'cache.sqlite',
                                       plan_export_paths(meshes, self.folder, 'fbx'), 'fbx',
                                       blender='D:/Blender/blender.exe')
        self.assertEqual([path.name for path in result.successful], ['Shoe.fbx', 'Shoe_2.fbx'])
        self.assertEqual(export_fbx.call_count, 2)
        for call in export_fbx.call_args_list:
            self.assertEqual(call.args[2], 'D:/Blender/blender.exe')
            self.assertTrue(str(call.args[3]).endswith('blender_convert.py'))

    def test_invalid_batch_never_processes_uninspected_packages(self):
        jobs = plan_export_paths([UnrealAsset('pak', 'shoe.uasset', 0, 'UnrealPackage', 'shoe')],
                                 self.folder, 'glb')
        with self.assertRaisesRegex(ValueError, 'typed, exportable'):
            run_batch_exports('Unreal', self.root, self.root / 'db', jobs, 'glb', umodel='ignored.exe')


if __name__ == '__main__':
    unittest.main()
