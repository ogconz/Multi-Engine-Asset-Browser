# Replace Mesh / Texture — v1.1.0 development preview

This feature is being developed in stages. **No v1.1.0 release has been published or validated in actual games yet.** The public v1.0.2 release remains the recommended version.

## Workflow

1. Scan your game, and select one supported **Mesh / StaticMesh / SkeletalMesh / GameObject / Texture2D** row.
2. Click **Replace Mesh / Texture...**
3. Click **Preview Original** to view the selected game asset.
4. Click **Choose FBX / GLB...** or **Choose PNG / JPG...** and select your own file. Preview it using **Preview Replacement**.
5. Where in-game installation is implemented, choose **Install Replacement in Game**. No transform, scale or rotation adjustments are performed. You are responsible for asset dimensions, skeleton, UV and compatibility.

For FBX preview, the application needs a separately installed Blender; GLB and PNG/JPG previews use existing bundled libraries.

## Actual game-file support — read before using

| Engine and asset | Replacement preview | In-game installation |
|---|---|---|
| Unity Texture2D | Yes | **Experimental**: rewrite compatible Unity container using UnityPy |
| Unity Mesh / GameObject / renderer | Yes | **Not yet available**: needs a supported mesh writer or runtime mod loader |
| UE4 StaticMesh / SkeletalMesh | Yes | **Not yet available**: requires compatible cooked assets, packing and game mod-loading |
| UE4 Texture2D | Yes | **Not yet available**: requires compatible cooked texture assets and mod-loading |
| Unreal Engine 5 I/O Store | Not supported by current browser | Not supported |

**Do not interpret a successful preview as an installed mod.** Install is disabled in the GUI for combinations without a working adapter. Neither FBX nor GLB can be injected directly into an arbitrary cooked Unreal game archive. For UE4.27, asset import and cooking depend on a compatible Unreal project and game-specific packaging/mod load rules.

## Experimental Unity Texture2D installation

The browser uses UnityPy to locate a Texture2D by both its CAB and PathID, encode replacement pixels as RGBA32, rebuild the selected Unity container, and verify that the rebuilt container still contains the requested texture. This does **not** mean every Unity game will accept a modified archive.

**Important safeguards:**
- Close the game completely before replacing or restoring anything. Avoid online or anti-cheat-protected games.
- The application prompts you before writing, and stores a **full copy of the original game container** in the user's local application-data directory, outside the game.
- Replacements use an atomic file swap and retain the first original backup, even if you replace multiple textures in the same container.
- **Restore Original Game Archive** returns that entire game container to its backed-up state; it undoes all replacements the browser installed in that container since the backup.
- If a game update or another mod changes the container, automatic restore refuses to overwrite those changes. Make a backup before modifying any game installation.
- Re-encoding as uncompressed RGBA32 can increase the bundle size and remove its original mipmap chain. Some games may refuse the result, render differently, or regenerate the archive on update.
- File access permissions and file-format variants can prevent installation. An error should leave the original game file intact.

This feature is for authorized single-player/offline modding. It does not bypass DRM, anti-cheat, AES encryption or protected game formats. Only modify games and assets you have permission to modify.

## Planned adapters

Future work should investigate a compatible runtime loader or asset compiler for **Skater XL** meshes and a tested UE4.27 cooking/PAK override workflow for **Session: Skate Sim**. Other games require individually verified compatibility profiles; merely being built with Unity or Unreal is insufficient for automatic in-game replacement.
