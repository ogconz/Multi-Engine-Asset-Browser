# Publishing Windows releases

Repository: [ogconz/Multi-Engine-Asset-Browser](https://github.com/ogconz/Multi-Engine-Asset-Browser).

## First public release: v1.0.0

1. Confirm that the latest **Tests** run succeeded.
2. Open **Actions → Windows EXE Release → Run workflow** with `main`. Its Windows runner runs tests, builds a PyInstaller one-file EXE, runs a packaged smoke test and uploads the EXE + SHA-256 checksum under **Artifacts**. A main-branch push also builds a test artifact.
3. Download the built Windows EXE and test it against the games and exports you use. Do not publish if the binary smoke test or manual testing fails.
4. Update your local repo: `git pull origin main`.
5. Create and push **the first public tag only after testing**:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

6. A **successful tagged** workflow publishes [GitHub Releases](../../releases) with `MultiEngineAssetBrowser.exe`, its `.sha256` checksum, and the v1.0.0 release notes. The workflow uses `contents: write`. If Actions permissions disallow publishing, allow write access in repository settings.

All subsequent public releases follow semantic versioning: **v1.0.1** for bug fixes, **v1.1.0** for added backward-compatible features, **v2.0.0** for a breaking release. Update the version constant in `app_version.py`, README and changelog, commit, test the EXE, and push a corresponding `v*` tag.

See [Release notes](RELEASE_NOTES_v1.0.0.md) and [the note from conz](ABOUT.md). The code is openly credited as AI-generated, with project direction and testing by conz.

## Build locally

On Windows with Python 3.11 x64, run `build_exe_windows.bat`. The packaged EXE includes Python libraries but **not** UE Viewer, Blender or the proprietary Oodle codec. The codec is retrieved by pyuepak when required and may need internet for first use.

## Publication checklist

- Check the repository contains no game archives, exported game assets, personal files or credentials.
- Document and review third-party licenses. The project's MIT license does not cover third-party code or codec binaries.
- Verify test and executable smoke-test jobs are green.
- Test the downloadable EXE on a Windows PC and confirm it can scan Unity and Unreal games.
- Tag and release only after the binary works.
