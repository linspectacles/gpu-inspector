#!/usr/bin/env python3
"""LinSpectacles GPU Inspector 0.0.4: explicit read-only Linux DRM inspection."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from PyQt6.QtCore import Qt, QSettings, QUrl
from PyQt6.QtGui import QIcon, QKeySequence, QPixmap, QColor, QTextCharFormat, QTextCursor, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget, QTableWidgetItem
)

from ._support import (
    BaseInspectorTab, STANDALONE_STYLESHEET,
    export_records_dialog, metadata_font_qss
)
from .collectors import discover
from .procfs import (scan_clients, memory_records, engine_records, raw_driver_fields,
                     engine_names, memory_names)
from .presentation import matches_search, sorted_records

APPLET_ID = 'linspectacles-gpu-inspector'
APPLET_NAME = 'GPU Inspector'
APPLET_VERSION = '0.0.4'
APPLET_REPOSITORY = 'https://github.com/linspectacles/gpu-inspector'
ORGANISATION = 'LinSpectacles'
ORGANISATION_ID = 'linspectacles'

VIEWS = ('GPUs', 'DRM Nodes', 'Clients', 'Memory', 'Engines')
COLUMNS = {
    'GPUs': [
        ('gpu', 'GPU', 220, 'left'), ('pci_address', 'PCI Address', 150, 'left'),
        ('vendor_device', 'Vendor / Device', 185, 'left'), ('driver', 'Driver', 130, 'left'),
        ('drm_card', 'DRM Card', 115, 'left'), ('render_node', 'Render Node', 120, 'left'),
        ('numa', 'NUMA Node', 110, 'left'), ('iommu', 'IOMMU Group', 125, 'left'),
    ],
    'DRM Nodes': [
        ('node', 'Node', 125, 'left'), ('type', 'Type', 110, 'left'),
        ('gpu', 'GPU', 210, 'left'), ('pci_address', 'PCI Address', 155, 'left'),
        ('driver', 'Driver', 130, 'left'), ('major_minor', 'Major:Minor', 110, 'left'),
        ('device_path', 'Device Path', 220, 'left'),
    ],
    'Clients': [
        ('process', 'Process', 160, 'left'), ('pid', 'PID', 95, 'right'),
        ('gpu', 'GPU', 210, 'left'), ('client_id', 'Client ID', 110, 'left'),
        ('client_name', 'Client Name', 175, 'left'), ('drm_node', 'DRM Node', 115, 'left'),
        ('fd', 'FD', 65, 'right'), ('engine_names', 'Engines', 155, 'left'),
        ('memory_names', 'Memory Regions', 170, 'left'),
    ],
    'Memory': [
        ('gpu', 'GPU', 180, 'left'), ('process', 'Process', 160, 'left'),
        ('pid', 'PID', 90, 'right'), ('client_id', 'Client ID', 95, 'left'),
        ('region', 'Region', 125, 'left'), ('total', 'Total', 140, 'right'),
        ('shared', 'Shared', 140, 'right'), ('resident', 'Resident', 140, 'right'),
        ('purgeable', 'Purgeable', 140, 'right'), ('active', 'Active', 140, 'right'),
    ],
    'Engines': [
        ('gpu', 'GPU', 160, 'left'), ('process', 'Process', 155, 'left'),
        ('pid', 'PID', 80, 'right'), ('client_id', 'Client ID', 95, 'left'),
        ('engine', 'Engine', 130, 'left'), ('busy_time', 'Busy Time', 150, 'right'),
        ('capacity', 'Capacity', 95, 'right'), ('busy_cycles', 'Busy Cycles', 140, 'right'),
        ('total_cycles', 'Total Cycles', 140, 'right'),
        ('max_frequency', 'Max Frequency', 135, 'right'),
    ],
}

SOURCES_TEXT = """GPU Inspector is read-only. Its displayed facts come from these interfaces.

GPU and DRM node inventory, device association and major/minor values
  /sys/class/drm/
  /dev/dri/ (device node presence and ordinary filesystem facts)

GPU PCI identity, bound driver, NUMA and IOMMU relationships
  /sys/bus/pci/devices/<BDF>/...

Visible process DRM descriptors and client information
  /proc/<pid>/fd/<fd>
  /proc/<pid>/fdinfo/<fd>

Optional AMDGPU device-level memory information
  /sys/bus/pci/devices/<BDF>/mem_info_vram_*
  /sys/bus/pci/devices/<BDF>/mem_info_vis_vram_*
  /sys/bus/pci/devices/<BDF>/mem_info_gtt_*

Important distinctions
  The GPU and DRM-node inventory is obtained from sysfs; no GPU vendor utility is required.
  Client, memory-region and engine records are limited to DRM fdinfo readable by the current user.
  AMDGPU device-level memory values are separate from DRM per-client memory accounting.
  DRM engine busy-time values are cumulative counters, not live utilisation percentages.
  Unreported fields are displayed as Not reported; no unsupported estimate or zero is introduced.
  The applet does not scan debugfs, use NVML, elevate privileges or change device state.
