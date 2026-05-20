# NEUF Log Viewer (Python)

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

The recommended workflow for LLM-assisted diagnosis is:
```
1. Ask user: device? time window? keywords?
2. Check available presets  →  neuf-log-viewer-cli.exe presets <folder>
3. Filter with preset + device + time  →  --format compact  (fast pattern scan)
4. Infer regex keywords from compact output
5. Re-filter with --search REGEX --format json --context N  (detailed analysis)
6. If no results, progressively expand (time → preset → keyword → device)
```

---

## Installation & Running

### Requirements
- Python 3.11+
- pip

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Build Windows `.exe`
```bat
build_exe.bat
```

Output files:
- `dist\neuf-log-viewer-cli.exe`
- `dist\neuf-log-viewer-api.exe`
- `dist\USERGUIDE.md`

### Run the Web UI (API Server)
```bash
python neuf_log_viewer_api.py <path-to-log-folder>
```

Example:
```bash
python neuf_log_viewer_api.py ./logs
```

The server will be available at: **http://localhost:3001**

> The database is built automatically on first run inside `<log-folder>/log-filter-db/`.  
> To force a full re-index, delete the entire `log-filter-db/` directory and restart.

---

## Web Interface (Web UI)

Open a web browser and go to: **http://localhost:3001**

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

## CLI (Command-Line Interface)

The CLI is optimised for LLM-assisted workflows and scripting. It supports the same filters as the Web UI.

### Commands

```bash
python neuf_log_viewer_cli.py presets <folder>
python neuf_log_viewer_cli.py filter  <folder> [options]
python neuf_log_viewer_cli.py help
```

Or using the built `.exe`:
```bash
neuf-log-viewer-cli.exe presets <folder>
neuf-log-viewer-cli.exe filter  <folder> [options]
```

### Filter Options

| Option | Description |
|---|---|
| `--preset <id>` | Apply a preset by ID (repeatable or comma-separated) |
| `--device <id>` | Include logs for this device ID (repeatable) |
| `--level <lvl>` | Include log level: `ERROR`\|`WARN`\|`INFO`\|`DEBUG` (repeatable) |
| `--component <name>` | Include logs from this component (repeatable) |
| `--exclude-component <name>` | Exclude logs from this component (repeatable) |
| `--search <text>` | Search message field — **supports full regex** |
| `--time-from <ts>` | Start timestamp `YYYY.MM.DD HH:mm:ss` |
| `--time-to <ts>` | End timestamp `YYYY.MM.DD HH:mm:ss` |
| `--context <n>` | Show n lines of context around each search match |
| `--page <n>` | Page number (default: 1) |
| `--page-size <n>` | Logs per page (default: 200) |
| `--format <fmt>` | Output format: `text` \| `compact` \| `json` |

Multi-value options accept repeated flags or comma-separated values:
```bash
--preset "errors_and_warnings,exclude_noisy_components"   # comma-separated
--preset errors_and_warnings --preset exclude_noisy_components   # repeated flags
```

### Output Formats

| Format | Best for |
|---|---|
| `text` | Human-readable, one log per line with all fields |
| `compact` | Short one-liner per entry — fast pattern scanning, token-efficient |
| `json` | Machine-readable — ideal for LLM structured processing |

### CLI Examples

**List available presets:**
```bash
python neuf_log_viewer_cli.py presets ./logs
```

**Quick error scan for a device in a time window:**
```bash
python neuf_log_viewer_cli.py filter ./logs \
  --device "TC101514400004" \
  --time-from "2026.05.08 09:45:00" --time-to "2026.05.08 10:15:00" \
  --preset "errors_and_warnings" \
  --format compact \
  --page 1 --page-size 100
```

**Regex search with context:**
```bash
python neuf_log_viewer_cli.py filter ./logs \
  --device "TC101514400004" \
  --search "Exception|Connection|Timeout" \
  --format json \
  --context 5 \
  --page 1
```

**Combine preset + component include + search:**
```bash
python neuf_log_viewer_cli.py filter ./logs \
  --preset "errors_and_warnings" \
  --component "com.app.network,com.app.bootstrap" \
  --search "refused|timeout" \
  --format json \
  --page 1
```

**Exclude noisy components, show all levels:**
```bash
python neuf_log_viewer_cli.py filter ./logs \
  --preset "exclude_noisy_components" \
  --format text \
  --page-size 500
```

### Regex Search Tips

The `--search` flag supports full Python-compatible regular expressions:

