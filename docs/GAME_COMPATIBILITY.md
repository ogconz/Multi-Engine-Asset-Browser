# Game compatibility and configuration

Compatibility is based on publicly documented engine formats and community testing, not guaranteed across every game version or update. This application reads local game files; games and third-party extractors are **not** bundled.

## Session: Skate Sim (PC)

| Field in Multi-Engine Asset Browser | Value |
|---|---|
| Engine | **Unreal** |
| Unreal Engine version | **4.27** |
| UE override (exact string) | `ue4.27` |
| UE Viewer executable | `umodel.exe` (download separately) |
| Typical archive | `SessionGame/Content/Paks/pakchunk0-WindowsNoEditor.pak` |
| PAK AES key (community-reported) | `0x2d0e2b103cf0b3cb5ea8d6b774ea49400d36bd431f4bdeff74f99261bd1dabdc` |

### How to use these settings

1. Point **Game Folder** to your local Session installation (or its `SessionGame/Content/Paks` folder).
2. Choose **Engine → Unreal**.
3. Select the official [UE Viewer / UModel](https://www.gildor.org/en/projects/umodel) `umodel.exe`.
4. Enter **`ue4.27`** in **UE override** (not `4.27` or `-game=ue4.27`).
5. Paste the entire **PAK AES** hexadecimal value above, starting with `0x`, into the **PAK AES** field.
6. Click **Scan / Refresh**. With automatic identification enabled, the program will attempt to classify package contents into Texture2D, StaticMesh, SkeletalMesh and other types.

**Accuracy / rights:** This key worked on a community-tested Session installation and may not work on newer updates or different distribution platforms. It is **not** a GitHub password, application credential or license key; it is an archive AES value. The browser does not save the entered key, auto-discover keys, modify the game installation, or include an AES value in its EXE. Only inspect content you are authorized to use; extracting assets does not authorize redistribution of those assets.

## Skater XL (Unity)

- **Engine:** Unity or Auto.
- **Game folder:** select the game's `SkaterXL_Data` directory to load dependencies from across Unity bundles.
- **UE override / PAK AES:** not applicable.
- **Export:** GLB / FBX for supported meshes and PNG for Texture2D assets.

## Other Unity and Unreal games

Engine compatibility varies by asset version and format; `ue4.27` is a **Session-specific example**, not a recommended default for all Unreal games. Keep the UE override empty for other games until you know the engine version. Some PAK archives are not encrypted and need no AES key. Unreal Engine 5 I/O Store `.utoc/.ucas` is not supported by the current backend.
