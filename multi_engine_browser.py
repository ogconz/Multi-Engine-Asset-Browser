"""Multi-Engine Asset Browser v1.0.0 - Unity / Unreal desktop frontend.

Unreal 4 PAK: pyuepak for read-only indexing, UE Viewer (umodel.exe) on demand.
Unity: preserves Skater XL v1.1 paths, index, 3D preview and PNG/FBX/GLB exports.
"""
from __future__ import annotations

import io
import os
import sys
import time
import traceback
from pathlib import Path

from app_version import __version__
from frozen_pak import import_pakfile

os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtCore import Qt, QItemSelectionModel, QSettings, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor

from skaterxl_core import (
    BundleResolver, IMAGE_TYPES, Indexer, MODEL_TYPES,
    SceneExtractor, decode_texture_image, default_cache_path, error_summary,
    export_fbx, export_glb, export_png, find_blender_exe,
    known_types, query_assets,
)
from unreal_core import (
    UE_IMAGE_TYPES, UE_MODEL_TYPES, UE_PACKAGE_TYPE, UnrealExtractor,
    UnrealAutoInspector, UnrealIndexer, find_umodel_exe, query_unreal_assets,
    save_inspected_objects, unreal_asset_details, unreal_default_cache_path,
    unreal_errors, unreal_inspection_errors, unreal_known_types,
)
from multi_core import detect_engine, resolved_game_root, ui_can_export, ui_can_preview
from batch_core import can_batch_export, multi_select_allowed, plan_export_paths, run_batch_exports

DARK_STYLE = """
QMainWindow, QWidget { background: #151922; color: #e8eaf0; font-size: 12px; }
QLabel#appTitle { font-size: 21px; font-weight: 700; color: #f7f7fc; }
QLabel#subTitle { color: #a6b0c4; font-size: 12px; }
QLabel#summary { color: #adbbca; font-size: 11px; }
QPushButton { background: #293346; border: 1px solid #36435a; border-radius: 6px;
              padding: 8px 13px; font-weight: 600; color: #ecf2ff; }
QPushButton:hover { background: #34445c; }
QPushButton:pressed { background: #223048; }
QPushButton:disabled { color: #788193; background: #242a34; }
QPushButton#primary { background: #2460aa; border: 1px solid #3977ba; }
QPushButton#primary:hover { background: #3075c6; }
QLineEdit, QComboBox { background: #1e2531; color: #e9ecf4; border: 1px solid #374358;
                       border-radius: 6px; padding: 7px 9px; min-height: 20px; }
QTableWidget { background: #171e28; alternate-background-color: #1d2632;
               gridline-color: #273244; border: 1px solid #374358; border-radius: 5px;
               selection-background-color: #27558d; selection-color: white; }
QTableWidget::item { padding: 6px; }
QHeaderView::section { background: #263245; color: #b7c7d8;
                       border: 0; border-right: 1px solid #343e50; padding: 9px 5px;
                       font-weight: 700; }
QProgressBar { border: 1px solid #36435a; background: #232d3c;
               border-radius: 4px; height: 7px; color: transparent; }
QProgressBar::chunk { background: #4a95e2; border-radius: 3px; }
QPlainTextEdit { border: 1px solid #354056; border-radius: 5px;
                 background: #171e28; color: #b9c7d9; padding: 8px; }
QSplitter::handle { background: #333d50; }
"""


def safe_file_stem(name: str, fallback: str = "Asset") -> str:
    stem = "".join(ch if ch.isalnum() or ch in "-_. " else "_" for ch in name).strip(" ._")[:80]
    return stem or fallback


class ScanThread(QThread):
    progress = Signal(int, int, int, int, str)
    succeeded = Signal(int, int, int, int)
    failed = Signal(str)

    def __init__(self, engine: str, root: Path, db: Path, aes_key: str = ''):
        super().__init__()
        import threading
        self.cancel_event = threading.Event()
        self.engine, self.root, self.db, self.aes_key = engine, root, db, aes_key

    def run(self):
        try:
            if self.engine == 'Unreal':
                scanner = UnrealIndexer(self.root, self.db, self.aes_key)
            else:
                scanner = Indexer(self.root, self.db)
            result = scanner.scan(self.progress.emit, self.cancel_event)
            self.succeeded.emit(*result, getattr(scanner, 'iostore_count', 0))
        except Exception:
            self.failed.emit(traceback.format_exc())


