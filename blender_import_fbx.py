"""Run inside Blender to convert an FBX into a preview-only GLB."""
import os
import sys


def main():
    if '--' not in sys.argv:
        raise SystemExit('Usage: blender --background --python blender_import_fbx.py -- model.fbx preview.glb')
    arguments = sys.argv[sys.argv.index('--') + 1:]
    if len(arguments) != 2:
        raise SystemExit('Expected FBX source and GLB output paths')
    source, target = map(os.path.abspath, arguments)
    import bpy
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.fbx(filepath=source)
    if not any(item.type == 'MESH' for item in bpy.context.scene.objects):
        raise RuntimeError('FBX has no mesh objects')
    bpy.ops.export_scene.gltf(filepath=target, export_format='GLB', export_apply=False)
    if not os.path.isfile(target) or os.path.getsize(target) == 0:
        raise RuntimeError('Blender did not produce a GLB preview')


if __name__ == '__main__':
    main()
