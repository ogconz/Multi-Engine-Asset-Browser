"""Offline regression tests for replacement previews, backups and safety."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import trimesh

from replacement_core import (
    ReplacementError, can_install, has_installed_replacement, install_unity_texture,
    load_replacement_image, load_replacement_mesh, replacement_kind,
    restore_unity_texture, validate_replacement_file,
)


class FakeTexture:
    def __init__(self, owner):
        self.owner = owner
        self.m_Width, self.m_Height = owner.resized

    def set_image(self, img, target_format, mipmap_count):
        self.m_Width, self.m_Height = img.size
        self.owner.resized = img.size

    def save(self):
        self.owner.changed = True


class FakeEnvironment:
    def __init__(self, content):
        self.content = content
        self.changed = False
        self.resized = (3, 2) if content.startswith(b'REPLACED') else (1, 1)
        self.file = self
        reader = types.SimpleNamespace(
            type=types.SimpleNamespace(name='Texture2D'), path_id=14,
            assets_file=types.SimpleNamespace(name='CAB-DEMO'),
        )
        reader.parse_as_object = lambda: FakeTexture(self)
        self.objects = [reader]

    def save(self, packer):
        if not self.changed:
            raise RuntimeError('Expected a modified UnityPy object')
        return b'REPLACED_UNITY_CONTAINER'


class ReplaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'SkaterXL_Data'
        self.data.mkdir()
        self.bundle = self.data / 'textures.bundle'
        self.bundle.write_bytes(b'ORIGINAL_UNITY_CONTAINER')
        self.backups = self.root / 'backups'
        self.asset = types.SimpleNamespace(type='Texture2D', name='T_Test', cab='CAB-DEMO', path_id=14, bundle=str(self.bundle))
        self.png = self.root / 'new.PNG'
        Image.new('RGBA', (3, 2), (17, 21, 144, 255)).save(self.png)

    def test_engine_support_is_explicit_not_misleading(self):
        self.assertEqual(replacement_kind('Unity', 'Mesh'), 'mesh')
        self.assertEqual(replacement_kind('Unreal', 'StaticMesh'), 'mesh')
        self.assertEqual(replacement_kind('Unreal', 'Texture2D'), 'texture')
        self.assertIsNone(replacement_kind('Unreal', 'UnrealPackage'))
        self.assertTrue(can_install('Unity', 'Texture2D'))
        self.assertFalse(can_install('Unity', 'Mesh'))
        self.assertFalse(can_install('Unreal', 'Texture2D'))
        self.assertFalse(can_install('Unreal', 'StaticMesh'))

    def test_image_replacement_file_validation(self):
        self.assertEqual(validate_replacement_file(self.png, 'texture'), self.png)
        self.assertEqual(load_replacement_image(self.png).size, (3, 2))
        with self.assertRaises(ReplacementError):
            validate_replacement_file(self.png, 'mesh')
        with self.assertRaises(ReplacementError):
            validate_replacement_file(self.root / 'missing.png', 'texture')

    def test_mesh_glb_preview(self):
        glb = self.root / 'replacement.glb'
        trimesh.creation.box().export(glb)
        scene = load_replacement_mesh(glb)
        self.assertGreater(len(scene.geometry), 0)
        with self.assertRaisesRegex(ReplacementError, 'requires Blender'):
            fbx = self.root / 'input.fbx'
            fbx.write_text('placeholder')
            load_replacement_mesh(fbx)

    def test_texture_install_backup_restore_and_external_edit_guard(self):
        dummy = types.ModuleType('UnityPy')
        dummy.load = lambda source: FakeEnvironment(source.read() if hasattr(source, 'read') else b'')
        enum = types.ModuleType('UnityPy.enums')
        enum.TextureFormat = types.SimpleNamespace(RGBA32=4)
        with patch.dict(sys.modules, {'UnityPy': dummy, 'UnityPy.enums': enum}):
            self.assertFalse(has_installed_replacement(self.data, self.bundle, self.backups))
            result = install_unity_texture(self.data, self.asset, self.png, self.backups)
            self.assertEqual(result.operation, 'installed')
            self.assertEqual(self.bundle.read_bytes(), b'REPLACED_UNITY_CONTAINER')
            self.assertEqual(result.backup_file.read_bytes(), b'ORIGINAL_UNITY_CONTAINER')
            self.assertTrue(has_installed_replacement(self.data, self.bundle, self.backups))
            with self.assertRaisesRegex(ReplacementError, 'changed since'):
                self.bundle.write_bytes(b'OTHER_MOD')
                install_unity_texture(self.data, self.asset, self.png, self.backups)
            with self.assertRaisesRegex(ReplacementError, 'modified externally'):
                restore_unity_texture(self.data, self.bundle, self.backups)
            self.bundle.write_bytes(b'REPLACED_UNITY_CONTAINER')
            receipt = restore_unity_texture(self.data, self.bundle, self.backups)
            self.assertEqual(receipt.operation, 'restored')
            self.assertEqual(self.bundle.read_bytes(), b'ORIGINAL_UNITY_CONTAINER')
            self.assertFalse(has_installed_replacement(self.data, self.bundle, self.backups))

    def test_refuse_outside_game_or_non_texture(self):
        self.asset.bundle = str(self.root / 'outside.bundle')
        Path(self.asset.bundle).write_bytes(b'X')
        with self.assertRaisesRegex(ReplacementError, 'outside'):
            install_unity_texture(self.data, self.asset, self.png, self.backups)
        self.asset.bundle = str(self.bundle)
        self.asset.type = 'Mesh'
        with self.assertRaisesRegex(ReplacementError, 'only Unity Texture2D'):
            install_unity_texture(self.data, self.asset, self.png, self.backups)


if __name__ == '__main__':
    unittest.main()
