"""Shared engine discovery and launch helpers. Deliberately independent of Qt."""
from __future__ import annotations

import os
from pathlib import Path

from skaterxl_core import game_data_path


def detect_engine(root: Path) -> str:
    """Return 'Unity', 'Unreal', or 'Unknown' without reading the entire game."""
    root = Path(root)
    if not root.is_dir():
        return 'Unknown'
    if root.name.lower().endswith('_data'):
        return 'Unity'
    if (root / 'SkaterXL_Data').is_dir():
        return 'Unity'
    if root.name.lower() == 'paks' or (root / 'SessionGame' / 'Content' / 'Paks').is_dir():
        return 'Unreal'
    if (root / 'Content' / 'Paks').is_dir():
        return 'Unreal'
    seen = 0
    for folder, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in {'.git', '.venv', '__pycache__'}]
        lower = [n.lower() for n in names]
        if any(n.endswith(('.pak', '.utoc', '.ucas')) for n in lower):
            return 'Unreal'
        if any(n.endswith(('.bundle', '.unity3d', '.assets')) for n in lower):
            return 'Unity'
        seen += 1
        if seen >= 500:
            break
    return 'Unknown'


def resolved_game_root(root: Path, engine: str) -> Path:
    root = Path(root).expanduser().resolve()
    return game_data_path(root) if engine == 'Unity' else root


def ui_can_preview(engine: str, typ: str) -> bool:
    if engine == 'Unity':
        from skaterxl_core import MODEL_TYPES, IMAGE_TYPES
        return typ in MODEL_TYPES + IMAGE_TYPES
    from unreal_core import UE_EXPORTABLE_TYPES
    return typ in UE_EXPORTABLE_TYPES


def ui_can_export(engine: str, typ: str, ext: str) -> bool:
    if engine == 'Unity':
        from skaterxl_core import MODEL_TYPES
        return typ == 'Texture2D' if ext == 'png' else typ in MODEL_TYPES
    from unreal_core import UE_MODEL_TYPES, UE_IMAGE_TYPES, UE_PACKAGE_TYPE
    allowed = UE_IMAGE_TYPES if ext == 'png' else UE_MODEL_TYPES
    return typ in allowed or typ == UE_PACKAGE_TYPE
