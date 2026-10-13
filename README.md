# Multi-Engine Asset Browser

**Browse, preview, and export assets from supported Unity and Unreal Engine games.**

**[Download the latest Windows `.exe`](../../releases/latest)** | [User guide](docs/USER_GUIDE.md) | [Build from source](#build-from-source) | [Report a problem](../../issues)

A free, open-source Windows desktop utility for exploring locally installed game assets. It indexes supported formats, identifies asset types, opens models in a rotatable 3D viewer, previews textures, and exports to **GLB**, **FBX**, or **PNG**.

## Features

- **Unity**: Read supported asset bundles with UnityPy, search meshes and textures, resolve referenced assets, and export model scenes or Texture2D images. Skater XL is an example.
- **Unreal Engine 4**: Index `.pak` archives with pyuepak; identify `StaticMesh`, `SkeletalMesh`, `Texture2D`, and other package classes using [UE Viewer](https://www.gildor.org/en/projects/umodel). Session: Skate Sim is an example (UE4.27).
- **Preview**: Interactive 3D mesh viewer (orbit, pan, zoom, wireframe) and texture preview.
- **Batch exports**: Filter by a particular asset type and use Shift, Ctrl, or Ctrl+A to select and export multiple assets to a folder.
- **Unreal background indexing**: Automatically identify asset classes, stop/resume, and keep a local SQLite cache.
- **Read-only scanning**: Scans game installations without writing to the game files.

## Download and run (no Python needed)

1. Open **[Releases](../../releases/latest)** on the right side of this repository.
2. Download **`MultiEngineAssetBrowser.exe`** from **Assets** (not the automatically generated *Source code* ZIP).
3. Run the `.exe` on **Windows 10/11 64-bit**. No Python installation is required for the prebuilt executable.
4. Choose your game folder and scan. For Unreal games, download **[UE Viewer / UModel](https://www.gildor.org/en/projects/umodel)** separately and select `umodel.exe` in the app.

**Optional external tools:** [Blender](https://www.blender.org/download/) is required for **FBX** exports. GLB and PNG exports do not require Blender. UE Viewer is required for Unreal package inspection and export, but not for Unity. UE Viewer and Blender are **not distributed with this project**.

**About encrypted game archives:** Some games require a user-entered AES key. The application does not discover keys and never saves keys in its settings. See the community-tested Session configuration below. Only inspect games and assets you are authorized to access and use.

> The `.exe` is produced on a Windows GitHub Actions runner using PyInstaller when a version tag is pushed. Windows and graphics drivers differ: if the packaged app does not launch, please open an issue with the relevant logs and Windows version. Unsigned community-built executables may trigger SmartScreen warnings; verify the download and scan it as you would any executable.

### Session: Skate Sim (PC / Unreal Engine 4.27)

For the Session `.pak` edition, choose **Engine: Unreal**, select the Session installation folder and locate [UE Viewer](https://www.gildor.org/en/projects/umodel) (`umodel.exe`). Then enter:

| Setting | Value |
|---|---|
| **UE override** | `ue4.27` |
| **PAK AES** | `0x2d0e2b103cf0b3cb5ea8d6b774ea49400d36bd431f4bdeff74f99261bd1dabdc` |

This **community-reported AES key worked in a tested Session installation**. It may not apply to other versions, platforms or updates. Paste the full key including `0x` into the optional PAK AES field. The app never saves the key. The key is documented for manual entry; it isn't built into the EXE. See [Game compatibility and configuration](docs/GAME_COMPATIBILITY.md) for step-by-step instructions.

## Compatibility

| Engine | Input | Preview/export |
|---|---|---|
| Unity | UnityPy-compatible bundles / serialized assets | Mesh/GameObject to GLB/FBX; Texture2D to PNG |
| Unreal Engine 4 | `.pak` and supported loose Unreal packages | UE Viewer-supported StaticMesh/SkeletalMesh to GLB/FBX; Texture2D to PNG |
| Unreal Engine 5 I/O Store | `.utoc` / `.ucas` | **Not currently supported** |

Game-specific engine changes, encrypted files, custom asset formats, missing mesh references, and unsupported UE Viewer package versions may prevent extraction. This is **not** a universal game extractor. See the [detailed user guide](docs/USER_GUIDE.md) for limitations and the UE4 version override.

## Build from source

If you'd rather run the Python source or contribute:

1. Install [Python 3.11 x64](https://www.python.org/downloads/) on Windows.
2. Clone or download this repository and run `install_windows.bat`.
3. Run `run_windows.bat` to launch the application.
4. For a standalone Windows executable, run `build_exe_windows.bat`. The output is `dist\MultiEngineAssetBrowser.exe`. It requires the Python dependencies and PyInstaller only **at build time**.

For command-line users:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe multi_engine_browser.py
```

To run the automated tests:

```powershell
.venv\Scripts\python.exe -m unittest discover -p "test_*.py" -v
```

## Releases

The source code lives in the normal **Code** tab. The **Releases** panel on GitHub will appear after the first release has been published. This repository contains a Windows [release workflow](.github/workflows/windows-release.yml): pushing a version tag such as `v2.2.0` runs the tests, builds the standalone `.exe`, and publishes a GitHub Release containing the executable and its SHA-256 checksum.

Maintainers: see [Publishing a release](docs/PUBLISHING.md). The workflow can also be run manually to build an `.exe` for testing without publishing a release.

## Contributing, licenses, and asset rights

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). This project's own source code is released under the **[MIT license](LICENSE)**. Third-party libraries and tools have their own licenses; see [Third-party software](docs/THIRD_PARTY.md).

This is an independent utility and is **not affiliated with** the developers or publishers of Skater XL, Session: Skate Sim, Unity, Unreal Engine, or UE Viewer. No game assets, copyrighted game files, decryption keys, or third-party executables are distributed here. Exporting an asset does not give you permission to redistribute or commercially exploit that asset; follow applicable licenses, rights, and laws.
