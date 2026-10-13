# Publishing the open-source repository and Windows EXE releases

## First-time publication

1. Sign in to GitHub and create a new **Public** repository, e.g. `MultiEngineAssetBrowser`. **Do not** add a GitHub-generated README, .gitignore or license: those files are already included here.
2. Extract the GitHub-ready source ZIP and open **PowerShell** in the extracted folder (the folder containing `README.md` and `.github`).
3. With Git installed, run the commands below. Replace `YOUR_USERNAME` with your GitHub name:

```powershell
git init
git add .
git commit -m "Initial public source release"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/MultiEngineAssetBrowser.git
git push -u origin main
```

4. In the GitHub **Actions** tab, allow GitHub Actions for the repository if prompted. The workflow requests `contents: write` for publishing a release; if organization policy blocks this, an admin needs to allow it.
5. Click **Actions > Windows EXE Release > Run workflow** to produce a preliminary `.exe` as a downloadable **workflow artifact**, without creating a public release. Download it from the completed Actions run, and test it on a Windows PC with both Unity and Unreal games before publishing.

## Release a version

When the binary has been tested, create and push a version tag:

```powershell
git tag v2.2.0
git push origin v2.2.0
```

That triggers `.github/workflows/windows-release.yml` on a **Windows runner**, installs dependencies, runs Python tests, packages `MultiEngineAssetBrowser.exe` with PyInstaller, checks the executable, and publishes a **GitHub Release** with:

- `MultiEngineAssetBrowser.exe` (the Windows 64-bit standalone GUI binary)
- `MultiEngineAssetBrowser.exe.sha256` (checksum for the binary)
- GitHub's automatically generated source-code archives, which are **not** the end-user executable

Once this succeeds, the GitHub repository will show **Releases** on the right side of its Code page, like other open-source projects. Each future `v*` tag creates a new release. To prepare the next release, update `CHANGELOG.md`, test, tag `v2.3.0`, and push that tag.

**No binary gets published until a tagged Windows build succeeds.** Creating the repository alone will not create a release or an `.exe` asset.

## Building a standalone Windows EXE locally

Run `build_exe_windows.bat` on Windows with Python 3.11 x64 installed. It builds `dist\MultiEngineAssetBrowser.exe` from the source. The `.exe` bundles the Python interpreter and Python libraries, but does **not** include UE Viewer or Blender.

PyInstaller cannot directly cross-compile a Windows `.exe` from Linux/macOS. That's why this project uses `windows-latest` in GitHub Actions.

## Public repository checklist

- Check the repository contains source and documentation, but **no game archives, exported models, texture assets, AES keys, private directories, or credentials**.
- Verify third-party library licenses and their redistribution obligations before distributing packaged binaries.
- Confirm GitHub Actions tests and the packaged application smoke test pass.
- Download the exact executable produced by Actions and test it with your installed games on Windows.
- Publish the version tag and confirm the release has an `.exe` under Assets.