"""


def reported(value):
    if value is None or value == '' or value == []:
        return 'Not reported'
    return str(value)


class GPUOptions(QDialog):
    """Kernel Modules 0.0.5 Options shell, adapted only for GPU's five inventories."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("Options — GPU Inspector")
        self.resize(980, 720)

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # Appearance: same layout and component order as Kernel Modules.
        appearance_page = QWidget()
        appearance_layout = QVBoxLayout(appearance_page)
        appearance_layout.setContentsMargins(12, 12, 12, 12)
        appearance_layout.setSpacing(10)

        appearance_heading = QLabel("Metadata display")
        heading_font = appearance_heading.font()
        heading_font.setBold(True)
        appearance_heading.setFont(heading_font)
        appearance_layout.addWidget(appearance_heading)

        appearance_note = QLabel(
            "Choose how the inventory and Metadata Details panes are arranged. "
            "This GPU Inspector setting is remembered."
        )
        appearance_note.setWordWrap(True)
        appearance_layout.addWidget(appearance_note)

        layout_row = QHBoxLayout()
        layout_row.addWidget(QLabel("Record details layout:"))
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["Horizontal", "Vertical"])
        self.layout_combo.setCurrentText(
            "Vertical" if owner.details_orientation == "vertical" else "Horizontal"
        )
        self.layout_combo.currentTextChanged.connect(self._layout_changed)
        layout_row.addWidget(self.layout_combo)
        layout_row.addStretch(1)
        appearance_layout.addLayout(layout_row)

        self.show_metadata_panel = QCheckBox("Show Metadata Details panel (F3)")
        self.show_metadata_panel.setChecked(owner.metadata_panel_visible)
        self.show_metadata_panel.toggled.connect(self._metadata_panel_changed)
        appearance_layout.addWidget(self.show_metadata_panel)

        shortcut_note = QLabel(
            "F3 hides/restores Metadata Details. Shift+F5 refreshes the active GPU view. "
            "Ctrl+L toggles Horizontal/Vertical layout. Ctrl+/ opens Options. "
            "Right-click an inventory column heading to show/hide columns."
        )
        shortcut_note.setWordWrap(True)
        appearance_layout.addWidget(shortcut_note)
        appearance_layout.addStretch(1)
        tabs.addTab(appearance_page, "Appearance")

        # Sources
        sources_page = QWidget()
        sources_layout = QVBoxLayout(sources_page)
        sources_layout.setContentsMargins(12, 12, 12, 12)
        sources_layout.setSpacing(10)

        sources_heading = QLabel("Data Sources")
        sources_heading_font = sources_heading.font()
        sources_heading_font.setBold(True)
        sources_heading_font.setPointSize(max(sources_heading_font.pointSize(), 11))
        sources_heading.setFont(sources_heading_font)
        sources_layout.addWidget(sources_heading)

        sources_note = QLabel(
            "Linux interfaces used by this read-only GPU/DRM inspector."
        )
        sources_note.setWordWrap(True)
        sources_layout.addWidget(sources_note)

        sources_text = QTextEdit()
        sources_text.setReadOnly(True)
        sources_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        chosen_font = getattr(owner, "_metadata_font", None)
        if chosen_font is not None:
            sources_text.setFont(chosen_font)
            sources_text.document().setDefaultFont(chosen_font)
            sources_text.setCurrentFont(chosen_font)
            font_rule = metadata_font_qss(chosen_font)
        else:
            font_rule = ""
        sources_text.setStyleSheet(
            "QTextEdit { "
            + font_rule
            + " background-color: #151719; color: #dcdcdc; "
              "border: 1px solid #333333; }"
        )

        source_key_format = QTextCharFormat()
        source_key_format.setForeground(QColor("#9cdcfe"))
        source_key_format.setFontWeight(600)
        source_value_format = QTextCharFormat()
        source_value_format.setForeground(QColor("#dcdcdc"))

        cursor = sources_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for line in owner.sources_text().splitlines():
            if line and not line[:1].isspace():
                cursor.insertText(line + "\n", source_key_format)
            else:
                cursor.insertText(line + "\n", source_value_format)
        sources_text.setTextCursor(cursor)
        sources_text.moveCursor(QTextCursor.MoveOperation.Start)
        sources_layout.addWidget(sources_text, 1)
        tabs.addTab(sources_page, "Sources")

        # Export: Kernel Modules checkbox pattern, using the active GPU view.
        export_page = QWidget()
        export_layout = QVBoxLayout(export_page)
        export_layout.setContentsMargins(12, 12, 12, 12)
        export_layout.setSpacing(10)

        export_heading = QLabel("Export details")
        export_heading_font = export_heading.font()
        export_heading_font.setBold(True)
        export_heading.setFont(export_heading_font)
        export_layout.addWidget(export_heading)

        export_note = QLabel(
            "Select the already-collected GPU details to include in the export. "
            "Export never scans unopened views."
        )
        export_note.setWordWrap(True)
        export_layout.addWidget(export_note)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Scope:"))
        self.scope_combo = QComboBox()
        self.scope_combo.addItems(["Active view", "All currently collected views"])
        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        scope_row.addWidget(self.scope_combo)
        scope_row.addStretch(1)
        export_layout.addLayout(scope_row)

        self.export_checkboxes = []
        for column in COLUMNS[owner.view]:
            checkbox = QCheckBox(column[1])
            checkbox.setChecked(True)
            export_layout.addWidget(checkbox)
            self.export_checkboxes.append((checkbox, column))
        self.export_metadata = QCheckBox("Metadata Details")
        self.export_metadata.setChecked(False)
        export_layout.addWidget(self.export_metadata)
        self.all_views_note = QLabel(
            "All collected views exports their available columns and acquisition fields; "
            "Metadata Details is optional."
        )
        self.all_views_note.setWordWrap(True)
        export_layout.addWidget(self.all_views_note)
        self._scope_changed()

        export_layout.addStretch(1)
        export_row = QHBoxLayout()
        export_row.addStretch(1)
        export_button = QPushButton("Export...")
        export_button.clicked.connect(self._export_selected)
        export_row.addWidget(export_button)
        export_layout.addLayout(export_row)
        tabs.addTab(export_page, "Export")

        # About
        about_page = QWidget()
        about_layout = QVBoxLayout(about_page)
        about_layout.setContentsMargins(24, 20, 24, 18)
        about_layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(112, 112)
        icon_path = Path(__file__).resolve().parent / "icon.png"
        if icon_path.is_file():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                icon_label.setPixmap(
                    pixmap.scaled(
                        112,
                        112,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        about_layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        name = QLabel("<h2 style='margin:0'>GPU Inspector</h2>")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(name)

        version = QLabel(f"Version {APPLET_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(version)

        slogan = QLabel("<b>Expose. Explore. Explain.</b>")
        slogan.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(slogan)

        description = QLabel(
            "A read-only LinSpectacles applet for inspecting GPUs, DRM device nodes, "
            "visible clients and reported memory/engine statistics."
        )
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(description)

        details = QLabel(
            "<b>Build:</b> Standalone LinSpectacles applet<br>"
            "<b>Organisation ID:</b> "
            "<a href='https://github.com/linspectacles/'>linspectacles</a><br>"
            f"<b>Applet ID:</b> {APPLET_ID}"
        )
        details.setWordWrap(True)
        details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details.setOpenExternalLinks(True)
        details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(details)

        copyright_label = QLabel(
            "Copyright © 2026 "
            "<a href='https://github.com/brunonlinespace'>brunonlinespace</a>"
        )
        copyright_label.setOpenExternalLinks(True)
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(copyright_label)

        license_label = QLabel("Licensed under GNU GPLv3 or later.")
        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(license_label)

        readme_url = QUrl.fromLocalFile(
            str(Path(__file__).resolve().parent.parent / "README.md")
        ).toString()
        license_url = QUrl.fromLocalFile(
            str(Path(__file__).resolve().parent.parent / "LICENSE")
        ).toString()
        links = QLabel(
            f"<a href='{readme_url}'>README</a>"
            "&nbsp;·&nbsp; "
            f"<a href='{license_url}'>License</a>"
            "&nbsp;·&nbsp; "
            "<a href='https://github.com/linspectacles/gpu-inspector'>Repository</a>"
        )
        links.setOpenExternalLinks(True)
        links.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout.addWidget(links)
        about_layout.addStretch(1)
        tabs.addTab(about_page, "About")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _layout_changed(self, text):
        self.owner.set_details_orientation(str(text).strip().lower(), persist=True)

    def _metadata_panel_changed(self, visible):
        self.owner.set_metadata_panel_visible(bool(visible), persist=True)

    def _scope_changed(self, *_):
        all_views = self.scope_combo.currentIndex() == 1
        for checkbox, _column in self.export_checkboxes:
            checkbox.setVisible(not all_views)
        self.all_views_note.setVisible(all_views)

    def _export_selected(self):
        all_collected = self.scope_combo.currentIndex() == 1
        if all_collected:
            selected = [("view", "View", 150, "left")]
            seen = {"view"}
            for view in self.owner._cache:
                for column in COLUMNS[view]:
                    if column[0] not in seen:
                        selected.append(column)
                        seen.add(column[0])
        else:
            selected = [column for checkbox, column in self.export_checkboxes if checkbox.isChecked()]
        if self.export_metadata.isChecked():
            selected.append(("metadata_details", "Metadata Details", 520, "left"))
        if not selected:
            QMessageBox.information(self, "Export", "Select at least one detail to export.")
            return
        selected.extend([
            ("acquired", "Acquired", 170, "left"),
            ("source_paths", "Source Paths", 290, "left"),
        ])
        records = self.owner.export_records(all_collected, include_metadata=self.export_metadata.isChecked())
        if not records:
            QMessageBox.information(self, "Export", "There is no collected data to export yet.")
            return
        path = export_records_dialog(self, APPLET_NAME, records, columns=selected)
        if path is not None:
            self.owner.set_status(f"Exported data to {path}")


class GPUInspectorTab(BaseInspectorTab):
    """Five-view inspector using the pre-existing LinSpectacles inventory shell."""
    def __init__(self, parent=None):
        self.view = 'GPUs'
        super().__init__('GPUs', COLUMNS['GPUs'], ['All Drivers'], parent)
        self._settings = QSettings('brunonlinespace', APPLET_ID)
        self._host_columns_callback = None
        self._host_column_settings = {}
        self._busy = False
        self._cache = {}                 # view -> immutable-by-convention, already acquired snapshot
        self._times = {}                 # view -> acquisition time
        self._client_snapshot = None     # shared data for first opening another lazy view
        self._coverage = None
        self._device_gpus = []
        self._device_nodes = []
        self._device_time = None
        self._node_signature = None
        self._status_messages = {}
        self.export_title = APPLET_NAME

        # Preserve the authoritative Kernel Modules top-row layout and controls:
        # count at left | stretch | View: | selector | Refresh List | Options...
        self.stats_label.setText('GPUs: 0')
        self.view_label = QLabel('View:')
        self.view_label.setStyleSheet('font-weight: 600;')
        self.view_choice = QComboBox()
        self.view_choice.addItems(VIEWS)
        self.view_choice.setMinimumWidth(145)
        refresh_index = self.dash_layout.indexOf(self.refresh_btn)
        self.dash_layout.insertWidget(refresh_index, self.view_label)
        self.dash_layout.insertWidget(refresh_index + 1, self.view_choice)
        self.view_choice.currentTextChanged.connect(self.change_view)

        # As in Kernel Modules, use the original rightmost export button as Options.
        self.export_btn.setText('Options...')
        try:
            self.export_btn.clicked.disconnect()
        except TypeError:
            pass
        self.export_btn.clicked.connect(self.open_options)
        self.export_btn.setEnabled(True)

        self.category_label.setText('Driver:')
        self.search_entry.setPlaceholderText('Search current inventory…')
        # Table frame, alternating rows, header and all pane styling are now
        # entirely the unmodified Kernel Modules _support.py implementation.
        self.details_orientation = 'horizontal'
        self._load_details_orientation()
        self.metadata_panel_visible = True
        self._load_metadata_panel_visibility()
        self._select_shortcuts()
        self._refresh_devices(startup=True)
        self._present_view('GPUs')
        self.set_status(self._status_messages['GPUs'])

    def _select_shortcuts(self):
        for key, action in (
            ('F3', self.toggle_metadata_panel),
            ('Ctrl+L', self.toggle_details_orientation),
            ('Shift+F5', self.load_modules),
            ('Ctrl+/', self.open_options),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)
            if not hasattr(self, '_shortcuts'):
                self._shortcuts = []
            self._shortcuts.append(shortcut)

    def apply_host_settings(self, settings=None, column_visibility_callback=None):
        """Preserve host-owned Metadata Details font; per-view column state is local."""
        settings = settings or {}
        self._host_columns_callback = column_visibility_callback
        self._host_column_settings = dict(settings)
        super().apply_host_settings(settings, column_visibility_callback)
        self._apply_saved_columns()

    def _apply_saved_columns(self):
        try:
            default = json.dumps(self._host_column_settings.get('hidden_columns', [])) if self.view == 'GPUs' else '[]'
            hidden = json.loads(self._settings.value(f'columns/{self.view}', default))
        except (TypeError, ValueError):
            hidden = []
        self.column_visibility.apply_hidden(hidden)

    def _columns_changed(self, hidden):
        self._settings.setValue(f'columns/{self.view}', json.dumps(hidden))
        if self._host_columns_callback:
            self._host_columns_callback(hidden)

    def _store_current_columns(self):
        if self.column_visibility:
            self._settings.setValue(f'columns/{self.view}', json.dumps(self.column_visibility.hidden_columns()))

    def _load_metadata_panel_visibility(self):
        value = self._settings.value('metadata_panel_visible', True)
        if isinstance(value, str):
            visible = value.strip().lower() not in {'0', 'false', 'no', 'off'}
        else:
            visible = bool(value)
        self.set_metadata_panel_visible(visible, persist=False)

    def set_metadata_panel_visible(self, visible, *, persist=True):
        self.metadata_panel_visible = bool(visible)
        details_panel = self.splitter.widget(1)
        if details_panel is not None:
            details_panel.setVisible(self.metadata_panel_visible)
        if self.metadata_panel_visible:
            self.set_details_orientation(self.details_orientation, persist=False)
        if persist:
            self._settings.setValue('metadata_panel_visible', self.metadata_panel_visible)
            self._settings.sync()

    def toggle_metadata_panel(self):
        self.set_metadata_panel_visible(not self.metadata_panel_visible, persist=True)

    def _load_details_orientation(self):
        orientation = str(
            self._settings.value('details_orientation', 'horizontal') or 'horizontal'
        ).lower()
        if orientation not in {'horizontal', 'vertical'}:
            orientation = 'horizontal'
        self.set_details_orientation(orientation, persist=False)

    def set_details_orientation(self, orientation, *, persist=True):
        orientation = str(orientation or 'horizontal').lower()
        if orientation not in {'horizontal', 'vertical'}:
            orientation = 'horizontal'
        self.details_orientation = orientation

        details_panel = self.splitter.widget(1)
        details_layout = details_panel.layout() if details_panel is not None else None
        if orientation == 'vertical':
            self.splitter.setOrientation(Qt.Orientation.Vertical)
            if details_layout is not None:
                details_layout.setContentsMargins(0, 8, 0, 0)
            self.splitter.setSizes([430, 330])
        else:
            self.splitter.setOrientation(Qt.Orientation.Horizontal)
            if details_layout is not None:
                details_layout.setContentsMargins(8, 0, 0, 0)
            self.splitter.setSizes([480, 700])

        if persist:
            self._settings.setValue('details_orientation', orientation)
            self._settings.sync()

    def toggle_details_orientation(self):
        target = 'vertical' if self.details_orientation == 'horizontal' else 'horizontal'
        self.set_details_orientation(target, persist=True)

    def open_options(self):
        GPUOptions(self).exec()

    @staticmethod
    def sources_text():
        return SOURCES_TEXT

    @staticmethod
    def _inventory_signature(nodes):
        # Stable DRM identities, not the acquisition time.
        return tuple(sorted((str(n.get('rdev')), str(n.get('gpu_key')),
                             str(n.get('sys_device')), str(n.get('device_path')))
                            for n in nodes))

    def _refresh_devices(self, startup=False):
        gpus, nodes, stamp = discover()
        signature = self._inventory_signature(nodes)
        if self._node_signature is not None and signature != self._node_signature:
            # Invalidate shared lazy client material, not already collected views:
            # their timestamps and data remain truthful until explicitly refreshed.
            self._client_snapshot = None
        self._device_gpus, self._device_nodes, self._device_time = gpus, nodes, stamp
        self._node_signature = signature
        if startup or self.view == 'GPUs':
            self._cache['GPUs'] = list(self._device_gpus)
            self._times['GPUs'] = self._device_time
            self._status_messages['GPUs'] = (
                f'Refreshed GPU inventory: {len(self._device_gpus)} GPU(s) · {len(self._device_nodes)} DRM node(s).'
            )

    def _acquire_clients(self):
        clients, coverage, stamp = scan_clients(self._device_nodes)
        for client in clients:
            client['scan_coverage'] = dict(coverage)
            fields = client['fields']
            client['engine_names'] = ', '.join(engine_names(fields)) or 'Not reported'
            client['memory_names'] = ', '.join(memory_names(fields)) or 'Not reported'
        self._client_snapshot = (clients, coverage, stamp)
        return self._client_snapshot

    @staticmethod
    def _coverage_suffix(coverage):
        return (f'{coverage["inaccessible"]} process(es) inaccessible · '
                f'{coverage["vanished"]} process(es) vanished during scan · '
                f'{coverage["inaccessible_fds"]} FD(s) inaccessible · '
                f'{coverage["vanished_fds"]} FD(s) vanished during scan · '
                f'{coverage["fd_errors"]} FD/process read error(s).')

    def _make_view(self, view, force_scan=False):
        if view == 'GPUs':
            if force_scan:
                self._refresh_devices()
            return list(self._device_gpus), self._device_time
        if view == 'DRM Nodes':
            if force_scan:
                self._refresh_devices()
            self._status_messages[view] = (
                f'Refreshed DRM nodes: {len(self._device_nodes)} node(s) across {len(self._device_gpus)} GPU(s).'
            )
            return list(self._device_nodes), self._device_time
        if force_scan:
            # A client-based view depends on CURRENT DRM-node identities. This
            # discovery does not refresh unopened or unrelated displayed views.
            self._refresh_devices()
        if force_scan or self._client_snapshot is None:
            clients, coverage, stamp = self._acquire_clients()
        else:
            clients, coverage, stamp = self._client_snapshot
        self._coverage = coverage
        if coverage.get('scan_error'):
            self._status_messages[view] = (
                f'{view} acquisition failed: {coverage["scan_error"]}. '
                'Zero results are not evidence of no DRM clients.'
            )
            return [], stamp
        no_nodes_note = 'No usable DRM nodes discovered; process FD scan not performed.' if not any(
            n.get('rdev') is not None for n in self._device_nodes) else ''
        suffix = self._coverage_suffix(coverage)
        if view == 'Clients':
            records = list(clients)
            self._status_messages[view] = (
                f'Refreshed DRM clients: {len(records)} client(s) from '
                f'{coverage["accessible"]} accessible process(es) · {suffix}'
            ) if not no_nodes_note else no_nodes_note
        elif view == 'Memory':
            records = memory_records(clients)
            device_count = sum(bool(g['device_memory']) for g in self._device_gpus)
            self._status_messages[view] = (
                f'Memory: {len(records)} client-region record(s) from DRM fdinfo · '
                f'device memory reported by {device_count} GPU(s) · {suffix}'
            ) if not no_nodes_note else no_nodes_note
        else:
            records = engine_records(clients)
            self._status_messages[view] = (
                f'Engines: {len(records)} reported client-engine record(s) from DRM fdinfo · {suffix}'
            ) if records else (
                f'No standard DRM client engine statistics were reported for visible clients · {suffix}'
            )
            if no_nodes_note:
                self._status_messages[view] = no_nodes_note
        return records, stamp

    def load_modules(self):
        self.refresh_active()

    def refresh_active(self):
        self._busy = True
        try:
            records, stamp = self._make_view(self.view, force_scan=True)
            self._cache[self.view] = records
            self._times[self.view] = stamp
            self._present_view(self.view)
            self.set_status(self._status_messages[self.view])
        except Exception as exc:
            self.set_status(f'Unable to refresh {self.view}: {exc}')
        finally:
            self._busy = False

    def change_view(self, view):
        if view == self.view or self._busy:
            return
        self._store_current_columns()
        self.view = view
        try:
            if view not in self._cache:
                records, stamp = self._make_view(view)
                self._cache[view] = records
                self._times[view] = stamp
            self._present_view(view)
            self.set_status(self._status_messages.get(view, f'Collected {view}.'))
        except Exception as exc:
            self._cache[view] = []
            self._present_view(view)
            self.set_status(f'Unable to acquire {view}: {exc}')

    def _selector_items(self, view):
        if view == 'GPUs':
            options = sorted(set(g['driver'] for g in self._cache.get(view, [])))
            return 'Driver:', ['All Drivers'] + options
        if view == 'DRM Nodes':
            types = sorted(set(n['type'] for n in self._cache.get(view, []) if n['type']))
            return 'Type:', ['All Types'] + types
        values = sorted(set(r.get('gpu', 'Not reported') for r in self._cache.get(view, [])))
        return 'GPU:', ['All GPUs'] + values

    def _present_view(self, view):
        self.columns = COLUMNS[view]
        self.modules_data = self._cache.get(view, [])
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(0)
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels([column[1] for column in self.columns])
        for i, (_, _, width, _) in enumerate(self.columns):
            self.table.setColumnWidth(i, width)
            self.table.setColumnHidden(i, False)
        self.column_visibility.columns = list(self.columns)
        self.column_visibility.set_changed_callback(self._columns_changed)
        self._apply_saved_columns()
        self.table.blockSignals(False)
        self.category_label.setText(self._selector_items(view)[0])
        self.category_dropdown.blockSignals(True)
        self.category_dropdown.clear()
        self.category_dropdown.addItems(self._selector_items(view)[1])
        self.category_dropdown.blockSignals(False)
        self.stats_label.setText(f'{view}: {len(self.modules_data)}')
        self.filter_modules()

    def filter_modules(self, *_):
        # The Kernel Modules inventory/selection contract is authoritative:
        # clear stale details; rebuild visible rows; select a visible row;
        # then render details from that selected row, outside blocked signals.
        if not hasattr(self, 'view') or not hasattr(self, '_cache'):
            return
        previous = self.current_record()
        query = self.search_entry.text().strip().lower()
        selector = self.category_dropdown.currentText()
        records = []
        for item in self.modules_data:
            match = (selector.startswith('All ') or
                     (self.view == 'GPUs' and item.get('driver') == selector) or
                     (self.view == 'DRM Nodes' and item.get('type') == selector) or
                     (self.view in ('Clients', 'Memory', 'Engines') and item.get('gpu') == selector))
            if not match:
                continue
            if not matches_search(item, query):
                continue
            records.append(item)

        blocked = self.table.blockSignals(True)
        try:
            self.clear_info()
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(records))
            for row, record in enumerate(records):
                for index, (key, _title, _width, alignment) in enumerate(self.columns):
                    cell = QTableWidgetItem(reported(record.get(key, 'Not reported')))
                    if index == 0:
                        cell.setData(Qt.ItemDataRole.UserRole, record)
                    cell.setTextAlignment(
                        (Qt.AlignmentFlag.AlignRight if alignment == 'right' else Qt.AlignmentFlag.AlignLeft)
                        | Qt.AlignmentFlag.AlignVCenter
                    )
                    self.style_table_item(cell, key, record)
                    self.table.setItem(row, index, cell)
            if records:
                target = next((i for i, record in enumerate(records) if record is previous), 0)
                self.table.setCurrentCell(target, 0)
                self.table.selectRow(target)
        finally:
            self.table.blockSignals(blocked)

        if records:
            self.on_module_select()
        else:
            self.clear_info()
        if query or not selector.startswith('All '):
            self.filter_status_lbl.setText(f'(Showing {len(records)} of {len(self.modules_data)} items)')
        else:
            self.filter_status_lbl.clear()

    def _section(self, title):
        self.append_info(f'--- {title} ---\n')

    def _details(self, entries):
        for key, value in entries:
            self.append_key_value(key, reported(value))

    def _sources(self, record, view=None):
        self.append_info('\n')
        self._section('Acquisition')
        source_fields = record.get('source_fields', [])
        unavailable = sum(1 for item in source_fields if item.get('state') not in
                          ('Reported',) and not str(item.get('state', '')).startswith('Reported →'))
        note_count = len(record.get('source_notes', []))
        failures = any(('Inaccessible' in str(item.get('state', '')) or
                        'failed' in str(item.get('state', '')).lower() or
                        'Unresolved' in str(item.get('state', '')))
                       for item in source_fields)
        scan_coverage = record.get('scan_coverage', {})
        limited_scan = any(scan_coverage.get(name, 0) for name in
                           ('inaccessible', 'vanished', 'inaccessible_fds', 'vanished_fds', 'fd_errors'))
        read_state = ('Partial / unavailable sources documented below' if failures or note_count or limited_scan
                      else ('Ordinary-user read-only; optional fields absent (listed below)'
                            if unavailable else 'Ordinary-user read-only; reported sources available'))
        self._details([('Acquired', record.get('acquired')),
                       ('Read State', read_state)])
        for source in dict.fromkeys(record.get('sources', [])):
            self.append_key_value('Source', source)
        # Distinguish a successfully read source from an optional absent sysfs
        # field, permission denial, or a failed symlink resolution.
        for item in source_fields:
            self.append_key_value('Source Field',
                                  f'{item["field"]} — {item["path"]} — {item["state"]}')
        for note in dict.fromkeys(record.get('source_notes', [])):
            self.append_key_value('Availability Note', note)
        coverage = record.get('scan_coverage')
        if (view or self.view) in ('Clients', 'Memory', 'Engines') and coverage:
            self.append_key_value('Process Scan', coverage.get('scan_state', 'Not reported'))
            if coverage.get('scan_error'):
                self.append_key_value('Scan Error', coverage['scan_error'])
            self.append_key_value('Process/FD Coverage', self._coverage_suffix(coverage))

    def on_module_select(self):
        record = self.current_record()
        self.clear_info()
        if record is not None:
            self._render_record_details(record, self.view)

    def _render_record_details(self, record, view):
        if view == 'GPUs':
            self._section('GPU Identity')
            self._details([('GPU', record['gpu']), ('PCI Address', record.get('pci_address')),
                           ('PCI Class', record.get('class')), ('Vendor ID', record.get('vendor')),
                           ('Device ID', record.get('device')), ('Subsystem Vendor ID', record.get('subsystem_vendor')),
                           ('Subsystem Device ID', record.get('subsystem_device')), ('Revision', record.get('revision'))])
            self.append_info('\n'); self._section('Driver')
            self._details([('Bound Driver', record.get('driver')), ('Driver Module', record.get('module')),
                           ('Driver Source', record.get('driver_path')), ('boot_vga', record.get('boot_vga'))])
            self.append_info('\n'); self._section('DRM')
            for node in record.get('nodes', []):
                self._details([(f'{node["type"]} Node', node['device_path']),
                               (f'{node["node"]} Major:Minor', node.get('major_minor'))])
            if not record.get('nodes'):
                self._details([('Nodes', 'Not reported')])
            self.append_info('\n'); self._section('Topology')
            self._details([('NUMA Node', record.get('numa')), ('IOMMU Group', record.get('iommu')),
                           ('PCIe Current Link Speed', record.get('current_link_speed')),
                           ('PCIe Current Link Width', record.get('current_link_width')),
                           ('PCIe Max Link Speed', record.get('max_link_speed')),
                           ('PCIe Max Link Width', record.get('max_link_width'))])
            if record.get('device_memory'):
                self.append_info('\n'); self._section('AMDGPU — Device Memory (separate from client memory)')
                self._details([(k, f'{v:,} bytes') for k, v in record['device_memory'].items()])
        elif view == 'DRM Nodes':
            self._section('DRM Node')
            self._details([('Node', record.get('node')), ('Type', record.get('type')),
                           ('Device Path', record.get('device_path')), ('Sysfs Path', record.get('sys_path')),
                           ('Major:Minor', record.get('major_minor')), ('GPU', record.get('gpu')),
                           ('PCI Address', record.get('pci_address')), ('Driver', record.get('driver')),
                           ('GPU Association', record.get('association')),
                           ('Device Present / Matching', record.get('device_confirmed', 'Not confirmed')), 
                           ('Filesystem Mode', record.get('mode')),
                           ('UID', record.get('uid')), ('GID', record.get('gid'))])
        else:
            self._section('Process')
            self._details([('Process', record.get('process')), ('PID', record.get('pid')),
                           ('Visible PIDs Sharing This Client', ', '.join(str(pid) for pid in record.get('pids', []))),
                           ('Command', record.get('command')), ('UID', record.get('uid')),
                           ('User', record.get('user'))])
            self.append_info('\n'); self._section('DRM Client')
            self._details([('GPU', record.get('gpu')), ('DRM Node', record.get('drm_node')),
                           ('FD', record.get('fd')), ('Shared / Duplicated FDs', ', '.join(record.get('fds', []))),
                           ('drm-client-id', record.get('client_id')), ('drm-client-name', record.get('client_name')),
                           ('drm-pdev', record.get('pdev')), ('drm-driver', record.get('drm_driver'))])
            if view == 'Memory':
                self.append_info('\n'); self._section('Reported Memory Region')
                self._details([('Region', record['region'])] + [(key.title(), record[key]) for key in
                               ('total', 'shared', 'resident', 'purgeable', 'active')])
                if record.get('legacy_memory') is not None:
                    self._details([('Legacy drm-memory (resident alias)', record['legacy_memory'])])
            elif view == 'Engines':
                self.append_info('\n'); self._section('Reported Engine — Cumulative Counters')
                self._details([('Engine', record['engine'])] + [(label, record[key]) for label, key in
                               [('Busy Time', 'busy_time'), ('Capacity', 'capacity'),
                                ('Busy Cycles', 'busy_cycles'), ('Total Cycles', 'total_cycles'),
                                ('Max Frequency', 'max_frequency')]])
            self.append_info('\n'); self._section('Reported Engines')
            engine_keys = [(k, v) for k, v in record['fields'].items() if k.startswith(
                ('drm-engine-', 'drm-engine-capacity-', 'drm-cycles-', 'drm-total-cycles-', 'drm-maxfreq-'))]
            self._details(engine_keys or [('Engine Fields', 'Not reported')])
            self.append_info('\n'); self._section('Reported Memory Regions')
            memory_keys = [(k, v) for k, v in record['fields'].items() if k.startswith(
                ('drm-total-', 'drm-shared-', 'drm-resident-', 'drm-purgeable-', 'drm-active-', 'drm-memory-'))
                and not k.startswith('drm-total-cycles-')]
            self._details(memory_keys or [('Memory Fields', 'Not reported')])
            raw = raw_driver_fields(record)
            if raw:
                self.append_info('\n'); self._section('Raw Driver Fields (uninterpreted)')
                self._details(raw.items())
        self._sources(record, view)
        self.info_text.moveCursor(QTextCursor.MoveOperation.Start)

    def sort_by(self, column_id):
        # Same current-snapshot behaviour as before, but true numeric/counter
        # order rather than lexical ordering of PID, FD, bytes or cycles.
        reverse = self._sort_reverse.get((self.view, column_id), False)
        self.modules_data[:] = sorted_records(self.modules_data, column_id, reverse)
        self._sort_reverse[(self.view, column_id)] = not reverse
        self.filter_modules()

    def metadata_details_for_export(self, record, view):
        original_info = self.info_text
        temp = QTextEdit()
        self.info_text = temp
        try:
            self._render_record_details(record, view)
            return temp.toPlainText()
        finally:
            self.info_text = original_info

    def export_records(self, all_collected=False, include_metadata=False):
        views = list(self._cache) if all_collected else [self.view]
        records = []
        for view in views:
            flat = self._clean_export(self._cache[view], view)
            if include_metadata:
                for item, record in zip(flat, self._cache[view]):
                    item['metadata_details'] = self.metadata_details_for_export(record, view)
            records.extend(flat)
        return records

    def get_export_records(self):
        return self._clean_export(self._cache.get(self.view, []), self.view)

    @staticmethod
    def _clean_export(records, view):
        flattened = []
        for r in records:
            fields = {k: r.get(k) for k, *_ in COLUMNS[view]}
            fields.update({'view': view, 'acquired': r.get('acquired'),
                           'source_paths': '; '.join(r.get('sources', []))})
            flattened.append(fields)
        return flattened

    def export_current_data(self, all_collected=False):
        selected = list(self._cache) if all_collected else [self.view]
        records = []
        for view in selected:
            records.extend(self._clean_export(self._cache[view], view))
        if not records:
            QMessageBox.information(self, 'Export', 'No matching collected data to export.')
            return
        columns = [('view', 'View')] + [v for view in selected for v in COLUMNS[view]] + [
            ('acquired', 'Acquired'), ('source_paths', 'Source Paths')]
        # De-duplicate column definitions in exported mixed-view schema.
        seen = set()
        columns = [c for c in columns if not (c[0] in seen or seen.add(c[0]))]
        path = export_records_dialog(self, APPLET_NAME + (' — Collected Views' if all_collected else ' — ' + self.view),
                                     records, columns=columns,
                                     sections={'Acquisition': '\n'.join(f'{v}: {self._times.get(v, "Not collected")}' for v in selected)})
        if path:
            self.set_status(f'Exported previously collected data to {path}')


def create_applet(parent=None):
    return GPUInspectorTab(parent)


def run_standalone():
    existing = QApplication.instance()
    application = existing or QApplication(sys.argv)
    application.setApplicationName(APPLET_NAME)
    application.setOrganizationName('brunonlinespace')
    if existing is None:
        application.setStyleSheet(STANDALONE_STYLESHEET)
    window = QMainWindow()
    window.setWindowTitle(f'{APPLET_NAME} {APPLET_VERSION} — LinSpectacles Applet')
    window.resize(1200, 780)
    icon = Path(__file__).parent / 'icon.png'
    if icon.is_file():
        application.setWindowIcon(QIcon(str(icon)))
        window.setWindowIcon(QIcon(str(icon)))
    window.setCentralWidget(create_applet())
    window.show()
    if existing is None:
        return application.exec()
    return 0


if __name__ == '__main__':
    raise SystemExit(run_standalone())
