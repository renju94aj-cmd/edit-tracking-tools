# -*- coding: utf-8 -*-
"""
Edit Tracking Tools plugin — FINAL LIVE-STATS VERSION
(with NULL date fix + automatic edit watcher + Day Count by date picker)

Tools included (total 7):
 1. Create Edited Fields and Date
 2. Auto Edit (auto set edited=1 and date)
 3. Mark Selected as Edited
 4. Update Date for Selected Features (calendar)
 5. Remove NULL Geometry
 6. Select NULL Attributes (corrected logic)
 7. Refresh Stats (reopen dock, refresh)

Stats dock:
 - Edited (1)
 - Not Edited (0)
 - Day Count (for selected date)
 - NULL Geometry (RED)
 - Null Attributes (RED)
"""

import os
from qgis.PyQt.QtWidgets import (
    QAction, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDialog, QPushButton, QCalendarWidget, QDateEdit
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, QVariant, QDate
from qgis.core import QgsField, QgsVectorLayer

EDIT_FIELD = "edited"
DATE_FIELD = "edited_dat"     # shapefile-safe 10 chars


def is_null_date(date_val):
    """
    Return True if the date field is effectively NULL/invalid.
    Handles both Python None AND invalid QDate objects.
    """
    if date_val is None:
        return True
    if isinstance(date_val, QDate) and not date_val.isValid():
        return True
    return False


def to_qdate(date_val):
    """
    Convert different date types to QDate for comparison.
    Returns QDate or None.
    """
    if isinstance(date_val, QDate):
        return date_val if date_val.isValid() else None
    # Python date / datetime support (just in case)
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
        self.auto_connections = {}  # layer.id() -> {layer, geom_fn, add_fn}

        self.dock = None
        self.stats_label = None

        self.action_create_field = None
        self.action_stats = None

        self.day_date_edit = None  # date selector in stats panel

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

        # 1) Create edited fields + date
        self.action_create_field = QAction(
            icon_create,
            "Create Edited Fields and Date",
            self.iface.mainWindow()
        )
        self.action_create_field.triggered.connect(self.create_edited_fields)
        self.toolbar.addAction(self.action_create_field)

        # 2) Auto edit (manual enable, if needed)
        action_auto = QAction(icon_auto, "Auto Edit", self.iface.mainWindow())
        action_auto.triggered.connect(self.enable_auto_edited_flag)
        self.toolbar.addAction(action_auto)

        # 3) Mark selected as edited
        action_mark = QAction(icon_mark, "Mark Selected Edited", self.iface.mainWindow())
        action_mark.triggered.connect(self.mark_selected_as_edited)
        self.toolbar.addAction(action_mark)

        # 4) Update date for selected features
        action_update_date = QAction(icon_update, "Update Date (Selected)", self.iface.mainWindow())
        action_update_date.triggered.connect(self.update_date_for_selected)
        self.toolbar.addAction(action_update_date)

        # 5) Remove Null Geometry
        action_remove_null_geom = QAction(icon_remove_null, "Remove NULL Geometry", self.iface.mainWindow())
        action_remove_null_geom.triggered.connect(self.remove_null_geometry)
        self.toolbar.addAction(action_remove_null_geom)

        # 6) Select Null Attributes
        action_select_null = QAction(icon_null_attr, "Select NULL Attributes", self.iface.mainWindow())
        action_select_null.triggered.connect(self.select_null_attributes)
        self.toolbar.addAction(action_select_null)

        # 7) Refresh Stats
        self.action_stats = QAction(icon_refresh, "Refresh Stats", self.iface.mainWindow())
        self.action_stats.triggered.connect(self.update_stats_for_active_layer)
        self.toolbar.addAction(self.action_stats)

        self.actions.extend([
            self.action_create_field, action_auto, action_mark,
            action_update_date, action_remove_null_geom,
            action_select_null, self.action_stats
        ])

        # Add stats dock
        self.create_stats_dock()

        # Watch layer changes (for stats + edit watcher hook)
        self.iface.currentLayerChanged.connect(self.on_layer_changed)

        # NEW: attach watcher for current active layer on plugin load
        self.on_layer_changed(self.iface.activeLayer())

    # ---------------- UNLOAD ----------------
    def unload(self):

        # Disconnect auto signals
        for layer_id, info in self.auto_connections.items():
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

        # Disconnect layer change signal
        try:
            self.iface.currentLayerChanged.disconnect(self.on_layer_changed)
        except Exception:
            pass

        # Remove toolbar
        if self.toolbar:
            for act in self.actions:
                self.toolbar.removeAction(act)
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar = None

        # Remove dock
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock = None

    # ---------------- LAYER CHANGE + EDIT WATCHER ----------------
    def on_layer_changed(self, layer):
        """
        Called when the active layer changes.
        - Updates stats.
        - Connects editingStarted/editingStopped for the new layer (automatic edit watcher).
        """
        # Update stats for the new layer
        self.update_stats_for_active_layer()

        # Attach editingStarted / editingStopped watcher for vector layers
        if isinstance(layer, QgsVectorLayer):
            try:
                layer.editingStarted.disconnect(self.on_editing_started)
            except Exception:
                pass
            try:
                layer.editingStopped.disconnect(self.on_editing_stopped)
            except Exception:
                pass

            layer.editingStarted.connect(self.on_editing_started)
            layer.editingStopped.connect(self.on_editing_stopped)

    def on_editing_started(self):
        """
        Called automatically when the current active layer enters edit mode.
        We auto-attach geometryChanged/featureAdded tracking if fields exist.
        """
        layer = self.iface.activeLayer()
        if not isinstance(layer, QgsVectorLayer):
            return
        # Silent attach (no popup message)
        self._attach_auto_for_layer(layer, silent=True)

    def on_editing_stopped(self):
        """
        Called when editing is turned off.
        Refresh stats on final committed state.
        """
        self.update_stats_for_active_layer()

    def _attach_auto_for_layer(self, layer, silent=False):
        """
        Core logic: attach geometryChanged + featureAdded to a given layer.
        Used by:
          - Auto Edit button (silent=False, with message)
          - editingStarted watcher (silent=True)
          - create_edited_fields (silent=True)
        """
        fields = layer.fields()
        edited_idx = fields.indexFromName(EDIT_FIELD)
        date_idx = fields.indexFromName(DATE_FIELD)

        if edited_idx == -1 or date_idx == -1:
            if not silent:
                self.iface.messageBar().pushCritical(
                    "Edit Tracking",
                    f"Fields '{EDIT_FIELD}' and/or '{DATE_FIELD}' missing."
                )
            return

        if layer.id() in self.auto_connections:
            if not silent:
                self.iface.messageBar().pushInfo(
                    "Edit Tracking",
                    "Auto Edit already enabled for this layer."
                )
            return

        def mark_feature_edited(fid, geom):
            if not layer.isEditable():
                return
            f = layer.getFeature(fid)
            old_val = f[edited_idx]
            make = old_val in (None, 0)
            if make:
                layer.changeAttributeValue(fid, edited_idx, 1)
                layer.changeAttributeValue(fid, date_idx, QDate.currentDate())
            # LIVE STATS
            self.update_stats_for_active_layer()

        def mark_feature_added(fid):
            if not layer.isEditable():
                return
            layer.changeAttributeValue(fid, edited_idx, 1)
            layer.changeAttributeValue(fid, date_idx, QDate.currentDate())
            # LIVE STATS
            self.update_stats_for_active_layer()

        layer.geometryChanged.connect(mark_feature_edited)
        layer.featureAdded.connect(mark_feature_added)

        self.auto_connections[layer.id()] = {
            "layer": layer,
            "geom_fn": mark_feature_edited,
            "add_fn": mark_feature_added,
        }

        if not silent:
            self.iface.messageBar().pushSuccess("Edit Tracking", "Auto Edit enabled for this layer.")

    # ---------------- STATS DOCK ----------------
    def create_stats_dock(self):

        self.dock = QDockWidget("Edit Tracking Stats", self.iface.mainWindow())
        content = QWidget()
        layout = QVBoxLayout(content)

        # Main stats label
        self.stats_label = QLabel("No active layer.")
        self.stats_label.setWordWrap(True)

        layout.addWidget(self.stats_label)

        # Day selector row
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

    # ---------------- STATS UPDATE ----------------
    def update_stats_for_active_layer(self, *args):

        if self.dock and not self.dock.isVisible():
            self.dock.show()

        layer = self.iface.activeLayer()
        if not layer:
            if self.stats_label:
                self.stats_label.setText("No active layer.")
            return

        fields = layer.fields()
        edited_idx = fields.indexFromName(EDIT_FIELD)
        date_idx = fields.indexFromName(DATE_FIELD)

        if edited_idx == -1 or date_idx == -1:
            if self.stats_label:
                self.stats_label.setText(
                    f"<b>Layer:</b> {layer.name()}<br>"
                    f"<span style='color:red;'>Required fields missing.</span>"
                )
            if self.action_create_field:
                self.action_create_field.setEnabled(True)
            return

        if self.action_create_field:
            self.action_create_field.setEnabled(False)

        total = 0
        edited_1 = 0
        edited_0 = 0
        null_geom = 0
        null_attr = 0

        # Day count for selected date
        if self.day_date_edit is not None:
            selected_day = self.day_date_edit.date()
        else:
            selected_day = QDate.currentDate()
        day_count = 0

        for f in layer.getFeatures():
            total += 1
            geom = f.geometry()

            # NULL GEOMETRY
            if geom is None or geom.isEmpty() or geom.isNull():
                null_geom += 1
                continue

            val = f[edited_idx]
            date_val = f[date_idx]
            date_null = is_null_date(date_val)

            # edited NULL
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

            # edited = 1 must have date
            if v == 1:
                if date_null:
                    null_attr += 1
                else:
                    edited_1 += 1
                    qd = to_qdate(date_val)
                    if qd is not None and qd == selected_day:
                        day_count += 1

            # edited = 0 → always Not Edited (valid), ignore date
            elif v == 0:
                edited_0 += 1

        if self.stats_label:
            self.stats_label.setText(
                f"<b>Layer:</b> {layer.name()}<br>"
                f"<b>Total:</b> {total}<br>"
                f"<b>Edited (1):</b> {edited_1}<br>"
                f"<b>Not Edited (0):</b> {edited_0}<br>"
                f"<b>Day Count ({selected_day.toString('yyyy-MM-dd')}):</b> {day_count}<br>"
                f"<b style='color:red;'>Null Geometry:</b> "
                f"<b style='color:red;'>{null_geom}</b><br>"
                f"<b style='color:red;'>Null Attributes:</b> "
                f"<b style='color:red;'>{null_attr}</b>"
            )

    # ---------------- HELPERS ----------------
    def get_layer_and_fields(self):
        layer = self.iface.activeLayer()
        if not layer:
            raise Exception("No active layer.")
        fields = layer.fields()
        e = fields.indexFromName(EDIT_FIELD)
        d = fields.indexFromName(DATE_FIELD)
        if e == -1 or d == -1:
            raise Exception("Required fields missing.")
        return layer, e, d

    # ---------------- TOOL 1: CREATE FIELDS ----------------
    def create_edited_fields(self):

        layer = self.iface.activeLayer()
        if not layer:
            self.iface.messageBar().pushWarning("Edit Tracking", "No active layer.")
            return

        if not layer.isEditable():
            layer.startEditing()

        pr = layer.dataProvider()
        fields = layer.fields()

        edited_idx = fields.indexFromName(EDIT_FIELD)
        date_idx = fields.indexFromName(DATE_FIELD)

        new_fields = []
        if edited_idx == -1:
            new_fields.append(QgsField(EDIT_FIELD, QVariant.Int))
        if date_idx == -1:
            new_fields.append(QgsField(DATE_FIELD, QVariant.Date))

        if new_fields:
            pr.addAttributes(new_fields)
            layer.updateFields()

        # Initialize NEW fields
        fields = layer.fields()
        edited_idx = fields.indexFromName(EDIT_FIELD)
        date_idx = fields.indexFromName(DATE_FIELD)

        for f in layer.getFeatures():
            if edited_idx != -1:
                layer.changeAttributeValue(f.id(), edited_idx, 0)
            if date_idx != -1:
                layer.changeAttributeValue(f.id(), date_idx, None)

        # NEW: attach watcher now that fields exist
        self._attach_auto_for_layer(layer, silent=True)

        self.iface.messageBar().pushSuccess(
            "Edit Tracking",
            "Edited Fields and Date created."
        )

        self.update_stats_for_active_layer()

    # ---------------- TOOL 2: AUTO EDIT (manual) ----------------
    def enable_auto_edited_flag(self):

        try:
            layer, _, _ = self.get_layer_and_fields()
        except Exception:
            self.iface.messageBar().pushCritical("Edit Tracking", "Required fields missing.")
            return

        self._attach_auto_for_layer(layer, silent=False)

    # ---------------- TOOL 3: MARK SELECTED ----------------
    def mark_selected_as_edited(self):

        try:
            layer, edited_idx, date_idx = self.get_layer_and_fields()
        except Exception:
            self.iface.messageBar().pushCritical("Edit Tracking", "Fields missing.")
            return

        ids = layer.selectedFeatureIds()
        if not ids:
            self.iface.messageBar().pushWarning("Edit Tracking", "No selection.")
            return

        if not layer.isEditable():
            layer.startEditing()

        today = QDate.currentDate()
        count = 0

        for f in layer.selectedFeatures():
            old = f[edited_idx]
            if old in (None, 0):
                layer.changeAttributeValue(f.id(), edited_idx, 1)
                layer.changeAttributeValue(f.id(), date_idx, today)
                count += 1

        self.iface.messageBar().pushSuccess("Edit Tracking", f"Updated {count} selected.")
        self.update_stats_for_active_layer()

    # ---------------- TOOL 4: UPDATE DATE (CALENDAR) ----------------
    def update_date_for_selected(self):

        try:
            layer, edited_idx, date_idx = self.get_layer_and_fields()
        except Exception:
            self.iface.messageBar().pushCritical("Edit Tracking", "Fields missing.")
            return

        ids = layer.selectedFeatureIds()
        if not ids:
            self.iface.messageBar().pushWarning("Edit Tracking", "No features selected.")
            return

        # Calendar selection dialog
        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle("Select Date")
        vbox = QVBoxLayout(dlg)

        cal = QCalendarWidget()
        cal.setSelectedDate(QDate.currentDate())

        btn = QPushButton("Apply Date")
        btn.clicked.connect(lambda: dlg.accept())

        vbox.addWidget(cal)
        vbox.addWidget(btn)

        if dlg.exec_() != QDialog.Accepted:
            return

        sel_date = cal.selectedDate()

        if not layer.isEditable():
            layer.startEditing()

        updated = 0

        for f in layer.selectedFeatures():
            geom = f.geometry()
            if geom is None or geom.isEmpty() or geom.isNull():
                continue

            layer.changeAttributeValue(f.id(), edited_idx, 1)
            layer.changeAttributeValue(f.id(), date_idx, sel_date)
            updated += 1

        self.iface.messageBar().pushSuccess("Edit Tracking", f"Updated {updated} features.")
        self.update_stats_for_active_layer()

    # ---------------- TOOL 5: REMOVE NULL GEOMETRY ----------------
    def remove_null_geometry(self):

        layer = self.iface.activeLayer()
        if not layer:
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

        self.iface.messageBar().pushSuccess(
            "Edit Tracking", f"Removed {len(ids)} NULL geometry features."
        )
        self.update_stats_for_active_layer()

    # ---------------- TOOL 6: SELECT NULL ATTRIBUTES ----------------
    def select_null_attributes(self):

        try:
            layer, edited_idx, date_idx = self.get_layer_and_fields()
        except Exception:
            self.iface.messageBar().pushCritical("Edit Tracking", "Fields missing.")
            return

        layer.removeSelection()
        null_ids = []

        for f in layer.getFeatures():
            geom = f.geometry()
            if geom is None or geom.isEmpty() or geom.isNull():
                continue

            val = f[edited_idx]
            date_val = f[date_idx]
            date_null = is_null_date(date_val)

            # NULL edited
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

            # edited=1 but no valid date → invalid attribute
            if v == 1 and date_null:
                null_ids.append(f.id())
                continue

            # edited=0 → always treated as valid here (even if date exists)

        if null_ids:
            layer.selectByIds(null_ids)
            self.iface.messageBar().pushSuccess(
                "Edit Tracking", f"Selected {len(null_ids)} NULL attribute features."
            )
        else:
            self.iface.messageBar().pushInfo("Edit Tracking", "No NULL attributes found.")

    # ---------------- TOOL 7: REFRESH ----------------
    def refresh_stats(self):
        self.update_stats_for_active_layer()