class AutoIdentifyThread(QThread):
    """Verify each Unreal package's real classes in the background with UE Viewer."""
    progress = Signal(int, int, int, int, int, str)
    succeeded = Signal(int, int, int, int, int, bool)
    failed = Signal(str)

    def __init__(self, root: Path, db: Path, exe: str, game_override: str, aes_key: str):
        super().__init__()
        import threading
        self.cancel_event = threading.Event()
        self.root, self.db, self.exe = root, db, exe
        self.game_override, self.aes_key = game_override, aes_key
        self.context = ''

    def run(self):
        try:
            extractor = UnrealExtractor(self.root, self.exe, self.game_override, self.aes_key)
            self.context = extractor.inspection_context()
            result = UnrealAutoInspector(self.db, extractor).inspect_all(
                self.progress.emit, self.cancel_event)
            self.succeeded.emit(*result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class AssetThread(QThread):
    ready = Signal(object, object, object, object)
    failed = Signal(str)

    def __init__(self, engine, root, db, asset, mode,
                 target='', blender='', umodel='', ue_override='', aes_key=''):
        super().__init__()
        self.engine, self.root, self.db, self.asset, self.mode = engine, root, db, asset, mode
        self.target, self.blender, self.umodel = target, blender, umodel
        self.ue_override, self.aes_key = ue_override, aes_key

    def run(self):
        try:
            if self.engine == 'Unreal':
                extractor = UnrealExtractor(self.root, self.umodel, self.ue_override, self.aes_key)
                if self.mode == 'inspect':
                    rows = extractor.inspect(self.asset)
                    save_inspected_objects(self.db, self.asset, rows, extractor.inspection_context())
                    self.ready.emit(self.asset, rows, [], 'inspected')
                    return
                kind, result, warnings = extractor.extract(self.asset, self.mode)
                if self.mode == 'png':
                    if kind != 'image':
                        raise RuntimeError('Selected Unreal item did not decode as a texture')
                    export_png(result, self.target)
                elif self.mode in ('glb', 'fbx'):
                    if kind != 'scene':
                        raise RuntimeError('Selected Unreal item did not decode as a mesh')
                    if self.mode == 'glb':
                        export_glb(result, self.target)
                    else:
                        export_fbx(result, self.target, self.blender, Path(__file__).parent / 'blender_convert.py')
                else:
                    self.ready.emit(self.asset, result, warnings, kind)
                    return
                self.ready.emit(self.asset, self.target, warnings, 'saved')
                return
            resolver = BundleResolver(self.db)
            reader = resolver.lookup(self.asset)
            if self.mode == 'png' and self.asset.type != 'Texture2D':
                raise ValueError('Select a Texture2D to export a PNG')
            if self.asset.type in IMAGE_TYPES and self.mode in ('preview', 'png'):
                image = decode_texture_image(reader)
                if self.mode == 'png':
                    export_png(image, self.target)
                    self.ready.emit(self.asset, self.target, [], 'saved')
                else:
                    self.ready.emit(self.asset, image, [], 'image')
                return
            scene, warnings = SceneExtractor(resolver).extract(self.asset)
            if self.mode == 'glb':
                export_glb(scene, self.target)
                self.ready.emit(self.asset, self.target, warnings, 'saved')
            elif self.mode == 'fbx':
                export_fbx(scene, self.target, self.blender, Path(__file__).parent / 'blender_convert.py')
                self.ready.emit(self.asset, self.target, warnings, 'saved')
            else:
                self.ready.emit(self.asset, scene, warnings, 'scene')
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class BatchExportThread(QThread):
    """Run many independent mesh/texture exports without freezing the Qt GUI."""
    progress = Signal(int, int, int, int, str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, engine, root, db, jobs, kind, blender='', umodel='',
                 ue_override='', aes_key=''):
        super().__init__()
        import threading
        self.cancel_event = threading.Event()
        self.engine, self.root, self.db, self.jobs, self.kind = engine, root, db, jobs, kind
        self.blender, self.umodel = blender, umodel
        self.ue_override, self.aes_key = ue_override, aes_key

    def run(self):
        try:
            result = run_batch_exports(
                self.engine, self.root, self.db, self.jobs, self.kind,
                self.blender, self.umodel, self.ue_override, self.aes_key,
                progress=self.progress.emit, cancel=self.cancel_event,
            )
            self.succeeded.emit(result)
        except Exception as exc:
            message = f'{type(exc).__name__}: {exc}'
            if self.aes_key:
                message = message.replace(self.aes_key, '<redacted AES key>')
            self.failed.emit(message)


class ModelWindow(QMainWindow):
    """Independent model inspection window, orbit/zoom/pan courtesy of VTK."""

    def __init__(self, asset: AssetKey, scene, warnings):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"3D Preview | {asset.name} | Multi-Engine Browser")
        self.resize(1024, 750)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(10, 10, 10, 10)
        head = QHBoxLayout()
        title = QLabel(asset.name)
        title.setStyleSheet("font-size: 18px; font-weight: 700")
        head.addWidget(title, 1)
        reset = QPushButton("Reset view")
        reset.clicked.connect(self.reset_view)
        self.wire = QCheckBox("Wireframe")
        self.wire.stateChanged.connect(self.toggle_wireframe)
        head.addWidget(self.wire)
        head.addWidget(reset)
        layout.addLayout(head)
        self.plot = QtInteractor(body)
        layout.addWidget(self.plot.interactor, stretch=1)
        self.plot.set_background("#172231")
        self.plot.add_axes()
        self.plot.enable_trackball_style()
        self.actors = []
        vertices = 0
        faces = 0
        for node in scene.graph.nodes_geometry:
            transform, geometry_name = scene.graph.get(node)
            mesh = scene.geometry[geometry_name]
            if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
                continue
            vertices += len(mesh.vertices)
            faces += len(mesh.faces)
            points = trimesh_points(mesh.vertices, transform)
            poly = pv.PolyData(points, np.hstack([
                np.full((len(mesh.faces), 1), 3, dtype=np.int64),
                np.asarray(mesh.faces, dtype=np.int64),
            ]).ravel())
            texture = None
            try:
                uvs = getattr(mesh.visual, "uv", None)
                material = getattr(mesh.visual, "material", None)
                image = getattr(material, "baseColorTexture", None)
                if uvs is not None and image is not None and len(uvs) == len(points):
                    uv = np.asarray(uvs, dtype=float).copy()
                    # VTK image sampling expects the opposite V convention to glTF.
                    uv[:, 1] = 1.0 - uv[:, 1]
                    poly.active_texture_coordinates = uv
                    rgb = np.asarray(image.convert("RGBA"))
                    texture = pv.numpy_to_texture(rgb)
            except Exception:
                texture = None
            if texture is not None:
                actor = self.plot.add_mesh(poly, texture=texture, smooth_shading=True,
                                           show_edges=False, name=str(node),
                                           ambient=0.25, diffuse=0.75)
            else:
                actor = self.plot.add_mesh(poly, color="#a5b4c5", smooth_shading=True,
                                           show_edges=False, name=str(node),
                                           ambient=0.26, diffuse=0.72)
            self.actors.append(actor)
        footer = QLabel(f"{len(self.actors)} mesh parts  •  {vertices:,} vertices  •  {faces:,} triangles  •  Left-drag: orbit  •  Wheel: zoom  •  Middle-drag: pan")
        footer.setObjectName("summary")
        layout.addWidget(footer)
        if warnings:
            warning_text = "  |  ".join(dict.fromkeys(warnings))
            notice = QLabel(warning_text[:400])
            notice.setWordWrap(True)
            notice.setStyleSheet("color: #edc17b; font-size: 11px;")
            notice.setToolTip(warning_text)
            layout.addWidget(notice)
        self.setCentralWidget(body)
        self.reset_view()

    def toggle_wireframe(self, state):
        for actor in self.actors:
            if state:
                actor.GetProperty().SetRepresentationToWireframe()
            else:
                actor.GetProperty().SetRepresentationToSurface()
        self.plot.render()

    def reset_view(self):
        self.plot.reset_camera()
        self.plot.render()

    def closeEvent(self, event):
        self.plot.close()
        super().closeEvent(event)


