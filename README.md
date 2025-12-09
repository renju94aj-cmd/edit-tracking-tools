# Edit Tracking Tools — QGIS Plugin

A powerful edit-tracking and QC assistant for QGIS digitizing workflows.  
Designed for GIS teams, production units, survey editors, and daily update workflows.

---

## Key Features

### Automatic Edit Tracking
- Detects geometry edits and new features.
- Automatically sets:
  - `edited = 1`
  - `edited_dat = <today>`
- Runs silently when editing starts.
- Ensures missing edits are not ignored.
  
To visually classify edited and not edited features in QGIS:

- Layer → Properties

- Symbology → choose Categorized

- Column = edited

Click Classify

- Assign different colors for 0 and 1

- This helps in quick QC verification.

###  Attribute Field Creator
Creates the two required fields:
- `edited` (0 = not edited, 1 = edited)
- `edited_dat` (date of editing)

All existing features are initialized as:
edited = 0
edited_dat = NULL

### QC + Editing Tools
| Tool | Description |
|------|-------------|
| **Create Edited Fields and Date** | Adds required fields & initializes data |
| **Auto Edit** | Manually enable edit watcher |
| **Mark Selected Edited** | Set selected features to edited = 1 |
| **Update Date (Calendar)** | Choose a custom edit date |
| **Select NULL Attributes** | Find missing or invalid edit fields |
| **Remove NULL Geometry** | Delete empty geometries |
| **Refresh Stats** | Manually refresh dock stats |

---

## Live Statistics Dock

This plugin includes a live-updating dock panel showing:

- **Total Features**
- **Edited Features (1)**
- **Not Edited (0)**
- **Null Geometry** (red)
- **Null Attributes** (red)
- **Day Count** — features edited on selected date

Includes date picker for daily QC monitoring.

---

## Folder Structure

     edit_tracking_tools/
     ├── __init__.py
     ├── edit_tracking_tools.py
     ├── metadata.txt
     ├── LICENSE.txt
     ├── icon.png
     └── icons/
          ├── auto_edit_24.png
          ├── create_edited_24.png
          ├── mark_selected_24.png
          ├── null_attr_24.png
          ├── refresh_stats_24.png
          ├── remove_null_geom_24.png
          ├── update_date_24.png


---

## Installation

1. Download the ZIP file of this plugin.
2. Open **QGIS → Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the downloaded file.
4. Enable **Edit Tracking Tools** from the plugin list.

---

## Author

**Renju A J**  
GitHub: https://github.com/renju94aj-cmd  
Email: renju94aj@gmail.com  

---

## License
This plugin is released under the **MIT License**.


