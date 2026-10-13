"""Batch exports for Unity / Unreal assets, independently testable without Qt.

A typed filter is required for selecting multiple assets. Export uses the same
per-asset decoders as the single-item workflow; one failure does not end a batch.
Never overwrite files already in the output folder, even for duplicate names.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from multi_core import ui_can_export
from skaterxl_core import (
    BundleResolver, SceneExtractor, decode_texture_image,
    export_fbx, export_glb, export_png,
)
from unreal_core import UnrealExtractor, UE_PACKAGE_TYPE

FORMATS = ('png', 'glb', 'fbx')
INACTIVE_FILTERS = ('', 'All', '3D candidates', UE_PACKAGE_TYPE)
WINDOWS_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


def multi_select_allowed(type_filter: str) -> bool:
    """Only an explicitly selected, real asset class enables Shift/Ctrl select."""
    return type_filter not in INACTIVE_FILTERS


def can_batch_export(engine: str, assets: Sequence, type_filter: str, kind: str) -> bool:
    """Require a single exportable class; no mixed or uninspected packages."""
    return (
        kind in FORMATS
        and len(assets) > 1
        and multi_select_allowed(type_filter)
        and all(asset.type == type_filter and ui_can_export(engine, asset.type, kind)
                for asset in assets)
    )


def safe_export_stem(name: str, fallback: str = 'Asset') -> str:
    """Portable Windows-safe filename stem (no directories or device names)."""
    stem = ''.join(c if c.isalnum() or c in '-_. ' else '_' for c in str(name))
    stem = stem.strip(' ._')[:80].rstrip(' .')
    if not stem:
        stem = fallback
    if stem.split('.', 1)[0].upper() in WINDOWS_RESERVED:
        stem = '_' + stem
    return stem


def plan_export_paths(assets: Sequence, folder: Path | str, kind: str) -> list[tuple[object, Path]]:
    """Reserve unique names within the batch and across *existing* output files.

    Deliberately casefolds for Windows filesystem compatibility. Only plans
    names; it does not create files or folders before the user starts export.
    """
    ext = kind.lower()
    if ext not in FORMATS:
        raise ValueError(f'Unsupported export format: {kind}')
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f'Choose an existing export folder: {folder}')
    used = {p.name.casefold() for p in folder.iterdir()}
    planned: list[tuple[object, Path]] = []
    for asset in assets:
        base = safe_export_stem(asset.name, 'Texture' if ext == 'png' else 'Model')
        number = 1
        while True:
            suffix = '' if number == 1 else f'_{number}'
            # Limit base to keep full file names Windows-friendly.
            stem = base[:max(1, 80 - len(suffix))].rstrip(' ._')
            filename = f'{stem}{suffix}.{ext}'
            if filename.casefold() not in used:
                break
            number += 1
        used.add(filename.casefold())
        planned.append((asset, folder / filename))
    return planned


@dataclass
class BatchResult:
    successful: list[Path]
    failures: list[tuple[str, str]]
    attempted: int
    total: int
    cancelled: bool


def run_batch_exports(
    engine: str, root: Path, db: Path, jobs: Sequence[tuple[object, Path]],
    kind: str, blender: str = '', umodel: str = '', ue_override: str = '', aes_key: str = '',
    progress: Callable[[int, int, int, int, str], None] | None = None,
    cancel: threading.Event | None = None,
) -> BatchResult:
    """Read game assets without modifications, exporting each item independently.

    Heavy extraction runs on a Qt worker thread in the desktop application.
    Cancellation is cooperative, checked between items (Blender/UE Viewer may
    take some time to finish the currently running item).
    """
    if kind not in FORMATS:
        raise ValueError(f'Unsupported export format: {kind}')
    if engine not in ('Unreal', 'Unity'):
        raise ValueError(f'Unknown engine: {engine}')
    if any(asset.type == UE_PACKAGE_TYPE or not ui_can_export(engine, asset.type, kind)
           for asset, _ in jobs):
        raise ValueError('Batch export requires typed, exportable assets.')

    # One resolver/extractor per batch reduces repeated setup work.
    extractor = UnrealExtractor(root, umodel, ue_override, aes_key) if engine == 'Unreal' else None
    resolver = BundleResolver(db) if engine == 'Unity' else None
    successful: list[Path] = []
    failures: list[tuple[str, str]] = []
    attempted = 0

    for asset, dest in jobs:
        if cancel and cancel.is_set():
            break
        attempted += 1
        try:
            if engine == 'Unreal':
                result_type, result, _warnings = extractor.extract(asset, kind)
                expected = 'image' if kind == 'png' else 'scene'
                if result_type != expected:
                    raise RuntimeError(f'Expected {expected} but Unreal extractor returned {result_type}.')
            elif kind == 'png':
                result = decode_texture_image(resolver.lookup(asset))
            else:
                result, _warnings = SceneExtractor(resolver).extract(asset)

            if kind == 'png':
                export_png(result, dest)
            elif kind == 'glb':
                export_glb(result, dest)
            else:
                export_fbx(result, dest, blender, Path(__file__).parent / 'blender_convert.py')
            successful.append(dest)
        except Exception as exc:
            message = f'{type(exc).__name__}: {exc}'
            if aes_key:
                message = message.replace(aes_key, '<redacted AES key>')
            failures.append((asset.name, message))
        if progress:
            progress(attempted, len(jobs), len(successful), len(failures), asset.name)

    return BatchResult(successful, failures, attempted, len(jobs),
                       bool(cancel and cancel.is_set()))
