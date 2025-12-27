# -*- coding: utf-8 -*-
"""
Edit Tracking Tools — FINAL (Lag-safe + Raster-safe + Manual-Edit Popup + Stale-ID cleanup)

Key behavior:
- Tracking turns ON only when user clicks Auto Edit button.
- When tracking ON: stats scan runs (throttled). When tracking OFF: no heavy scan (no lag).
- Raster-safe: never calls .fields() on non-vector layers.
- If user manually toggles QGIS editing ON for a previously tracked layer (saved by layer.source()),
  a popup asks once per edit session: "Enable tracking now?"
- Stale layer-id cleanup: when layer removed from project, plugin removes old IDs from internal sets
  (tracked_layer_ids, auto_connections, _prompted_this_edit_session) to avoid wrong state.

Tools:
1) Create Edited Fields and Date
2) Auto Edit (Enable/Disable tracking for ACTIVE layer)  [single toggle button]
3) Mark Selected Edited
4) Update Date (Selected)  [calendar]
5) Remove NULL Geometry
6) Select NULL Attributes
7) Refresh Stats
"""

import os

from qgis.PyQt.QtWidgets import (
    QAction, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDialog, QPushButton, QCalendarWidget, QDateEdit, QMessageBox
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, QVariant, QDate, QTimer

from qgis.core import (
    QgsField, QgsVectorLayer, QgsSettings, QgsProject
)

EDIT_FIELD = "edited"
DATE_FIELD = "edited_dat"   # shapefile-safe 10 chars

SETTINGS_GROUP = "EditTrackingTools"
SETTINGS_KEY_TRACKED_SOURCES = f"{SETTINGS_GROUP}/tracked_sources"


def is_null_date(date_val):
    if date_val is None:
        return True
    if isinstance(date_val, QDate) and not date_val.isValid():
        return True
    return False


def to_qdate(date_val):
    if isinstance(date_val, QDate):
        return date_val if date_val.isValid() else None
    if hasattr(date_val, "year") and hasattr(date_val, "month") and hasattr(date_val, "day"):
        try:
            return QDate(date_val.year, date_val.month, date_val.day)
        except Exception:
            return None
    return None


class EditTrackingToolsPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)

        self.toolbar = None
        self.actions = []

        # Tracking state per layer id (session)
        self.tracked_layer_ids = set()

        # layer.id() -> {layer, geom_fn, add_fn}
        self.auto_connections = {}

        # Popup asked once per edit session (layer.id())
        self._prompted_this_edit_session = set()

        # Settings storage of previously tracked layers (by layer.source())
        self.settings = QgsSettings()

        # UI
        self.dock = None
        self.stats_label = None
        self.day_date_edit = None

        # actions
        self.action_create_field = None
        self.action_auto_toggle = None
        self.action_mark = None
        self.action_update_date = None
        self.action_remove_null_geom = None
        self.action_select_null = None
        self.action_stats = None

        # Throttle stats refresh (prevents freezes while editing)
        self._stats_timer = QTimer()
        self._stats_timer.setSingleShot(True)
        self._stats_timer.timeout.connect(self._update_stats_now)

        # Track which layer has edit signals connected (avoid duplicates)
        self._edit_signal_connected_layer_id = None

    # ---------------- GUI INIT ----------------
    def initGui(self):
        self.toolbar = self.iface.addToolBar("Edit Tracking")
        self.toolbar.setObjectName("EditTrackingToolbar")

        # ICONS
        icon_create = QIcon(os.path.join(self.plugin_dir, "icons", "create_edited_24.png"))
        icon_auto = QIcon(os.path.join(self.plugin_dir, "icons", "auto_edit_24.png"))
        icon_mark = QIcon(os.path.join(self.plugin_dir, "icons", "mark_selected_24.png"))
        icon_update = QIcon(os.path.join(self.plugin_dir, "icons", "update_date_24.png"))
        icon_remove_null = QIcon(os.path.join(self.plugin_dir, "icons", "remove_null_geom_24.png"))
        icon_null_attr = QIcon(os.path.join(self.plugin_dir, "icons", "null_attr_24.png"))
        icon_refresh = QIcon(os.path.join(self.plugin_dir, "icons", "refresh_stats_24.png"))

        # 1) Create fields
        self.action_create_field = QAction(icon_create, "Create Edited Fields and Date", self.iface.mainWindow())
        self.action_create_field.triggered.connect(self.create_edited_fields)
        self.toolbar.addAction(self.action_create_field)

        # 2) Auto Edit toggle (single button)
        self.action_auto_toggle = QAction(icon_auto, "Auto Edit (Enable Tracking)", self.iface.mainWindow())
        self.action_auto_toggle.setCheckable(True)
        self.action_auto_toggle.toggled.connect(self.toggle_tracking_for_active_layer)
        self.toolbar.addAction(self.action_auto_toggle)

        # 3) Mark selected
        self.action_mark = QAction(icon_mark, "Mark Selected Edited", self.iface.mainWindow())
        self.action_mark.triggered.connect(self.mark_selected_as_edited)
        self.toolbar.addAction(self.action_mark)

        # 4) Update date
        self.action_update_date = QAction(icon_update, "Update Date (Selected)", self.iface.mainWindow())
        self.action_update_date.triggered.connect(self.update_date_for_selected)
        self.toolbar.addAction(self.action_update_date)

        # 5) Remove null geom
        self.action_remove_null_geom = QAction(icon_remove_null, "Remove NULL Geometry", self.iface.mainWindow())
        self.action_remove_null_geom.triggered.connect(self.remove_null_geometry)
        self.toolbar.addAction(self.action_remove_null_geom)

        # 6) Select null attributes
        self.action_select_null = QAction(icon_null_attr, "Select NULL Attributes", self.iface.mainWindow())
        self.action_select_null.triggered.connect(self.select_null_attributes)
        self.toolbar.addAction(self.action_select_null)

        # 7) Refresh stats
        self.action_stats = QAction(icon_refresh, "Refresh Stats", self.iface.mainWindow())
        self.action_stats.triggered.connect(self.update_stats_for_active_layer)
        self.toolbar.addAction(self.action_stats)

        self.actions.extend([
            self.action_create_field, self.action_auto_toggle, self.action_mark,
            self.action_update_date, self.action_remove_null_geom, self.action_select_null,
            self.action_stats
        ])

        # Dock stats
        self.create_stats_dock()

        # Layer change
        self.iface.currentLayerChanged.connect(self.on_layer_changed)

        # Connect edit signals for active layer (for popup)
        self.iface.currentLayerChanged.connect(self._connect_edit_signals_for_layer)
        self._connect_edit_signals_for_layer(self.iface.activeLayer())

        # --- Stale layer-id cleanup when layer removed ---
        prj = QgsProject.instance()
        # Depending on QGIS version, these signals exist:
        if hasattr(prj, "layersWillBeRemoved"):
            prj.layersWillBeRemoved.connect(self._on_layers_will_be_removed)
        if hasattr(prj, "layerWillBeRemoved"):
            prj.layerWillBeRemoved.connect(self._on_layer_will_be_removed)

        self.on_layer_changed(self.iface.activeLayer())

    # ---------------- UNLOAD ----------------
    def unload(self):
        # disconnect watchers
        for layer_id, info in list(self.auto_connections.items()):
            layer = info.get("layer")
            try:
                layer.geometryChanged.disconnect(info["geom_fn"])
            except Exception:
                pass
            try:
                layer.featureAdded.disconnect(info["add_fn"])
            except Exception:
                pass

        self.auto_connections.clear()
        self.tracked_layer_ids.clear()
        self._prompted_this_edit_session.clear()

        try:
            self.iface.currentLayerChanged.disconnect(self.on_layer_changed)
        except Exception:
            pass
        try:
            self.iface.currentLayerChanged.disconnect(self._connect_edit_signals_for_layer)
        except Exception:
            pass

        prj = QgsProject.instance()
        try:
            if hasattr(prj, "layersWillBeRemoved"):
                prj.layersWillBeRemoved.disconnect(self._on_layers_will_be_removed)
        except Exception:
            pass
        try:
            if hasattr(prj, "layerWillBeRemoved"):
                prj.layerWillBeRemoved.disconnect(self._on_layer_will_be_removed)
        except Exception:
            pass

        if self.toolbar:
            for act in self.actions:
                self.toolbar.removeAction(act)
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar = None

        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock = None

    # ---------------- SETTINGS ----------------
    def _get_tracked_sources(self):
        val = self.settings.value(SETTINGS_KEY_TRACKED_SOURCES, [], type=list)
        return set(val or [])

    def _save_tracked_source(self, layer: QgsVectorLayer):
        sources = self._get_tracked_sources()
        sources.add(layer.source())
        self.settings.setValue(SETTINGS_KEY_TRACKED_SOURCES, sorted(list(sources)))

    def _is_previously_tracked(self, layer: QgsVectorLayer) -> bool:
        return layer.source() in self._get_tracked_sources()

    # ---------------- STALE ID CLEANUP ----------------
    def _cleanup_layer_id(self, layer_id: str):
        """Remove stale layer IDs from internal state when layers are removed."""
        self.tracked_layer_ids.discard(layer_id)
        self._prompted_this_edit_session.discard(layer_id)

        info = self.auto_connections.pop(layer_id, None)
        if info:
            layer = info.get("layer")
            try:
                layer.geometryChanged.disconnect(info["geom_fn"])
            except Exception:
                pass
            try:
                layer.featureAdded.disconnect(info["add_fn"])
            except Exception:
                pass

        if self._edit_signal_connected_layer_id == layer_id:
            self._edit_signal_connected_layer_id = None

    def _on_layers_will_be_removed(self, layer_ids):
        for lid in list(layer_ids):
            self._cleanup_layer_id(lid)

    def _on_layer_will_be_removed(self, layer_id):
        self._cleanup_layer_id(layer_id)

    # ---------------- HELPERS ----------------
    def _active_vector_layer(self):
        layer = self.iface.activeLayer()
        return layer if isinstance(layer, QgsVectorLayer) else None

    def _layer_has_required_fields(self, layer: QgsVectorLayer) -> bool:
        fields = layer.fields()
        return fields.indexFromName(EDIT_FIELD) != -1 and fields.indexFromName(DATE_FIELD) != -1

    def _set_tracking_tools_enabled(self, enabled: bool):
        for act in (self.action_mark, self.action_update_date, self.action_remove_null_geom, self.action_select_null):
            if act:
                act.setEnabled(enabled)

    def _detach_auto_for_layer(self, layer: QgsVectorLayer):
        info = self.auto_connections.pop(layer.id(), None)
        if not info:
            return
        try:
            layer.geometryChanged.disconnect(info["geom_fn"])
        except Exception:
            pass
        try:
            layer.featureAdded.disconnect(info["add_fn"])
        except Exception:
            pass

    # ---------------- Connect edit signals (popup) ----------------
    def _connect_edit_signals_for_layer(self, layer):
        if not isinstance(layer, QgsVectorLayer):
            self._edit_signal_connected_layer_id = None
            return

        # Avoid reconnecting to same layer repeatedly
        if self._edit_signal_connected_layer_id == layer.id():
            return

        # Disconnect from previous (best-effort)
        prev = None
        if self._edit_signal_connected_layer_id:
            prev = QgsProject.instance().mapLayer(self._edit_signal_connected_layer_id)
        if isinstance(prev, QgsVectorLayer):
            try:
                prev.editingStarted.disconnect(self._on_layer_editing_started)
            except Exception:
                pass
            try:
                prev.editingStopped.disconnect(self._on_layer_editing_stopped)
            except Exception:
                pass

        try:
            layer.editingStarted.connect(self._on_layer_editing_started)
        except Exception:
            pass
        try:
            layer.editingStopped.connect(self._on_layer_editing_stopped)
        except Exception:
            pass

        self._edit_signal_connected_layer_id = layer.id()

    def _on_layer_editing_started(self):
        layer = self._active_vector_layer()
        if not layer:
            return

        # If tracking already ON, do nothing
        if layer.id() in self.tracked_layer_ids:
            return

        # Do not prompt repeatedly in same edit session
        if layer.id() in self._prompted_this_edit_session:
            return

        # Only prompt for previously tracked layers (by source) AND fields exist
        if not self._layer_has_required_fields(layer):
            return
        if not self._is_previously_tracked(layer):
            return

        self._prompted_this_edit_session.add(layer.id())

        reply = QMessageBox.question(
            self.iface.mainWindow(),
            "Enable Edit Tracking?",
            f"You started editing:\n\n{layer.name()}\n\nEnable Edit Tracking Tool for this layer?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply == QMessageBox.Yes:
            # Enable tracking now (do not call startEditing; already started)
            self.tracked_layer_ids.add(layer.id())

            # Sync toggle UI without recursion
            self.action_auto_toggle.blockSignals(True)
            self.action_auto_toggle.setChecked(True)
            self.action_auto_toggle.blockSignals(False)
            self.action_auto_toggle.setText("Auto Edit (Disable Tracking)")

            self._attach_auto_for_layer(layer)
            self.iface.messageBar().pushSuccess("Edit Tracking", "Tracking enabled for current edit session.")
            self.on_layer_changed(layer)
            self.update_stats_for_active_layer()

    def _on_layer_editing_stopped(self):
        layer = self._active_vector_layer()
        if not layer:
            return
        # allow popup again next time editing starts
        self._prompted_this_edit_session.discard(layer.id())
        self.update_stats_for_active_layer()

    # ---------------- LAYER CHANGE ----------------
    def on_layer_changed(self, layer):
        self.update_stats_for_active_layer()

        vlayer = layer if isinstance(layer, QgsVectorLayer) else None
        if not vlayer:
            self._set_tracking_tools_enabled(False)
            self.action_create_field.setEnabled(False)

            self.action_auto_toggle.blockSignals(True)
            self.action_auto_toggle.setChecked(False)
            self.action_auto_toggle.blockSignals(False)
            self.action_auto_toggle.setText("Auto Edit (Enable Tracking)")
            return

        is_tracked = vlayer.id() in self.tracked_layer_ids
        has_fields = self._layer_has_required_fields(vlayer)

        self.action_auto_toggle.blockSignals(True)
        self.action_auto_toggle.setChecked(is_tracked)
        self.action_auto_toggle.blockSignals(False)
        self.action_auto_toggle.setText("Auto Edit (Disable Tracking)" if is_tracked else "Auto Edit (Enable Tracking)")

        # Create-fields only when tracking ON and fields missing
        self.action_create_field.setEnabled(is_tracked and not has_fields)

        # Other tools only when tracking ON and fields exist
        self._set_tracking_tools_enabled(is_tracked and has_fields)

    # ---------------- TRACKING TOGGLE ----------------
    def toggle_tracking_for_active_layer(self, checked: bool):
        layer = self._active_vector_layer()
        if not layer:
            self.iface.messageBar().pushWarning("Edit Tracking", "Select a vector layer first.")
            self.action_auto_toggle.blockSignals(True)
            self.action_auto_toggle.setChecked(False)
            self.action_auto_toggle.blockSignals(False)
            return

        if checked:
            # Enable tracking only by this button
            self.tracked_layer_ids.add(layer.id())
            self.action_auto_toggle.setText("Auto Edit (Disable Tracking)")

            # Save source to allow popup in future sessions
            self._save_tracked_source(layer)

            # Turn ON QGIS editing for this layer
            if not layer.isEditable():
                layer.startEditing()

            if self._layer_has_required_fields(layer):
                self._attach_auto_for_layer(layer)
                self.iface.messageBar().pushSuccess("Edit Tracking", f"Tracking enabled: {layer.name()}")
            else:
                self.iface.messageBar().pushInfo(
                    "Edit Tracking",
                    "Tracking enabled. Now click 'Create Edited Fields and Date'."
                )

        else:
            # Disable tracking
            self.tracked_layer_ids.discard(layer.id())
            self._detach_auto_for_layer(layer)
            self.action_auto_toggle.setText("Auto Edit (Enable Tracking)")

            # Turn OFF QGIS editing for this layer (commit)
            if layer.isEditable():
                ok = layer.commitChanges()
                if not ok:
                    self.iface.messageBar().pushWarning("Edit Tracking", "Could not commit changes. Save manually.")
            self.iface.messageBar().pushInfo("Edit Tracking", f"Tracking disabled: {layer.name()}")

        self.on_layer_changed(layer)
        self.update_stats_for_active_layer()

    # ---------------- WATCHER ATTACH ----------------
    def _attach_auto_for_layer(self, layer: QgsVectorLayer):
        if layer.id() in self.auto_connections:
            return

        fields = layer.fields()
        edited_idx = fields.indexFromName(EDIT_FIELD)
        date_idx = fields.indexFromName(DATE_FIELD)
        if edited_idx == -1 or date_idx == -1:
            return

        def mark_feature_edited(fid, geom):
            if not layer.isEditable():
                return
            f = layer.getFeature(fid)
            if f[edited_idx] in (None, 0):
                layer.changeAttributeValue(fid, edited_idx, 1)
                layer.changeAttributeValue(fid, date_idx, QDate.currentDate())
            self.update_stats_for_active_layer()

        def mark_feature_added(fid):
            if not layer.isEditable():
                return
            layer.changeAttributeValue(fid, edited_idx, 1)
            layer.changeAttributeValue(fid, date_idx, QDate.currentDate())
            self.update_stats_for_active_layer()

        layer.geometryChanged.connect(mark_feature_edited)
        layer.featureAdded.connect(mark_feature_added)

        self.auto_connections[layer.id()] = {
            "layer": layer,
            "geom_fn": mark_feature_edited,
            "add_fn": mark_feature_added
        }

    # ---------------- STATS DOCK ----------------
    def create_stats_dock(self):
        self.dock = QDockWidget("Edit Tracking Stats", self.iface.mainWindow())
        content = QWidget()
        layout = QVBoxLayout(content)

        self.stats_label = QLabel("No active layer.")
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)

        row = QHBoxLayout()
        lbl = QLabel("Day Count Date:")
        self.day_date_edit = QDateEdit()
        self.day_date_edit.setCalendarPopup(True)
        self.day_date_edit.setDate(QDate.currentDate())
        self.day_date_edit.dateChanged.connect(self.update_stats_for_active_layer)
        row.addWidget(lbl)
        row.addWidget(self.day_date_edit)
        row.addStretch()
        layout.addLayout(row)

        self.dock.setWidget(content)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)

        self.update_stats_for_active_layer()

    # ---- Throttled stats update ----
    def update_stats_for_active_layer(self, *args):
        if not self._stats_timer.isActive():
            self._stats_timer.start(250)

    def _update_stats_now(self):
        layer = self.iface.activeLayer()

        if not layer:
            self.stats_label.setText("No active layer.")
            return

        if not isinstance(layer, QgsVectorLayer):
            self.stats_label.setText(
                f"<b>Layer:</b> {layer.name()}<br>"
                f"<span style='color:#666;'>Raster/non-vector layer — tracking not applicable.</span>"
            )
            return

        tracked = layer.id() in self.tracked_layer_ids
        if not tracked:
            self.stats_label.setText(
                f"<b>Layer:</b> {layer.name()}<br>"
                f"<b>Tracking:</b> OFF<br>"
                f"<span style='color:#666;'>Click Auto Edit to enable tracking and view stats.</span>"
            )
            return

        fields = layer.fields()
        edited_idx = fields.indexFromName(EDIT_FIELD)
        date_idx = fields.indexFromName(DATE_FIELD)

        if edited_idx == -1 or date_idx == -1:
            self.stats_label.setText(
                f"<b>Layer:</b> {layer.name()}<br>"
                f"<b>Tracking:</b> ON<br>"
                f"<span style='color:red;'>Required fields missing.</span><br>"
                f"<span style='color:#666;'>Click 'Create Edited Fields and Date'.</span>"
            )
            return

        selected_day = self.day_date_edit.date() if self.day_date_edit else QDate.currentDate()

        total = edited_1 = edited_0 = null_geom = null_attr = day_count = 0

        for f in layer.getFeatures():
            total += 1
            g = f.geometry()
            if g is None or g.isEmpty() or g.isNull():
                null_geom += 1
                continue

            val = f[edited_idx]
            date_val = f[date_idx]
            date_null = is_null_date(date_val)

            if val is None:
                null_attr += 1
                continue

            try:
                v = int(val)
            except Exception:
                null_attr += 1
                continue

            if v not in (0, 1):
                null_attr += 1
                continue

            if v == 1:
                if date_null:
                    null_attr += 1
                else:
                    edited_1 += 1
                    qd = to_qdate(date_val)
                    if qd is not None and qd == selected_day:
                        day_count += 1
            else:
                edited_0 += 1

        self.stats_label.setText(
            f"<b>Layer:</b> {layer.name()}<br>"
            f"<b>Tracking:</b> ON<br>"
            f"<b>Total:</b> {total}<br>"
            f"<b>Edited (1):</b> {edited_1}<br>"
            f"<b>Not Edited (0):</b> {edited_0}<br>"
            f"<b>Day Count ({selected_day.toString('yyyy-MM-dd')}):</b> {day_count}<br>"
            f"<b style='color:red;'>Null Geometry:</b> <b style='color:red;'>{null_geom}</b><br>"
            f"<b style='color:red;'>Null Attributes:</b> <b style='color:red;'>{null_attr}</b>"
        )

    # ---------------- TOOL 1: CREATE FIELDS ----------------
    def create_edited_fields(self):
        layer = self._active_vector_layer()
        if not layer:
            self.iface.messageBar().pushWarning("Edit Tracking", "Select a vector layer.")
            return

        if layer.id() not in self.tracked_layer_ids:
            self.iface.messageBar().pushWarning("Edit Tracking", "Enable Auto Edit (Tracking) first.")
            return

        if not layer.isEditable():
            layer.startEditing()

        pr = layer.dataProvider()
        fields = layer.fields()

        new_fields = []
        if fields.indexFromName(EDIT_FIELD) == -1:
            new_fields.append(QgsField(EDIT_FIELD, QVariant.Int, "integer"))
        if fields.indexFromName(DATE_FIELD) == -1:
            new_fields.append(QgsField(DATE_FIELD, QVariant.Date, "date"))

        if new_fields:
            pr.addAttributes(new_fields)
            layer.updateFields()

        # refresh indexes
        fields = layer.fields()
        edited_idx = fields.indexFromName(EDIT_FIELD)
        date_idx = fields.indexFromName(DATE_FIELD)

        # initialize all features (important)
        for f in layer.getFeatures():
            layer.changeAttributeValue(f.id(), edited_idx, 0)
            layer.changeAttributeValue(f.id(), date_idx, None)

        # attach watcher now that fields exist
        self._attach_auto_for_layer(layer)

        self.iface.messageBar().pushSuccess(
            "Edit Tracking",
            "Fields created and initialized (edited=0, edited_dat=NULL)."
        )
        self.on_layer_changed(layer)
        self.update_stats_for_active_layer()

    # ---------------- TOOL 3: MARK SELECTED ----------------
    def mark_selected_as_edited(self):
        layer = self._active_vector_layer()
        if not layer or layer.id() not in self.tracked_layer_ids or not self._layer_has_required_fields(layer):
            self.iface.messageBar().pushWarning("Edit Tracking", "Tracking ON + fields required.")
            return
        if not layer.selectedFeatureIds():
            self.iface.messageBar().pushWarning("Edit Tracking", "No selection.")
            return
        if not layer.isEditable():
            layer.startEditing()

        fields = layer.fields()
        edited_idx = fields.indexFromName(EDIT_FIELD)
        date_idx = fields.indexFromName(DATE_FIELD)

        today = QDate.currentDate()
        n = 0
        for f in layer.selectedFeatures():
            if f[edited_idx] in (None, 0):
                layer.changeAttributeValue(f.id(), edited_idx, 1)
                layer.changeAttributeValue(f.id(), date_idx, today)
                n += 1
        self.iface.messageBar().pushSuccess("Edit Tracking", f"Updated {n} selected.")
        self.update_stats_for_active_layer()

    # ---------------- TOOL 4: UPDATE DATE (CALENDAR) ----------------
    def update_date_for_selected(self):
        layer = self._active_vector_layer()
        if not layer or layer.id() not in self.tracked_layer_ids or not self._layer_has_required_fields(layer):
            self.iface.messageBar().pushWarning("Edit Tracking", "Tracking ON + fields required.")
            return
        if not layer.selectedFeatureIds():
            self.iface.messageBar().pushWarning("Edit Tracking", "No selection.")
            return

        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle("Select Date")
        vbox = QVBoxLayout(dlg)

        cal = QCalendarWidget()
        cal.setSelectedDate(QDate.currentDate())
        vbox.addWidget(cal)

        btn_apply = QPushButton("Apply Date")
        btn_cancel = QPushButton("Cancel")
        row = QHBoxLayout()
        row.addWidget(btn_apply)
        row.addWidget(btn_cancel)
        vbox.addLayout(row)

        btn_apply.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return

        sel_date = cal.selectedDate()

        if not layer.isEditable():
            layer.startEditing()

        fields = layer.fields()
        edited_idx = fields.indexFromName(EDIT_FIELD)
        date_idx = fields.indexFromName(DATE_FIELD)

        n = 0
        for f in layer.selectedFeatures():
            g = f.geometry()
            if g is None or g.isEmpty() or g.isNull():
                continue
            layer.changeAttributeValue(f.id(), edited_idx, 1)
            layer.changeAttributeValue(f.id(), date_idx, sel_date)
            n += 1

        self.iface.messageBar().pushSuccess("Edit Tracking", f"Updated {n} features.")
        self.update_stats_for_active_layer()

    # ---------------- TOOL 5: REMOVE NULL GEOMETRY ----------------
    def remove_null_geometry(self):
        layer = self._active_vector_layer()
        if not layer or layer.id() not in self.tracked_layer_ids:
            self.iface.messageBar().pushWarning("Edit Tracking", "Enable tracking first.")
            return
        if not layer.isEditable():
            layer.startEditing()

        ids = []
        for f in layer.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty() or g.isNull():
                ids.append(f.id())
        for fid in ids:
            layer.deleteFeature(fid)

        self.iface.messageBar().pushSuccess("Edit Tracking", f"Removed {len(ids)} NULL geometry features.")
        self.update_stats_for_active_layer()

    # ---------------- TOOL 6: SELECT NULL ATTRIBUTES ----------------
    def select_null_attributes(self):
        layer = self._active_vector_layer()
        if not layer or layer.id() not in self.tracked_layer_ids or not self._layer_has_required_fields(layer):
            self.iface.messageBar().pushWarning("Edit Tracking", "Tracking ON + fields required.")
            return

        fields = layer.fields()
        edited_idx = fields.indexFromName(EDIT_FIELD)
        date_idx = fields.indexFromName(DATE_FIELD)

        layer.removeSelection()
        null_ids = []

        for f in layer.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty() or g.isNull():
                continue

            val = f[edited_idx]
            date_val = f[date_idx]
            date_null = is_null_date(date_val)

            if val is None:
                null_ids.append(f.id())
                continue
            try:
                v = int(val)
            except Exception:
                null_ids.append(f.id())
                continue
            if v not in (0, 1):
                null_ids.append(f.id())
                continue
            if v == 1 and date_null:
                null_ids.append(f.id())

        if null_ids:
            layer.selectByIds(null_ids)
            self.iface.messageBar().pushSuccess("Edit Tracking", f"Selected {len(null_ids)} NULL attribute features.")
        else:
            self.iface.messageBar().pushInfo("Edit Tracking", "No NULL attributes found.")

    # ---------------- TOOL 7: REFRESH ----------------
    def refresh_stats(self):
        self.update_stats_for_active_layer()
