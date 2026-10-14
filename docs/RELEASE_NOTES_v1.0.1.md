# Multi-Engine Asset Browser v1.0.1

**Windows EXE bug-fix release — Unity asset loading**

This update fixes the error **`ModuleNotFoundError: No module named 'UnityPy.resources'`** that could appear when opening assets from the first public Windows release, v1.0.0.

- Include the UnityPy resource package and the `lzma.tpk` data file in the PyInstaller executable.
- Expand the Windows packaged-app smoke test to check the UnityPy resource module and actually read its resource data.
- No change to supported engine formats or your game's files.

**Install:** Download the updated `MultiEngineAssetBrowser.exe` from this release's Assets section and replace the previous EXE. No Python installation required. Your existing scan caches and settings should remain intact.

For Unreal games, UE Viewer (UModel) is still needed for asset extraction. Blender is still needed for FBX exports. Compatibility varies by game and version.

**From conz:** This project grew out of my ideas and testing, and the code was developed with AI. Thanks for trying the first release and reporting issues — that feedback helps make the tool better!