def trimesh_points(vertices: np.ndarray, transform: np.ndarray) -> np.ndarray:
    xyz = np.asarray(vertices, dtype=np.float64)
    return xyz @ transform[:3, :3].T + transform[:3, 3]


class ImageWindow(QMainWindow):
    """Texture viewer with a direct PNG export action for Texture2D assets."""

    def __init__(self, asset: AssetKey, image):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"Texture Preview | {asset.name}")
        self.resize(880, 720)
        self.asset = asset
        self.image = image
        body = QWidget()
        layout = QVBoxLayout(body)
        toolbar = QHBoxLayout()
        label_info = QLabel(f"{asset.name}  •  {image.width} × {image.height} px  •  {image.mode}")
        label_info.setObjectName("summary")
        toolbar.addWidget(label_info, 1)
        if asset.type in ("Texture2D", "UnrealPackage"):
            save_button = QPushButton("Save PNG")
            save_button.clicked.connect(self.save_png)
            toolbar.addWidget(save_button)
        layout.addLayout(toolbar)
        scroll = QScrollArea()
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        buf = io.BytesIO()
        preview = image if image.mode in ("RGB", "RGBA", "L", "P") else image.convert("RGBA")
        preview.save(buf, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue())
        label.setPixmap(pixmap)
        label.resize(pixmap.size())
        scroll.setWidget(label)
        scroll.setWidgetResizable(False)
        layout.addWidget(scroll, 1)
        self.setCentralWidget(body)

    def save_png(self):
        name = safe_file_stem(self.asset.name, "Texture")
        output, _ = QFileDialog.getSaveFileName(
            self, "Save Texture2D as PNG", str(Path.home() / f"{name}.png"), "PNG images (*.png)"
        )
        if not output:
            return
        if not output.lower().endswith(".png"):
            output += ".png"
        try:
            export_png(self.image, output)
            QMessageBox.information(self, "PNG export complete", f"Saved texture:\n{output}")
        except Exception as exc:
            QMessageBox.warning(self, "PNG export failed", f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'Multi-Engine Asset Browser v{__version__} | Unity + Unreal')
        self.resize(1440, 850)
        self.settings = QSettings('MultiEngineTools', 'AssetBrowser')
        legacy_settings = QSettings('SkaterXLTools', 'AssetBrowser')
        suggested = r'D:\SteamLibrary\steamapps\common\Skater XL\SkaterXL_Data'
        self.root = Path(str(self.settings.value('folder', legacy_settings.value('folder', suggested)))).expanduser()
        self.engine = detect_engine(self.root)
        if self.engine == 'Unknown':
            self.engine = 'Unity'
        self.root = resolved_game_root(self.root, self.engine)
        self.db = self._cache_for(self.engine, self.root)
        self.scanner = None
        self.inspector = None
        self._after_scan_auto = False
        self._last_identify_table_refresh = 0.0
        self.current_worker = None
        self.batch_worker = None
        self._batch_folder = None
        self._result_count = 0
        self._total_results = 0
        self.viewers = []
        self.assets = []

        main_widget = QWidget()
        root_layout = QVBoxLayout(main_widget)
        root_layout.setContentsMargins(19, 17, 19, 12)
        root_layout.setSpacing(10)
        title = QLabel(f'Multi-Engine Asset Browser v{__version__}')
        title.setObjectName('appTitle')
        root_layout.addWidget(title)
        subtitle = QLabel('Unity bundles + Unreal Engine 4 PAKs | Search, preview in 3D, export GLB / FBX / PNG')
        subtitle.setObjectName('subTitle')
        root_layout.addWidget(subtitle)

        top = QHBoxLayout()
        top.addWidget(QLabel('ENGINE'))
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(['Auto', 'Unity', 'Unreal'])
        self.engine_combo.setMinimumWidth(110)
        self.engine_combo.currentTextChanged.connect(self._engine_choice_changed)
        top.addWidget(self.engine_combo)
        top.addWidget(QLabel('GAME FOLDER'))
        self.folder_input = QLineEdit(str(self.root))
        self.folder_input.setToolTip('Unity: select _Data or game root. Unreal: select game root or Content/Paks.')
        top.addWidget(self.folder_input, 1)
        browse = QPushButton('Browse...')
        browse.clicked.connect(self.choose_folder)
        self.browse_button = browse
        top.addWidget(browse)
        self.scan_button = QPushButton('Scan / Refresh')
        self.scan_button.setObjectName('primary')
        self.scan_button.clicked.connect(self.start_scan)
        top.addWidget(self.scan_button)
        self.cancel_button = QPushButton('Stop')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_scan)
        top.addWidget(self.cancel_button)
        root_layout.addLayout(top)

        self.unreal_options = QWidget()
        options = QHBoxLayout(self.unreal_options)
        options.setContentsMargins(0, 1, 0, 1)
        options.addWidget(QLabel('UE VIEWER'))
        self.umodel_edit = QLineEdit(str(self.settings.value('umodel_exe', find_umodel_exe())))
        self.umodel_edit.setPlaceholderText('Path to umodel.exe - required for Unreal preview / export')
        options.addWidget(self.umodel_edit, 1)
        choose_umodel = QPushButton('Select umodel.exe')
        choose_umodel.clicked.connect(self.browse_umodel)
        options.addWidget(choose_umodel)
        options.addWidget(QLabel('UE override'))
        self.ue_version_edit = QLineEdit(str(self.settings.value('ue_override', '')))
        self.ue_version_edit.setPlaceholderText('Auto (e.g. ue4.27)')
        self.ue_version_edit.setMaximumWidth(132)
        options.addWidget(self.ue_version_edit)
        options.addWidget(QLabel('PAK AES'))
        self.aes_edit = QLineEdit()
        self.aes_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.aes_edit.setPlaceholderText('Optional key - not saved')
        self.aes_edit.setMaximumWidth(170)
        options.addWidget(self.aes_edit)
        root_layout.addWidget(self.unreal_options)
        self.unreal_options.setVisible(self.engine == 'Unreal')

        self.auto_identify_options = QWidget()
        classify_row = QHBoxLayout(self.auto_identify_options)
        classify_row.setContentsMargins(0, 0, 0, 0)
        self.auto_identify_check = QCheckBox('Automatically identify Unreal asset types after scan')
        self.auto_identify_check.setChecked(self.settings.value('auto_identify', True, type=bool))
        self.auto_identify_check.setToolTip(
            'Uses UE Viewer to inspect individual packages after PAK indexing. '
            'The first pass can be slow; results are cached for future launches.')
        self.auto_identify_check.toggled.connect(
            lambda value: self.settings.setValue('auto_identify', value))
        classify_row.addWidget(self.auto_identify_check)
        self.identify_button = QPushButton('Identify existing packages')
        self.identify_button.setToolTip('Classify any as-yet-uninspected Unreal packages using UE Viewer.')
        self.identify_button.clicked.connect(self.start_auto_identify)
        classify_row.addWidget(self.identify_button)
        hint = QLabel('Background task  •  Stop to pause  •  Progress is cached')
        hint.setObjectName('summary')
        classify_row.addWidget(hint)
        classify_row.addStretch()
        root_layout.addWidget(self.auto_identify_options)
        self.auto_identify_options.setVisible(self.engine == 'Unreal')

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        root_layout.addWidget(self.progress)
        self.status = QLabel('Select your game folder and click Scan / Refresh. Unity needs no external exporter; Unreal needs UE Viewer.')
        self.status.setObjectName('summary')
        root_layout.addWidget(self.status)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search asset, package, texture, shoe, mesh, PAK path...')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.queue_refresh)
        filters.addWidget(self.search, 1)
        filters.addWidget(QLabel('Type'))
        self.type_combo = QComboBox()
        self.type_combo.setMinimumWidth(200)
        self.type_combo.addItems(['All', '3D candidates'])
        self.type_combo.currentTextChanged.connect(self.type_filter_changed)
        filters.addWidget(self.type_combo)
        self.result_label = QLabel('No index')
        self.result_label.setObjectName('summary')
        filters.addWidget(self.result_label)
        root_layout.addLayout(filters)
        self.selection_hint = QLabel('Choose a specific Type to enable Shift/Ctrl multi-selection.')
        self.selection_hint.setObjectName('summary')
        root_layout.addWidget(self.selection_hint)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['ASSET', 'TYPE', 'SOURCE', 'CAB / UE PACKAGE PATH', 'ID / EXPORT INDEX'])
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)  # All/3D candidates are single-select
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)
        for idx, width in enumerate([310, 165, 305, 430, 125]):
            self.table.setColumnWidth(idx, width)
        self.table.itemSelectionChanged.connect(self.selected_changed)
        self.table.cellDoubleClicked.connect(self.double_clicked)
        splitter.addWidget(self.table)
        diag = QWidget()
        dl = QVBoxLayout(diag)
        dl.setContentsMargins(3, 3, 3, 3)
        dl.addWidget(QLabel('SELECTED ASSET / DIAGNOSTICS'))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText('Unity: select a Mesh, GameObject, or Texture2D.\n'
                                  'Unreal: select a package and Inspect it to reveal objects inside.')
        dl.addWidget(self.details)
        splitter.addWidget(diag)
        splitter.setSizes([575, 155])
        root_layout.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.inspect_button = QPushButton('Inspect package objects')
        self.inspect_button.clicked.connect(self.inspect)
        bottom.addWidget(self.inspect_button)
        self.preview_button = QPushButton('Preview in 3D')
        self.preview_button.setObjectName('primary')
        self.preview_button.clicked.connect(self.preview)
        bottom.addWidget(self.preview_button)
        self.glb_button = QPushButton('Export GLB')
        self.glb_button.clicked.connect(lambda: self.export('glb'))
        bottom.addWidget(self.glb_button)
        self.fbx_button = QPushButton('Export FBX')
        self.fbx_button.clicked.connect(lambda: self.export('fbx'))
        bottom.addWidget(self.fbx_button)
        self.png_button = QPushButton('Export PNG')
        self.png_button.clicked.connect(lambda: self.export('png'))
        bottom.addWidget(self.png_button)
        bottom.addStretch()
        bottom.addWidget(QLabel('Read-only game input | Exports are separate files'))
        root_layout.addLayout(bottom)
        self.setCentralWidget(main_widget)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(240)
        self.search_timer.timeout.connect(self.refresh_results)
        self._update_selection_mode()
        self.update_buttons()
        if self.db.exists():
            self.update_types()
            self.refresh_results()
            self.status.setText(f'Saved {self.engine} index loaded. Click Scan / Refresh to check for changes.')

    def _cache_for(self, engine: str, root: Path) -> Path:
        return default_cache_path(root) if engine == 'Unity' else unreal_default_cache_path(root)

    def _engine_choice_changed(self, value: str):
        predicted = detect_engine(Path(self.folder_input.text().strip().strip('"')))
        is_unreal = value == 'Unreal' or (value == 'Auto' and predicted == 'Unreal')
        self.unreal_options.setVisible(is_unreal)
        self.auto_identify_options.setVisible(is_unreal)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select game root, Unity _Data, or Unreal Paks folder', str(self.root))
        if folder:
            self.folder_input.setText(folder)
            self._engine_choice_changed(self.engine_combo.currentText())

    def browse_umodel(self):
        found, _ = QFileDialog.getOpenFileName(self, 'Locate UE Viewer (umodel.exe)',
                                              str(Path.home()), 'UE Viewer (umodel.exe);;Executables (*.exe)')
        if found:
            self.umodel_edit.setText(found)
            self.settings.setValue('umodel_exe', found)

    def _requested_engine(self, root: Path) -> str:
        selected = self.engine_combo.currentText()
        if selected == 'Auto':
            selected = detect_engine(root)
            if selected == 'Unknown':
                raise ValueError('Could not auto-detect Unity or Unreal assets. Select the correct engine manually.')
        return selected

    def start_scan(self):
        if ((self.scanner and self.scanner.isRunning()) or
                (self.inspector and self.inspector.isRunning()) or
                (self.current_worker and self.current_worker.isRunning()) or
                (self.batch_worker and self.batch_worker.isRunning())):
            return
        entered = Path(self.folder_input.text().strip().strip('"')).expanduser()
        if not entered.is_dir():
            QMessageBox.warning(self, 'Folder not found', f'Select an existing folder:\n{entered}')
            return
        try:
            engine = self._requested_engine(entered)
            root = resolved_game_root(entered, engine)
        except ValueError as exc:
            QMessageBox.warning(self, 'Engine detection', str(exc))
            return
        self.engine, self.root = engine, root
        self.db = self._cache_for(engine, root)
        self.unreal_options.setVisible(engine == 'Unreal')
        self.auto_identify_options.setVisible(engine == 'Unreal')
        self._after_scan_auto = False
        self.folder_input.setText(str(root))
        self.settings.setValue('folder', str(root))
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.status.setText(f'Scanning {engine} assets... Unreal .pak scanning reads indexes only (not 16 GB of data).')
        self.scanner = ScanThread(engine, root, self.db, self.aes_edit.text() if engine == 'Unreal' else '')
        self.scanner.progress.connect(self.scan_progress)
        self.scanner.succeeded.connect(self.scan_completed)
        self.scanner.failed.connect(self.scan_failed)
        self.scanner.finished.connect(self.scan_finished)
        self.scanner.start()

    def cancel_scan(self):
        if self.scanner and self.scanner.isRunning():
            self.scanner.cancel_event.set()
            self.status.setText('Stopping after the current file finishes...')
            self.cancel_button.setEnabled(False)
        elif self.inspector and self.inspector.isRunning():
            self.inspector.cancel_event.set()
            self.status.setText('Stopping identification after the current package (up to 2 minutes)...')
            self.cancel_button.setEnabled(False)
        elif self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.cancel_event.set()
            self.status.setText('Stopping batch export after the current asset finishes...')
            self.cancel_button.setEnabled(False)

    def scan_progress(self, done, total, changed, errors, filename):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.status.setText(f'{self.engine}: {done:,}/{total:,} containers | {changed:,} changed | {errors:,} failures | {filename}')
        if done % 50 == 0:
            self.refresh_results()

    def scan_completed(self, done, changed, errors, iostore):
        self.update_types()
        self.refresh_results()
        message = f'{self.engine}: scanned {done:,} containers, {changed:,} updated, {errors:,} failed.'
        if self.engine == 'Unreal' and iostore:
            message += f' WARNING: {iostore} .utoc archives detected; I/O Store unsupported.'
        self.status.setText(message)
        self._after_scan_auto = (self.engine == 'Unreal' and self.auto_identify_check.isChecked()
                                 and not self.scanner.cancel_event.is_set())
        if errors:
            problems = unreal_errors(self.db) if self.engine == 'Unreal' else error_summary(self.db)
            self.details.setPlainText('Some files could not be indexed:\n\n' + '\n'.join(problems) +
                                      '\n\nOther successfully indexed packages are available.')

    def scan_failed(self, message):
        self.status.setText('Scan failed. Details below.')
        self.details.setPlainText(message)
        QMessageBox.critical(self, 'Scanner error', message[-3500:])

    def scan_finished(self):
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        self.scanner = None
        if self._after_scan_auto:
            self._after_scan_auto = False
            # Defer until the PAK index worker is fully shut down.
            QTimer.singleShot(0, self.start_auto_identify)
        self.update_buttons()

    def start_auto_identify(self):
        if self.engine != 'Unreal' or not self.db.is_file():
            return
        if ((self.inspector and self.inspector.isRunning()) or
                (self.scanner and self.scanner.isRunning()) or
                (self.current_worker and self.current_worker.isRunning()) or
                (self.batch_worker and self.batch_worker.isRunning())):
            return
        umodel = self._require_umodel()
        if not umodel:
            self.status.setText('Automatic Unreal type detection requires umodel.exe.')
            return
        self.inspector = AutoIdentifyThread(
            self.root, self.db, umodel, self.ue_version_edit.text().strip(),
            self.aes_edit.text().strip())
        self.inspector.progress.connect(self.identify_progress)
        self.inspector.succeeded.connect(self.identify_completed)
        self.inspector.failed.connect(self.identify_failed)
        self.inspector.finished.connect(self.identify_finished)
        self.scan_button.setEnabled(False)
        self.identify_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self._last_identify_table_refresh = 0.0
        self.status.setText('Identifying real Unreal asset classes using UE Viewer...')
        self.inspector.start()

    def identify_progress(self, done, total, identified, errors, object_count, filename):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.status.setText(
            f'Unreal classes: {done:,}/{total:,} packages | {object_count:,} objects found | '
            f'{errors:,} inspection failures | {filename}')
        # SQLite WAL permits refreshing the list while the background thread
        # saves inspected package classes.
        now = time.monotonic()
        if done == total or now - self._last_identify_table_refresh >= 2.5:
            self._last_identify_table_refresh = now
            self.update_types()
            self.refresh_results()

    def identify_completed(self, done, total, identified, errors, object_count, cancelled):
        self.update_types()
        self.refresh_results()
        if cancelled:
            message = (f'Identification paused at {done:,}/{total:,} packages. '
                       f'{object_count:,} typed objects cached; click Identify existing packages to resume.')
        elif total == 0:
            message = 'All Unreal packages have already been classified (cached results).'
        else:
            message = (f'Identified {identified:,}/{total:,} Unreal packages: '
                       f'{object_count:,} typed objects; {errors:,} failed.')
        self.status.setText(message)
        if errors and self.inspector:
            self.details.setPlainText(message + '\n\nInspection errors (first few):\n' + '\n'.join(
                unreal_inspection_errors(self.db, self.inspector.context)))

    def identify_failed(self, error):
        self.status.setText('Unreal automatic identification stopped with an error.')
        self.details.setPlainText(error)
        QMessageBox.warning(self, 'Asset type identification', error[-3500:])

    def identify_finished(self):
        self.inspector = None
        self.scan_button.setEnabled(True)
        self.identify_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
        self.update_buttons()

    def update_types(self):
        current = self.type_combo.currentText()
        types = unreal_known_types(self.db) if self.engine == 'Unreal' else known_types(self.db)
        choices = ['All', '3D candidates', *types]
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItems(choices)
        self.type_combo.setCurrentText(current if current in choices else 'All')
        self.type_combo.blockSignals(False)
        self._update_selection_mode()

    def _update_selection_mode(self):
        enabled = multi_select_allowed(self.type_combo.currentText())
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection if enabled
                                    else QTableWidget.SelectionMode.SingleSelection)
        if enabled:
            self.selection_hint.setText('Shift+click for a range, Ctrl+click to add items, Ctrl+A to select displayed rows. '
                                        'Multiple exports save into a folder.')
        else:
            self.selection_hint.setText('Select a specific asset type (e.g. Texture2D or StaticMesh) '
                                        'to enable Shift/Ctrl multi-selection.')

    def type_filter_changed(self):
        # Changing the type also changes which keyboard selection behavior is available.
        self.table.clearSelection()
        self._update_selection_mode()
        self.refresh_results()

    def queue_refresh(self):
        self.search_timer.start()

    def refresh_results(self):
        # Preserve multi-selection during background Unreal type identification,
        # which otherwise refreshes the table every few seconds.
        previously_selected = set(self.selected_keys()) if hasattr(self, 'table') else set()
        try:
            fn = query_unreal_assets if self.engine == 'Unreal' else query_assets
            assets, count = fn(self.db, self.search.text(), self.type_combo.currentText())
        except Exception as exc:
            self.status.setText(f'Index error: {exc}')
            return
        self.assets = assets
        self._result_count, self._total_results = len(assets), count
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(assets))
        for row, item in enumerate(assets):
            vals = [item.name, item.type, Path(item.bundle).name, item.cab,
                    str(item.path_id - 1) if self.engine == 'Unreal' and item.path_id else
                    ('-' if self.engine == 'Unreal' else str(item.path_id))]
            for col, val in enumerate(vals):
                cell = QTableWidgetItem(val)
                if col == 0:
                    cell.setToolTip(item.bundle)
                if col == 1:
                    if item.type in ('Mesh', 'StaticMesh', 'SkeletalMesh'):
                        cell.setForeground(QColor('#92dda9'))
                    elif item.type in MODEL_TYPES:
                        cell.setForeground(QColor('#99caff'))
                    elif item.type in IMAGE_TYPES:
                        cell.setForeground(QColor('#ebc388'))
                self.table.setItem(row, col, cell)
        # Keep selected assets that are still among the visible results.
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        sm = self.table.selectionModel()
        for row, asset in enumerate(assets):
            if asset in previously_selected:
                sm.select(self.table.model().index(row, 0), flags)
                if not multi_select_allowed(self.type_combo.currentText()):
                    break
        self.table.blockSignals(False)
        self.selected_changed()

    def selected_keys(self):
        if not hasattr(self, 'table'):
            return []
        rows = sorted(item.row() for item in self.table.selectionModel().selectedRows())
        return [self.assets[row] for row in rows if 0 <= row < len(self.assets)]

    def selected_key(self):
        keys = self.selected_keys()
        return keys[0] if keys else None

    def _update_result_label(self, count: int):
        label = f'Showing {self._result_count:,} / {self._total_results:,}'
        if count:
            label += f'   |   {count:,} selected'
        if self._total_results > self._result_count:
            self.result_label.setToolTip('Only displayed results can be selected (currently limited to 1,500 rows).')
        else:
            self.result_label.setToolTip('')
        self.result_label.setText(label)

    def selected_changed(self):
        keys = self.selected_keys()
        self._update_result_label(len(keys))
        self.update_buttons()
        if len(keys) > 1:
            kind = keys[0].type
            self.details.setPlainText(
                f'{len(keys):,} {kind} assets selected.\n\n'
                'Use Export PNG / GLB / FBX (as available) to choose an output folder.\n'
                'Every item is exported separately. Identical names receive numbered suffixes;\n'
                'existing files are not intentionally overwritten.\n\n'
                'Tip: Shift+click selects a range, Ctrl+click toggles items, '
                'Ctrl+A selects all currently displayed rows.')
            return
        if not keys:
            return
        key = keys[0]
        if self.engine == 'Unreal':
            self.details.setPlainText(unreal_asset_details(key))
        else:
            mode = ('3D preview, GLB/FBX' if key.type in MODEL_TYPES else
                    '2D preview, PNG' if key.type == 'Texture2D' else 'Indexed')
            self.details.setPlainText(
                f'Name:       {key.name}\nType:       {key.type}\nBundle:     {key.bundle}\n'
                f'Unity CAB:  {key.cab}\nPath ID:    {key.path_id}\nAvailable:  {mode}\n\n'
                'Scan the entire game Data folder to resolve meshes in external bundles.')

    def update_buttons(self):
        keys = self.selected_keys() if hasattr(self, 'table') else []
        key = keys[0] if len(keys) == 1 else None
        many = len(keys) > 1
        busy = bool(self.batch_worker) or any(w and w.isRunning() for w in (self.current_worker, self.scanner))
        identifying = bool(self.inspector and self.inspector.isRunning())
        self.inspect_button.setEnabled(bool(key and self.engine == 'Unreal' and not busy and not identifying))
        self.inspect_button.setVisible(self.engine == 'Unreal')
        self.preview_button.setEnabled(bool(key and ui_can_preview(self.engine, key.type) and not busy))
        img = bool(key and key.type in IMAGE_TYPES)
        self.preview_button.setText('Preview texture' if img else 'Preview in 3D / texture')
        for kind, button in [('glb', self.glb_button), ('fbx', self.fbx_button), ('png', self.png_button)]:
            if many:
                allowed = can_batch_export(self.engine, keys, self.type_combo.currentText(), kind)
                button.setText(f'Export {len(keys):,} {kind.upper()}s')
                button.setEnabled(allowed and not busy and not identifying)
            else:
                button.setText(f'Export {kind.upper()}')
                button.setEnabled(bool(key and ui_can_export(self.engine, key.type, kind) and not busy))

    def double_clicked(self, *args):
        if len(self.selected_keys()) != 1:
            return
        key = self.selected_key()
        if key and self.engine == 'Unreal' and key.type == UE_PACKAGE_TYPE:
            self.inspect()
        else:
            self.preview()

    def _require_umodel(self) -> str:
        exe = self.umodel_edit.text().strip().strip('"')
        if not Path(exe).is_file():
            exe = find_umodel_exe()
        if not exe or not Path(exe).is_file():
            self.browse_umodel()
            exe = self.umodel_edit.text().strip().strip('"')
        if not exe or not Path(exe).is_file():
            return ''
        self.umodel_edit.setText(exe)
        self.settings.setValue('umodel_exe', exe)
        self.settings.setValue('ue_override', self.ue_version_edit.text().strip())
        return exe

    def inspect(self):
        key = self.selected_key()
        if not key or self.engine != 'Unreal':
            return
        umodel = self._require_umodel()
        if umodel:
            self.launch_task(key, 'inspect', umodel=umodel)

    def preview(self):
        key = self.selected_key()
        if not key or not ui_can_preview(self.engine, key.type):
            return
        umodel = self._require_umodel() if self.engine == 'Unreal' else ''
        if self.engine == 'Unity' or umodel:
            self.launch_task(key, 'preview', umodel=umodel)

    def export(self, kind: str):
        keys = self.selected_keys()
        if not keys:
            return
        bulk = len(keys) > 1
        if bulk:
            if not can_batch_export(self.engine, keys, self.type_combo.currentText(), kind):
                QMessageBox.warning(self, 'Select one asset type',
                                    'Batch export requires a specific Type filter and '
                                    'assets supporting the chosen output format.')
                return
            if self.inspector and self.inspector.isRunning():
                QMessageBox.information(self, 'Identification running',
                                        'Stop or finish type identification before batch exporting.')
                return
        elif not ui_can_export(self.engine, keys[0].type, kind):
            return
        umodel = self._require_umodel() if self.engine == 'Unreal' else ''
        if self.engine == 'Unreal' and not umodel:
            return
        blender = ''
        if kind == 'fbx':
            blender = str(self.settings.value('blender_exe', ''))
            if not blender or not Path(blender).is_file():
                blender = find_blender_exe() or ''
            if not blender or not Path(blender).is_file():
                blender, _ = QFileDialog.getOpenFileName(self, 'Locate Blender for FBX export',
                                                        str(Path.home()), 'Blender (blender.exe);;Executables (*.exe)')
                if not blender:
                    return
            self.settings.setValue('blender_exe', blender)

        if bulk:
            folder = QFileDialog.getExistingDirectory(
                self, f'Export {len(keys):,} {kind.upper()} files to folder',
                str(self.settings.value('export_folder', str(Path.home()))))
            if not folder:
                return
            try:
                jobs = plan_export_paths(keys, Path(folder), kind)
            except Exception as exc:
                QMessageBox.warning(self, 'Batch export destination', f'{type(exc).__name__}: {exc}')
                return
            self.settings.setValue('export_folder', folder)
            self.start_batch_export(jobs, kind, blender, umodel)
            return

        key = keys[0]
        default = safe_file_stem(key.name, 'Texture' if kind == 'png' else 'Model')
        file_filter = f'{kind.upper()} files (*.{kind})'
        dest, _ = QFileDialog.getSaveFileName(self, f'Export {kind.upper()}',
                                              str(Path.home() / f'{default}.{kind}'), file_filter)
        if not dest:
            return
        if not dest.lower().endswith('.' + kind):
            dest += '.' + kind
        self.launch_task(key, kind, dest, blender, umodel)

    def start_batch_export(self, jobs, kind: str, blender='', umodel=''):
        if any(w and w.isRunning() for w in (self.batch_worker, self.current_worker,
                                            self.scanner, self.inspector)):
            return
        self._batch_folder = jobs[0][1].parent
        self.batch_worker = BatchExportThread(
            self.engine, self.root, self.db, jobs, kind, blender, umodel,
            self.ue_version_edit.text().strip() if self.engine == 'Unreal' else '',
            self.aes_edit.text().strip() if self.engine == 'Unreal' else '',
        )
        self.batch_worker.progress.connect(self.batch_progress)
        self.batch_worker.succeeded.connect(self.batch_completed)
        self.batch_worker.failed.connect(self.batch_failed)
        self.batch_worker.finished.connect(self.batch_finished)
        self.scan_button.setEnabled(False)
        self.identify_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        for widget in (self.table, self.type_combo, self.search, self.engine_combo,
                       self.folder_input, self.browse_button, self.unreal_options):
            widget.setEnabled(False)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.status.setText(f'Batch export: preparing {len(jobs):,} {kind.upper()} files...')
        self.batch_worker.start()
        self.update_buttons()

    def batch_progress(self, done, total, saved, failed, name):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.status.setText(f'Exported {done:,}/{total:,} assets | {saved:,} saved | '
                            f'{failed:,} failed | Latest: {name}')

    def batch_completed(self, result):
        folder = str(self._batch_folder)
        state = ('Stopped early' if result.cancelled else 'Finished')
        summary = (f'{state}: {len(result.successful):,} exported, '
                   f'{len(result.failures):,} failed, {result.total - result.attempted:,} skipped.\n'
                   f'Output folder: {folder}')
        lines = [summary]
        if result.failures:
            lines += ['\nFailed assets:']
            for name, error in result.failures:
                lines.append(f'- {name}: {error}')
        self.details.setPlainText('\n'.join(lines))
        self.status.setText(summary.replace('\n', ' | '))
        if result.failures:
            QMessageBox.warning(self, 'Batch export completed with errors',
                                summary + '\n\nSee diagnostics for the failed asset names and reasons.')
        else:
            QMessageBox.information(self, 'Batch export complete', summary)

    def batch_failed(self, message):
        self.status.setText('Batch export could not start; see diagnostics.')
        self.details.setPlainText(message)
        QMessageBox.warning(self, 'Batch export error', message[:3500])

    def batch_finished(self):
        self.batch_worker = None
        self.scan_button.setEnabled(True)
        self.identify_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        for widget in (self.table, self.type_combo, self.search, self.engine_combo,
                       self.folder_input, self.browse_button, self.unreal_options):
            widget.setEnabled(True)
        self.update_buttons()

    def launch_task(self, key, mode, target='', blender='', umodel=''):
        if ((self.current_worker and self.current_worker.isRunning()) or
                (self.batch_worker and self.batch_worker.isRunning())):
            return
        self.current_worker = AssetThread(
            self.engine, self.root, self.db, key, mode, target, blender, umodel,
            self.ue_version_edit.text().strip() if self.engine == 'Unreal' else '',
            self.aes_edit.text().strip() if self.engine == 'Unreal' else ''
        )
        self.current_worker.ready.connect(self.task_ready)
        self.current_worker.failed.connect(self.task_failed)
        self.current_worker.finished.connect(self.task_finished)
        self.current_worker.start()
        verb = 'Inspecting' if mode == 'inspect' else 'Loading' if mode == 'preview' else 'Exporting'
        self.status.setText(f'{verb} {key.name}...')
        self.update_buttons()

    def task_ready(self, key, result, warnings, kind):
        if kind == 'inspected':
            self.update_types()
            # Search for the asset name so the package and its children remain visible.
            self.refresh_results()
            self.status.setText(f'Found {len(result):,} objects in {key.name}. Select a StaticMesh / SkeletalMesh / Texture2D child.')
            self.details.setPlainText(unreal_asset_details(key) + '\n\nIdentified objects:\n' +
                                      '\n'.join(f'{typ}  {name}' for _, typ, name in result[:120]))
        elif kind == 'scene':
            try:
                win = ModelWindow(key, result, warnings)
                self.viewers.append(win)
                win.destroyed.connect(lambda *_: self._forget_viewer(win))
                win.show()
                self.status.setText(f'3D preview loaded: {key.name}')
            except Exception as exc:
                QMessageBox.critical(self, '3D viewer error', f'{type(exc).__name__}: {exc}')
        elif kind == 'image':
            win = ImageWindow(key, result)
            self.viewers.append(win)
            win.destroyed.connect(lambda *_: self._forget_viewer(win))
            win.show()
            self.status.setText(f'Texture preview loaded: {key.name}')
        elif kind == 'saved':
            self.status.setText(f'Saved {Path(result).name} to {Path(result).parent}')
            QMessageBox.information(self, 'Export complete', f'Saved file:\n{result}\n\n' + '\n'.join(warnings[:4]))

    def _forget_viewer(self, win):
        if win in self.viewers:
            self.viewers.remove(win)

    def task_failed(self, message):
        self.status.setText('Unable to process this asset. See diagnostics.')
        self.details.setPlainText(message)
        QMessageBox.warning(self, 'Asset unavailable', message[:4300])

    def task_finished(self):
        self.current_worker = None
        self.update_buttons()

    def closeEvent(self, event):
        if self.scanner and self.scanner.isRunning():
            QMessageBox.information(self, 'Scanning', 'Click Stop and wait for the current PAK/bundle before exiting.')
            event.ignore()
            return
        if self.batch_worker and self.batch_worker.isRunning():
            QMessageBox.information(self, 'Batch export',
                                    'Click Stop and wait for the current asset to finish before exiting.')
            event.ignore()
            return
        if self.current_worker and self.current_worker.isRunning():
            QMessageBox.information(self, 'Asset operation', 'Wait for this preview/export operation to finish.')
            event.ignore()
            return
        if self.inspector and self.inspector.isRunning():
            QMessageBox.information(self, 'Identifying assets',
                                    'Click Stop and wait for the current package before exiting. '
                                    'Already identified packages are cached.')
            event.ignore()
            return
        for win in list(self.viewers):
            win.close()
        super().closeEvent(event)


