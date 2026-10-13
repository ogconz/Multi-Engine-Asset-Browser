"""Run by Blender's background process; converts a generated GLB to FBX.

This must NOT be run with normal Python; Blender supplies the bpy module.
"""
import os
import sys


def main():
    if "--" not in sys.argv:
        raise SystemExit("Usage: blender --background --python blender_convert.py -- source.glb result.fbx")
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 2:
        raise SystemExit("Expected input GLB path and output FBX path")
    source, target = map(os.path.abspath, args)
    import bpy
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=source)
    model_meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not model_meshes:
        raise RuntimeError("GLB did not import any mesh objects; FBX export cancelled")
    bpy.ops.export_scene.fbx(
        filepath=target,
        use_selection=False,
        apply_unit_scale=True,
        add_leaf_bones=False,
        bake_anim=False,
        path_mode="COPY",
        embed_textures=True,
    )
    if not os.path.isfile(target) or os.path.getsize(target) == 0:
        raise RuntimeError("FBX export produced no file")
    print("Skater XL FBX export complete:", target)


if __name__ == "__main__":
    main()