| Pattern | Purpose |
|---|---|
| `Exception` or `Error` | Match either word — use `Exception\|Error` in the shell |
| `ERROR.*Connection` | ERROR logs containing "Connection" |
| `Timeout` or `Hung` or `Stalled` | Any timeout-related message — `Timeout\|Hung\|Stalled` |
| `OutOfMemory` or `OOM` | Memory crisis — `OutOfMemory\|OOM` |
| `Connection.*refused` | Connection refused errors |
| `java:[0-9]+` | Stack trace line references |

---

## Creating Custom Presets

Edit `preset.json` at the project root. Add new entries using this structure:

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

### Supported Filter Fields

| Field | Type | Description |
|---|---|---|
| `logLevelInclude` | `string[]` | Include only these log levels — e.g. `["ERROR", "WARN"]` |
| `logLevelExclude` | `string[]` | Exclude these log levels |
| `componentInclude` | `(string\|null)[]` | Include only these components; supports SQL `%LIKE%` wildcards; `null` matches logs with no component |
| `componentExclude` | `(string\|null)[]` | Exclude these components; supports SQL `%LIKE%` wildcards; `null` excludes logs with no component |
| `threadInclude` | `string[]` | Include only these thread names |
| `threadExclude` | `string[]` | Exclude these thread names |
| `deviceInclude` | `string[]` | Include only these device IDs |
| `deviceExclude` | `string[]` | Exclude these device IDs |
| `filenameInclude` | `string[]` | Include only logs from these source files |
| `filenameExclude` | `string[]` | Exclude logs from these source files |

### Preset Examples

**Show only errors and warnings:**
```json
"my_errors": {
  "id": "my_errors",
  "label": "⚠️ Errors & Warnings",
  "description": "Show ERROR and WARN only",
  "filters": { "logLevelInclude": ["ERROR", "WARN"] }
}
```

**Exclude a noisy component using a wildcard:**
```json
"no_heartbeat": {
  "id": "no_heartbeat",
  "label": "💓 Exclude Heartbeat",
  "description": "Hide all heartbeat-related components",
  "filters": { "componentExclude": ["%Heartbeat%", "%Ping%"] }
}
```

**Show only logs that have a component name (hide framework noise):**
```json
"components_only": {
  "id": "components_only",
  "label": "🔍 Has Component Only",
  "description": "Show only logs with a component name",
  "filters": { "componentExclude": [null] }
}
```

**Notes:**
- Changes to `preset.json` take effect immediately — no server restart required.
- If a data-derived preset (auto-generated from your log data) shares the same `id` as a `preset.json` entry, the data-derived one takes precedence.

---

## Log Format

NEUF Log Viewer parses the DWS standard log format:

```
YYYY.MM.DD HH:mm:ss.SSS [LEVEL] [class ClassName]: ThreadName: <DeviceID> (ComponentName) Message
```

Example:
```
2026.04.01 14:23:45.123 [ERROR] [class DeviceManager]: pool-1: <TC101514400004> (DwsCoreImpl) Device connection timeout
```

| Field | Example value | Description |
|---|---|---|
| Timestamp | `2026.04.01 14:23:45.123` | `YYYY.MM.DD HH:mm:ss.SSS` |
| Level | `ERROR` | ERROR, WARN, INFO, DEBUG, TRACE |
| ClassName | `DeviceManager` | Java class name |
| ThreadName | `pool-1` | Thread name |
| DeviceID | `TC101514400004` | Device identifier (optional) |
| ComponentName | `DwsCoreImpl` | OSGi/bundle component name (optional) |
| Message | `Device connection timeout` | Log message body |

---

## Directory Structure

```
📁 <project-root>/              ← wherever you cloned the repo
├── neuf_log_viewer_api.py      ← Web UI / API server entry point
├── neuf_log_viewer_cli.py      ← CLI entry point
├── preset.json                 ← custom preset definitions
├── requirements.txt            ← Python runtime dependencies
├── build_exe.bat               ← Windows build script
└── src/                        ← shared library code

📁 <your-log-folder>/           ← the folder you pass as argument
├── NEUF-DWS-Core.81.log
├── NEUF-Impl-Bundle.145.log
├── ... (other .log files)
└── log-filter-db/
    └── neuf-logs.db             ← SQLite database (created automatically)
```

---

## Database Management

### Storage Location
```
<log-folder>/log-filter-db/neuf-logs.db
```

### Rebuilding the Database

If you add new log files or want a clean re-index:
```bash
rmdir /s /q <log-folder>\log-filter-db
python neuf_log_viewer_api.py <log-folder>
```

---

**Version:** 1.0.0  
**Last updated:** 2026-05-20

