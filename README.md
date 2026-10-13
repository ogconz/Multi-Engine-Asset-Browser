# Multi-Engine Asset Browser

An open-source Windows desktop app for browsing, previewing and exporting supported **Unity** and **Unreal Engine 4** game assets.

**[Download latest Windows EXE](../../releases/latest)** · [Releases](../../releases) · [Report an issue](../../issues)

## Features

- Unity asset bundles (e.g. Skater XL) and Unreal Engine 4 PAK files (e.g. Session: Skate Sim)
- Search and filter asset classes including Texture2D, StaticMesh and SkeletalMesh
- Interactive 3D mesh previews and texture previews
- GLB, FBX and PNG exports, including multi-select / batch exports
- Cached indexing and automatic asset type identification for UE4 packages

## Installing

Once the first GitHub Release has finished building, open **Releases** on the right and download **MultiEngineAssetBrowser.exe** from Assets. On Windows 10/11 x64, run the EXE directly. The packaged executable doesn't require a separate Python installation.

**Unreal:** Install [UE Viewer (UModel)](https://www.gildor.org/en/projects/umodel) and select `umodel.exe` within the app. **FBX export:** Install [Blender](https://www.blender.org/). These external executables are not bundled. Encrypted archives can require an AES key supplied by the user; none are distributed with this project.

## Run from source

Use **Python 3.11 x64** on Windows:

```bat
install_windows.bat
run_windows.bat
```

To build the standalone EXE locally:

```bat
build_exe_windows.bat
```

The automatic Windows release workflow builds, tests and publishes the EXE and a SHA-256 checksum whenever a `v*` tag is pushed.

## Compatibility

| Engine | Supported inputs |
|---|---|
| Unity | UnityPy-supported serialized files and bundles |
| Unreal Engine 4 | UE Viewer-supported PAK packages and loose assets |
| Unreal Engine 5 I/O Store | Not supported (`.utoc` / `.ucas`) |

Mesh rigging, materials, asset dependencies and particular game versions may affect export success.

## License and legal

MIT license — see [LICENSE](LICENSE). The project isn't affiliated with Unity, Unreal Engine, Skater XL or Session developers. **No game files or AES keys** are included; extracted assets remain subject to their respective owners' rights.

> This repository is being initialized. Until the full source is uploaded and a Windows build passes, the latest release link may not yet contain an executable.
