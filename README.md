 # Edit Tracking Tools — QGIS Plugin Version 1.0.1

A lightweight, lag-safe edit-tracking and QC assistant for QGIS digitizing workflows.
Designed for GIS teams, production units, survey editors, and daily update workflows where only selected layers require edit tracking, while others remain normal QGIS editing layers.

What Makes This Plugin Different?

🔹 Edit tracking is NOT automatic — user explicitly enables it per layer

🔹 Avoids QGIS lag when switching between multiple editable layers

🔹 Smart popup reminder if user forgets to enable tracking

🔹 Safe for raster layers (no crashes)

🔹 Designed for real-world production and QC workflows

Key Features

**Manual Auto Edit (Tracking Toggle)**

- Tracking is enabled only when user clicks Auto Edit

- Automatically turns ON QGIS default Toggle Editing

- Automatically turns OFF QGIS Toggle Editing when tracking is disabled

- Other layers remain in normal QGIS editing mode

- Prevents lag caused by checking fields on every layer

Smart Reminder (Popup Safety)

- If a layer was previously tracked and the user:

Manually enables QGIS Toggle Editing without Auto Edit

- A popup appears (once per edit session):

“Do you want to enable Edit Tracking Tool for this layer?”

- This prevents missed edits without forcing tracking on all layers.

**Automatic Edit Tracking (When Enabled)**

Detects:

- Geometry edits

- New features

- Automatically sets:

  - edited = 1

  - edited_dat = <today>

- Runs silently during editing

- Updates live statistics with throttling to avoid freezing

**Attribute Field Creator**

- Creates the required fields only when tracking is enabled:

- edited → integer

  - 0 = not edited

  - 1 = edited

- edited_dat → date

- All existing features are initialized as:
  
  - edited = 0
  - edited_dat = NULL

**To quickly visualize edited vs not edited features:**

- Layer → Properties

- Symbology

- Choose Categorized

- Column = edited

- lick Classify

- Assign different colors for:

  - 0 → Not Edited

  - 1 → Edited

### QC + Editing Tools

| Tool                              | Description                                  |
| --------------------------------- | -------------------------------------------- |
| **Create Edited Fields and Date** | Adds & initializes tracking fields           |
| **Auto Edit (Toggle)**            | Enable / Disable tracking for active layer   |
| **Mark Selected Edited**          | Set selected features as edited              |
| **Update Date (Calendar)**        | Assign custom edit date to selected features |
| **Select NULL Attributes**        | Identify invalid or missing edit values      |
| **Remove NULL Geometry**          | Delete features with empty geometry          |
| **Refresh Stats**                 | Manually refresh statistics panel            |

**Live Statistics Dock**

The dock panel updates only for tracked layers to avoid lag.

Shows:

Total Features

+ Edited Features (1)

- Not Edited Features (0)

- NULL Geometry (highlighted in red)

- NULL Attributes (highlighted in red)

- Day Count — features edited on selected date

Includes:

- Date picker for daily QC monitoring

- Throttled updates to prevent freezing during heavy edit
  
**Performance & Safety**

- No processing on raster layers

- No field scanning on untracked layers

- No lag when switching layers

- Cleans stale layer IDs automatically

- Session-safe popup logic (shown only once per edit session)

**Folder Structure**
  
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

**Installation**

Download the plugin ZIP file

Open QGIS → Plugins → Manage and Install Plugins

Go to Install from ZIP

Select the downloaded ZIP

Enable Edit Tracking Tools

**Version**

Current Release: v1.0.1

What’s New in 1.0.1

- Lag-free layer switching

- Manual tracking control per layer

- Popup reminder for missed Auto Edit

- Raster-safe handling

- Stale layer ID cleanup

- Improved production stability

Author

Renju A J
GitHub: https://github.com/renju94aj-cmd

Email: renju94aj@gmail.com

License

This plugin is released under the MIT License.
