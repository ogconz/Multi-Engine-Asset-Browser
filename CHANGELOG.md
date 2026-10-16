# Changelog

## v1.1.0-dev.1 — Experimental replacement workflow (NOT RELEASED)

- Add **Replace Mesh / Texture...** to the Windows browser for supported asset types.
- Pick and preview a replacement mesh (GLB, or FBX via Blender) or texture (PNG/JPG).
- Separate original and replacement previews, without geometry adjustment controls.
- First experimental real in-game installer: **Unity Texture2D** via UnityPy rewriting, with full original container backup, source-file validation, atomic write, and Restore Original.
- Clearly mark **Unity meshes and all Unreal replacements** as *preview only / not installed* until game-specific mod installers and cooked asset support are implemented.
- Include local tests for format validation, Unity install/restore, and external modification safety.
- Public release **v1.0.2 stays unchanged**. Do not publish v1.1.0 until in-game testing and additional engine adapters are verified.


## v1.0.2 — Unity texture preview compatibility fix

- Fix packaged Windows EXE failing to preview/export Unity Texture2D PNGs with a missing `fmod_toolkit/libfmod/Windows/x64/fmod.dll` error.
- Prevent UnityPy's optional AudioClip importer from trying to load the FMOD audio codec when only textures or meshes are needed.
- Keep the proprietary FMOD engine out of the EXE; audio conversion is not an implemented feature.
- Include the `archspec` CPU microarchitecture JSON database, plus ASTC and Texture2D decoder libraries needed by UnityPy.
- Extend the packaged EXE smoke test to load `UnityPy.export.Texture2DConverter`, verify the `archspec` JSON files, and decode a synthetic RGBA32 texture to check the pixel output.
- No rescanning, game file changes or settings reset should be required.

**Published after successful Windows texture-preview and PNG export testing.**


## v1.0.1 — Windows UnityPy asset-loading fix

- Fix packaged Windows EXE error `ModuleNotFoundError: No module named 'UnityPy.resources'` when opening or previewing assets.
- Bundle UnityPy's dynamic submodules and resource data, including `lzma.tpk`.
- Extend the packaged EXE smoke test to import `UnityPy.resources` and read its data, so future builds fail before release if this dependency is missing.
- No game content or saved scan caches are modified.

**Released after Windows verification.**


## v1.0.0 — First public release

- First public Windows release of Multi-Engine Asset Browser, an idea by conz with AI-generated implementation.
- Unity asset indexing, 3D preview and GLB/FBX/PNG export.
- Unreal Engine 4 PAK indexing and UE Viewer-based mesh/texture extraction.
- Automatic and resumable Unreal asset-type identification with caching.
- Shift/Ctrl multi-selection and type-filtered batch exports.
- Session: Skate Sim UE4.27 compatibility guide.
- Portable Windows EXE packaging with automated smoke tests and GitHub Releases.

Public version numbers start at **1.0.0**. Earlier v2.x designations refer only to private development/testing builds. Subsequent public releases will use semantic versioning (for example, 1.0.1 for fixes and 1.1.0 for features).
