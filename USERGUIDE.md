# NEUF Log Viewer

## The Problem

NEUF DWS systems produce very large log files — often hundreds of thousands of lines across many files — from dozens of components running on multiple devices simultaneously. When you need to diagnose an issue, finding the relevant entries is extremely time-consuming because:

- Logs span multiple files with no single view
- Many high-volume components (endpoints, historical data, wiring, DWS internals) produce noise that buries the signal
- Searching without context means repeatedly scrolling through irrelevant lines
- LLM-assisted analysis is impractical when the raw log volume far exceeds token budgets

## The Approach

NEUF Log Viewer solves this by **indexing all logs into a local SQLite database** on first run, then exposing fast, composable filters through both a Web UI and a CLI:

1. **Presets** — one-click noise reduction (exclude known high-volume components, show errors only, etc.)
2. **Multi-dimensional filters** — narrow by log level, device, component, thread, filename, and time range simultaneously
3. **Keyword / regex search** — full regex support so you can search for `Exception|Error|Timeout` or `ERROR.*Connection` in one pass
4. **Context lines** — show N lines surrounding each match so you see what happened before and after
5. **Pagination** — browse large result sets in manageable pages
6. **Export** — download the filtered result as a plain `.log` file


## Installation & Running


- Operating system: Windows (64-bit)
- A log folder to analyze (containing NEUF `.log` files)
- Release package files:
  - `neuf-log-viewer.exe`
  - `preset.json`
  - `USERGUIDE.md`

> Keep `neuf-log-viewer.exe` and `preset.json` in the same folder.

---

Open Command Prompt or PowerShell in the folder containing `neuf-log-viewer.exe`, then run:

```powershell
.\neuf-log-viewer.exe <path-to-log-folder>
```

Example:

```powershell
.\neuf-log-viewer.exe D:\logs\NEUF
```

When started successfully, the app launches the Web UI at:

- **http://localhost:3001**

---

## Web Interface (Web UI)

Open a web browser and go to: **http://localhost:3001**

### Presets

Presets are saved filter combinations that remove common noise or focus on a specific concern. Select one or more from the **Presets** panel to apply them before or alongside your own filters.

Built-in presets (defined in `preset.json`):

| Preset ID | What it does |
|---|---|
| `errors_and_warnings` | Show ERROR and WARN levels |
| `errors_only` | Show ERROR level only |
| `exclude_noisy_components` | Exclude Endpoint, Historical, Dws*, Wiring, and other high-volume components |
| `exclude_endpoint_tester` | Exclude components matching `%Endpoint%` |
| `exclude_historical_data` | Exclude components matching `%Historical%` |
| `exclude_dws` | Exclude components matching `Dws%` |
| `exclude_wiring` | Exclude components matching `%Wiring%` |
| `component_not_null` | Show only logs that have a component name |
| `component_null` | Show only logs that have no component name |

### Log Filtering

Enter filter criteria in the sidebar on the left:

| Field | Description |
|---|---|
| **Log Level** | Select which levels to show (ERROR, WARN, INFO, DEBUG) |
| **Thread** | Include or exclude thread names |
| **Device** | Include or exclude device IDs |
| **Component** | Include or exclude component names |
| **Filename** | Include or exclude source log files |
| **Time From / To** | Restrict results to a time range |
| **Search** | Full-text or **regex** search in the message field |
| **Context Lines** | Show N lines before and after each search match |

Click **Apply** to run the filter. Results appear in the main panel with total count and pagination controls.

### Pagination
- Adjust the number of logs per page (default: 50)
- Navigate between pages using the navigation buttons
- View total matching logs and number of pages

### Export
Export all logs matching the current filters to a `.log` file:
- Click the **Export** button
- The file downloads to your computer
- Filename format: `neuf-logs-export-<timestamp>.log`

---

### Creating Custom Presets

Edit `preset.json` at the project root (same folder as `neuf-log-viewer-api.js`). Add new entries using this structure:

```json
{
  "my_preset_id": {
    "id": "my_preset_id",
    "label": "🏷️ My Preset Label",
    "description": "Short description shown in the UI",
    "filters": {
      "componentExclude": ["%MyNoisyComponent%"],
      "logLevelInclude": ["ERROR", "WARN"]
    }
  }
}
```

### Quick Filtering Tips

- If you need specific issues, enter keywords in **Search**, Regex is supportted
- Increase **Context Lines** to include lines before/after each match

---

## Where is the database stored?

The app automatically creates a database on first run at:

```text
<log-folder>/log-filter-db/neuf-logs.db
```

On Windows, this path is equivalent to:

```text
<log-folder>\log-filter-db\neuf-logs.db
```

If you add new logs or want a full re-index:

1. Stop the application
2. Delete the `log-filter-db` folder inside your log folder
3. Run `neuf-log-viewer.exe` again

---

## Common Issues

### Cannot open `http://localhost:3001`

- Check whether the terminal window shows an error
- Make sure you provided the correct log folder path
- Restart the application

### Error: log folder path does not exist

- Verify the path passed to the run command
- If the path contains spaces, wrap it in double quotes:

```powershell
.\neuf-log-viewer.exe "D:\My Logs\NEUF"
```
