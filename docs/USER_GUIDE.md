# Multi-Engine Asset Browser v2.2 - Source user guide

> **Standalone `.exe` users:** You do not need Python or the `.bat` installers. Download `MultiEngineAssetBrowser.exe` from the [GitHub Releases page](../../releases/latest) and launch it. This document also covers running the application directly from its Python source. UE Viewer is a separate download for Unreal extraction; Blender is needed for FBX export.

A desktop asset browser for **Unity games** (including Skater XL) and **Unreal Engine 4 games stored in `.pak` files** (including Session: Skate Sim's packaging layout). The **original Skater XL v1.1 Unity mesh/texture functionality is retained**. The Unreal backend indexes PAK archives without unpacking them all, **automatically identifies object classes (Texture2D, StaticMesh, SkeletalMesh, etc.) in the background**, and previews/exports supported mesh and image assets. The game installation is accessed read-only.

**Important: This is an early multi-engine prototype.** Unity operations are based on the previously working v1.1 code. Unreal PAK indexing, automatic class identification, cached/resumable scans, model round trips and PNG exports passed **30 offline tests (including batch-export regressions) using stand-in game data and a mocked UE Viewer**. The original Windows GUI has been used successfully by early users with Skater XL and Session; the new separately packaged public EXE still requires its own Windows release verification. If a package or mesh is unsupported, the app should report an error rather than silently producing an empty GLB.

## Downloads and dependencies

| Item | Needed for | Installation |
|---|---|---|
| **Python 3.11, 64-bit** | Running the app | https://www.python.org/downloads/ ; install Windows version with `py` launcher |
| **Python packages** | All app features and Unreal PAK index | `install_windows.bat` installs UnityPy, PySide6, PyVista, PyVistaQt, Trimesh, NumPy, Pillow, **pyuepak**, **cryptography** and required transitive packages |
| **UE Viewer / UModel (`umodel.exe`)** | **Unreal** object inspection, 3D preview, texture/model extraction | Download and unzip official UE Viewer: https://www.gildor.org/en/projects/umodel ; select `umodel.exe` in the app |
| **Blender** | **FBX only**, both engines | https://www.blender.org/download/ ; GLB and PNG do not need Blender |
| Your legally obtained local game files | All features | Unity `_Data` / game root or Unreal game root / `Content\Paks` |

You do **not** need Unreal Editor, Unity Editor, AssetRipper or FModel. UE Viewer is a separate executable, not a pip module; the ZIP does not bundle third-party binaries. Some Windows systems also need the Microsoft Visual C++ 2015-2022 x64 Redistributable for VTK or UE Viewer.

The **official UE Viewer** provides `-list`, `-export`, `-gltf`, `-png` and `-path` command-line options. It has broad, but not universal, Unreal package compatibility.

## First installation

1. Extract the entire application ZIP to a normal folder, e.g. `D:\MultiEngineAssetBrowser` (not inside the ZIP).
2. Double-click **`install_windows.bat`**. It creates `.venv` and installs the required Python packages. Internet access is needed for this step.
3. For Unreal, separately download and unzip **UE Viewer**, and locate its `umodel.exe`. A recent version supporting `-gltf` is required.
4. Double-click **`run_windows.bat`**.
5. Select your game folder and choose **Engine: Auto**, then click **Scan / Refresh**.

### Update an existing working v2.1 installation to v2.2

1. Close the app.
2. Extract the **v2.2 Update ZIP** into the folder containing `multi_engine_browser.py` (for example `E:\Programs\Multi Engine Asset Browser`), replacing the old `multi_engine_browser.py` and `README.md` and adding the new `batch_core.py` and `test_batch_core.py`.
3. Double-click your existing **`run_windows.bat`**. **No rescan, no new pip packages, no reinstall, and no new UE Viewer setup are needed** if v2.1 already works. Your game indices, selected UE version, and settings are preserved. (As before, the PAK AES key is not stored.)

### Shift/Ctrl multi-selection and batch export (new in v2.2)

1. Select a **specific class** from the **Type** dropdown, for example `Texture2D`, `StaticMesh`, `SkeletalMesh`, or (Unity) `Mesh`. Leaving Type as `All`, `3D candidates`, or `UnrealPackage` keeps **single selection only** to prevent bulk-exporting incompatible or unclassified assets.
2. In the asset table, **Shift+click** to select a range; **Ctrl+click** to add/remove individual rows; **Ctrl+A** to select all **currently displayed** rows for that type. The selection count appears next to the result count.
3. For `Texture2D`, click **Export N PNGs**. For supported meshes, click **Export N GLBs** or **Export N FBXs**. The buttons enable automatically when all selected assets can use that format.
4. Choose an **output folder**. Each asset is exported as a separate file. If assets share a name, output filenames receive numbered suffixes (for example `T_Shoe.png`, `T_Shoe_2.png`). Files already in the selected folder are skipped during filename allocation so existing exports are not intentionally overwritten.
5. The progress bar displays exported / failed counts. The task runs in a background thread so the window stays responsive. Click **Stop** to finish the current item and cancel the remaining items. At the end, you'll see a success/failure summary and per-item errors in the Diagnostics pane. One bad texture or mesh does **not** stop other items.

**Single-item behavior is unchanged:** select one item and use the existing Save As dialog. **Batch mode only starts with two or more selected rows.** Supported source formats, Unreal `ue4.27` / AES setup and Blender requirement for FBX remain the same as v2.1.

**Selection scope:** The table currently displays **up to 1,500 matching rows** at once. Ctrl+A selects those displayed rows, not all indexed assets beyond that limit. Use the search field to narrow the result set and export it in chunks if needed. If you run a batch a second time into the same folder, new suffixes avoid overwriting the earlier results. For very large Unreal batches, UE Viewer is called separately for each object and FBX additionally uses Blender, so processing can take a while. No game files are changed.

## Unity (Skater XL and other Unity games)

1. Set **Engine: Auto** or **Unity**.
2. Select the Unity game root or game `_Data` folder. For Skater XL, use the complete `D:\SteamLibrary\steamapps\common\Skater XL\SkaterXL_Data` folder, not only the individual assetbundle folder.
3. Click **Scan / Refresh**. Search for an asset name; filter to **Mesh**, **GameObject**, or **Texture2D**.
4. Select a mesh/GameObject and click **Preview in 3D** or **Export GLB/FBX**. Select a `Texture2D` to **Export PNG** or preview then save.

This is the same UnityPy-based extractor, cross-bundle CAB resolver, separate 3D window, GLB/FBX conversion and PNG export from v1.1. Other Unity games can be scanned when they use a UnityPy-supported serialized format; support is not guaranteed for unusual/custom/encrypted archive formats.

## Unreal Engine (Session: Skate Sim)

The Session Windows Steam depot lists a large `pakchunk0-WindowsNoEditor.pak` under `SessionGame\Content\Paks`. Select **the game folder**, e.g.:

```text
D:\SteamLibrary\steamapps\common\Session
```

Alternatively, select this folder directly:

```text
D:\SteamLibrary\steamapps\common\Session\SessionGame\Content\Paks
```

### How automatic type identification works (new in v2.1)

1. Select **Engine: Unreal**, your Session folder, and `umodel.exe` (the path is remembered). Enter the UE version override, for example **`ue4.27`**, and your existing PAK AES key if required (not saved).
2. Leave **Automatically identify Unreal asset types after scan** checked (default), then click **Scan / Refresh**. `pyuepak` first reads the PAK filenames without extracting the archive.
3. Once the fast filename scan finishes, **UE Viewer starts identifying every package in the background** using the actual Unreal export table, rather than guessing from filenames. The Type column changes from `UnrealPackage` to verified `Texture2D`, `SkeletalMesh`, `StaticMesh`, `Material`, etc. As packages are identified, they appear in the searchable list and the class filters update automatically. Successfully inspected package placeholders disappear; packages that could not be inspected remain `UnrealPackage`.
4. You can **Stop** the classification whenever you want. The types already identified remain cached, and the next **Scan / Refresh** or **Identify existing packages** resumes only unfinished or previously failed packages. The PAK itself is unchanged, and the same game's cache is reused across restarts.
5. Select a typed `StaticMesh` or `SkeletalMesh` for **3D preview / GLB / FBX**; select `Texture2D` for **image preview / PNG**. The older **Inspect package objects** button still works as a one-off fallback for anything the background scan could not recognize.

**Performance:** The initial filename index is quick compared with a complete class scan. Confirming *every* asset class involves starting UE Viewer on individual Unreal packages, potentially many thousands of times, so **the first full identification can be slow on Session** (possibly much longer than the PAK index scan). You can stop it and resume later. Subsequent runs skip successfully identified packages, unless the PAK, UE Viewer executable or UE override changes. Automatic identification is a separate optional step; uncheck it for quick index-only scans. **It does not extract every mesh/texture up front.**

If the AES key was not entered or UModel failed to read some packages, check the diagnostics, correct your settings, and click **Identify existing packages** again. Failed packages are retried; successful ones stay cached. The app never stores the AES key.

The asset list is cached in `%LOCALAPPDATA%\MultiEngineAssetBrowser\unreal_<folder-hash>.sqlite3`. An unchanged PAK archive is **not reparsed** at each refresh. Each export invokes `umodel.exe` to decode just the selected object/package into a **temporary output folder**, then uses Trimesh/Pillow/Blender to produce the requested output. These temporary decoded files are deleted after the operation. Your game's `.pak`, `.uasset`, `.uexp` and other files are never written to.

### Session compatibility quick reference

For **Session: Skate Sim (PC, Unreal Engine 4.27)**:

- **UE override:** `ue4.27`
- **PAK AES (community-reported):** `0x2d0e2b103cf0b3cb5ea8d6b774ea49400d36bd431f4bdeff74f99261bd1dabdc`
- **UE Viewer:** select your downloaded `umodel.exe`

This key was confirmed to work for one Session installation, not guaranteed for other builds or updates. Enter it manually; the browser does not store it. For a copy-friendly setup and notes on other games, see [Game compatibility](GAME_COMPATIBILITY.md).

### Engine version override and AES key

- Leave **UE override** empty to let UE Viewer auto-detect the game engine version. If it fails, run `umodel.exe -taglist` in a command prompt and enter one of its supported tags (for example `ue4.27`, only **if your installed UE Viewer lists that exact tag**). Not every game's UE version is the same.
- Leave **PAK AES** empty for unencrypted archives. If an archive uses AES encryption and you **lawfully have** the relevant key, you can supply 64 hexadecimal characters in this field. The application never saves that key to settings. The project does not attempt to discover encryption keys; community-reported values are documented for manual entry where appropriate.
- If the package index cannot be decoded, the scanning diagnostics show which PAK failed. UE Viewer's own codec/engine compatibility limitations may also prevent individual asset extraction.

## What is and is not supported

| Feature | Unity supported serialized assets | Unreal Engine 4 `.pak` packages |
|---|---|---|
| Discover / search assets | Objects and Unity CAB references | Package paths + automatic, cached class identification with UE Viewer |
| Texture2D preview and PNG | Yes, when UnityPy can decode the texture | Yes, when UE Viewer can export the texture |
| Static 3D preview window | Mesh and mesh-containing GameObjects | UE Viewer-supported StaticMesh / SkeletalMesh |
| GLB export | Yes, native Trimesh GLB | Yes, via UE Viewer glTF -> Trimesh GLB |
| FBX export | Yes, via Blender | Yes, via Blender |
| Original rigs, animations, shader graphs | No; static geometry | No; static geometry |
| Unreal **`.utoc/.ucas` I/O Store** | N/A | **Not supported in v2.0** |
| Encrypted/proprietary formats | Best effort only | Supported only where tools accept a user-provided lawful key and compatible formats |

A few important caveats:

- **You cannot convert every indexed asset into FBX/GLB/PNG.** Indexing is discovery; Audio, Materials, Animation clips and Blueprints are not 3D meshes or decoded images in this tool.
- UE Viewer compatibility varies by engine version and game-specific serialization changes. Meshes/textures may be unavailable, and UModel may sometimes crash on unsupported packages.
- UE skeletal meshes are reduced to static mesh geometry when loaded into Trimesh and exported as GLB/FBX; skeletons, skinned weights and animations are **not preserved**.
- Texturing is **best effort**. UVs and geometry may export while some shader-specific materials/texture bindings are missing. Normal maps alone do not represent geometry.
- This version targets Unreal **`.pak`** archives, not all Unreal Engine 5 games. Unreal **I/O Store** (`.utoc/.ucas`) requires a different backend (e.g. a supported exporter) not included here; the GUI reports this limitation. Loose Unreal `.uasset` / `.umap` files can be indexed but still require UE Viewer for inspection/extraction.
- Encrypted archives and proprietary codecs require the relevant engine-compatible decoder; no bypass of DRM or anti-cheat is provided.
- Indexing a 16+ GB Session archive can still take time depending on the drive and archive directory size, though the tool never unpacks the whole archive for indexing.
- Use exported content only as permitted by the relevant game's rights and terms. Do not redistribute copyrighted assets without permission.

## Troubleshooting

**No Unreal packages appear:** Verify that you selected the folder with `SessionGame\Content\Paks\*.pak`, run the installer to add `pyuepak`, and check scanning diagnostics for unsupported archive versions or encryption.

**Inspect cannot find an Unreal package:** UE Viewer package-path matching varies; the tool first tries the path relative to `Content/`, then filename and stem. Try selecting the game root instead of just `Paks`, or check the UE Viewer engine override with `umodel.exe -taglist`.

**UE Viewer produces no model:** Verify the row type is `StaticMesh` or `SkeletalMesh`, not a Material or Blueprint. Inspect the package, select a child, and try the UModel GUI manually for comparison. Game-specific formats may be unsupported.

**FBX won't export:** Install Blender, then browse to `blender.exe` when the app asks. GLB or PNG do not need Blender.

**Unity mesh missing:** Scan the entire `_Data` folder (not just a single AssetBundle) to resolve external CAB mesh references.

**Blank result for `3D candidates` on Unreal:** The fast PAK scan indexes **filenames**, not verified types. Wait for the automatic class scan to discover meshes, click **Identify existing packages**, or manually inspect specific packages. If background inspection fails, verify `umodel.exe`, `ue4.27` and the PAK AES key.

**Run tests:**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

The test suite includes Unity cross-bundle / glTF / PNG tests plus simulated Unreal PAK index and UE Viewer list/export tests. Running them does not require the actual games.

## Open source dependencies

- [UnityPy](https://github.com/K0lb3/UnityPy) - Unity serialized resources
- [pyuepak](https://github.com/stas96111/pyuepak) - Unreal PAK index reader
- [UE Viewer](https://www.gildor.org/en/projects/umodel) - Unreal mesh/texture conversion (installed separately)
- [PySide6](https://pypi.org/project/PySide6/), [PyVista](https://docs.pyvista.org/), [Trimesh](https://trimesh.org/), [Pillow](https://python-pillow.github.io/)