def _packaged_self_test(output_file: str) -> int:
    """Windows CI smoke test: verify bundled imports and Qt/VTK without a GUI."""
    import traceback
    try:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        import UnityPy  # noqa: F401 - included in the frozen distribution
        # Loading an asset dynamically accesses this module and its bundled
        # lzma.tpk data. Plain "import UnityPy" doesn't catch missing resources.
        from importlib import resources as package_resources
        import UnityPy.resources  # noqa: F401
        tpk_file = package_resources.files('UnityPy.resources').joinpath('lzma.tpk')
        with tpk_file.open('rb') as tpk_stream:
            if not tpk_stream.read(16):
                raise RuntimeError('Missing/empty UnityPy.resources/lzma.tpk in EXE')
        # A Texture2D preview loads UnityPy.export, which eagerly imports
        # AudioClipConverter and (otherwise) loads native FMOD audio DLLs.
        # Exercise this precise import path to prevent broken GUI previews.
        from UnityPy.export import Texture2DConverter  # noqa: F401
        import fmod_toolkit
        if not getattr(fmod_toolkit, '_meab_optional_audio_disabled', False):
            raise RuntimeError('Audio-only FMOD dependency was not disabled in frozen EXE')
        import_pakfile()  # exercises frozen pyuepak/Oodle runtime
        import cryptography  # noqa: F401
        import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
        import vtkmodules.vtkInteractionStyle  # noqa: F401
        import vtkmodules.vtkRenderingFreeType  # noqa: F401
        app = QApplication([sys.argv[0]])
        mesh = pv.Sphere(theta_resolution=8, phi_resolution=8)
        assert mesh.n_points > 0
        assert app is not None
        result, code = 'OK\n', 0
    except BaseException:
        result, code = traceback.format_exc(), 1
    Path(output_file).write_text(result, encoding='utf-8')
    return code


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == '--self-test':
        raise SystemExit(_packaged_self_test(sys.argv[2]))
    app = QApplication(sys.argv)
    app.setApplicationName('Multi-Engine Asset Browser')
    app.setApplicationVersion(__version__)
    app.setOrganizationName('MultiEngineTools')
    app.setStyle('Fusion')
    app.setStyleSheet(DARK_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
