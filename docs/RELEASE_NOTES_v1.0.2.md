# Multi-Engine Asset Browser v1.0.2

**Windows bug-fix release: Texture2D preview/export**

Fixes the error `Failed to load ... fmod_toolkit/libfmod/Windows/x64/fmod.dll` when previewing or exporting Unity textures, which affected the v1.0.1 Windows executable.

### Changes
- Prevent UnityPy's unused AudioClip import from requiring a proprietary FMOD audio DLL when decoding textures.
- Keep FMOD's audio engine out of the EXE. This browser handles supported models and textures, not AudioClip extraction.
- Expand the Windows EXE smoke test to load UnityPy's texture converter, catching this problem before release.
- Preserve existing game folders, scan caches and settings.

**Install:** Download the v1.0.2 `MultiEngineAssetBrowser.exe` from Assets and replace your older executable. No Python installation or new scan should be necessary.

This free tool was initiated and tested by conz and implemented with AI assistance. Thank you for reporting bugs so it can improve.
