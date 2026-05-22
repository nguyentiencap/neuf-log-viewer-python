#!/usr/bin/env python3
"""
NEUF Log Viewer — CLI (Python port of neuf-log-viewer-cli.js)
Command-line interface for log analysis, optimised for LLM workflows.

Three primary use-cases:
  1. Apply presets to reduce noise and focus on a device / time window
  2. Keyword / regex search so an LLM can locate relevant entries
  3. Paginated output so an LLM can read large logs in manageable batches

Usage:
  python neuf_log_viewer_cli.py presets <folder>
  python neuf_log_viewer_cli.py filter  <folder> [options]
  python neuf_log_viewer_cli.py help
"""

import asyncio
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Bootstrap: make python-port/src importable regardless of cwd
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from src.neuf_log_service import NEUFLogService  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_LOG_LEVELS = ['ERROR', 'WARN', 'INFO', 'DEBUG']
VALID_FORMATS = ['text', 'compact', 'json']
VALID_OPTIONS = [
    'preset',
    'device',
    'level',
    'component',
    'exclude-component',
    'search',
    'time-from',
    'time-to',
    'scan-from',
    'scan-to',
    'context',
    'page',
    'page-size',
    'format',
    'help',
]

# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

HELP_TEXT = """
NEUF Log Viewer CLI — LLM-friendly log analysis tool
=====================================================

Usage:
  python neuf_log_viewer_cli.py <command> <folder> [options]

Commands:
  presets <folder>           List all available preset filters with their IDs.
  filter  <folder> [opts]    Filter and search logs with optional pagination.
                             The database is built automatically on first run.
  help                       Show this help message.

Filter options:
  --preset          <id>     Apply a preset (use ID from 'presets' command).
                             Repeatable: --preset p1 --preset p2
                             Or comma-separated: --preset "p1,p2"
  --device          <id>     Include logs for this device ID. Repeatable.
  --level           <lvl>    Include log level: ERROR|WARN|INFO|DEBUG. Repeatable.
  --component       <name>   Include logs from this component. Repeatable.
  --exclude-component <name> Exclude logs from this component. Repeatable.
   --search          <text>   Search for text or regex in the log message.
                              Supports regex! Examples:
                              --search "Exception|Error"
                              --search "ERROR.*Connection"
   --time-from       <ts>     Start timestamp (YYYY.MM.DD HH:mm:ss).
   --time-to         <ts>     End  timestamp (YYYY.MM.DD HH:mm:ss).
   --scan-from       <ts>     Scan only log entries on or after this timestamp.
                              Entries outside this range are ignored during indexing.
   --scan-to         <ts>     Scan only log entries on or before this timestamp.
                              Entries outside this range are ignored during indexing.
   --context         <n>      Show n lines of context around each search match.
  --page            <n>      Page number for batch reading (default: 1).
  --page-size       <n>      Logs per page (default: 200).
  --format          <fmt>    Output format: text | compact | json (default: text).

Output formats:
  text     Human-readable, one log per line with all fields visible.
  compact  Short one-liner per entry — useful when token budget is limited.
  json     Machine-readable JSON — ideal for LLM structured processing.

Note: To force a re-index, delete the log-filter-db/ folder inside the log
folder and run the command again.
"""


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def parse_args(argv):
    """
    Parse sys.argv into {'command': str, 'folder': str|None, 'options': dict}.

    Supports:
      --flag value      (string)
      Repeated --flag   (accumulated into list)
      --flag            (boolean True)
    """
    args = argv[1:]  # skip script name
    command = args[0] if args else 'help'
    folder = args[1] if len(args) > 1 and not args[1].startswith('--') else None

    options = {}
    i = 2 if folder else 1

    while i < len(args):
        arg = args[i]
        if arg.startswith('--'):
            key = arg[2:]
            next_arg = args[i + 1] if i + 1 < len(args) else None
            if next_arg is None or next_arg.startswith('--'):
                # Boolean flag
                options[key] = True
                i += 1
            else:
                # Value flag — accumulate repeated keys into lists
                if key in options:
                    existing = options[key]
                    if isinstance(existing, list):
                        existing.append(next_arg)
                    else:
                        options[key] = [existing, next_arg]
                else:
                    options[key] = next_arg
                i += 2
        else:
            i += 1

    return {'command': command, 'folder': folder, 'options': options}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def expand_comma_separated(value):
    """
    Expand a single string or list of strings on commas.
    Returns a flat list of non-empty stripped values.
    """
    if not value:
        return []
    items = value if isinstance(value, list) else [value]
    result = []
    for item in items:
        for part in item.split(','):
            stripped = part.strip()
            if stripped:
                result.append(stripped)
    return result


def is_valid_timestamp(ts):
    """Validate YYYY.MM.DD HH:mm:ss format (second-precision only)."""
    if not ts or not isinstance(ts, str):
        return False
    return bool(re.match(r'^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}$', ts))


def levenshtein_distance(a, b):
    """Calculate Levenshtein edit distance between two strings."""
    matrix = [[0] * (len(a) + 1) for _ in range(len(b) + 1)]
    for i in range(len(a) + 1):
        matrix[0][i] = i
    for j in range(len(b) + 1):
        matrix[j][0] = j
    for j in range(1, len(b) + 1):
        for i in range(1, len(a) + 1):
            indicator = 0 if a[i - 1] == b[j - 1] else 1
            matrix[j][i] = min(
                matrix[j][i - 1] + 1,
                matrix[j - 1][i] + 1,
                matrix[j - 1][i - 1] + indicator,
            )
    return matrix[len(b)][len(a)]


def suggest_option_name(typo):
    """Return the closest valid option name, or None if too far away."""
    best = None
    best_distance = 3  # only suggest within 3 edits
    for valid in VALID_OPTIONS:
        dist = levenshtein_distance(typo, valid)
        if dist < best_distance:
            best_distance = dist
            best = valid
    return best


def _validate_integer(value, minimum=None):
    """Return (valid: bool, result: int|None, error: str|None)."""
    if not value or not isinstance(value, str):
        return False, None, 'Value is required'
    try:
        num = int(value)
    except ValueError:
        return False, None, f'Expected integer, got: "{value}"'
    if minimum is not None and num < minimum:
        return False, None, f'Expected value >= {minimum}, got: {num}'
    return True, num, None


def validate_options(command, opts):
    """
    Validate all CLI options.  Writes errors to stderr and exits with code 1
    if any validation fails.
    """
    errors = []

    # Unknown options
    for key in opts:
        if key not in VALID_OPTIONS:
            suggestion = suggest_option_name(key)
            if suggestion:
                errors.append(
                    f'❌ Unknown option: --{key}\n   Did you mean: --{suggestion}?'
                )
            else:
                valid_list = ', '.join(f'--{o}' for o in VALID_OPTIONS)
                errors.append(
                    f'❌ Unknown option: --{key}\n   Valid options: {valid_list}'
                )

    # Log levels
    if opts.get('level'):
        levels = opts['level'] if isinstance(opts['level'], list) else [opts['level']]
        for lvl in levels:
            if lvl.upper() not in VALID_LOG_LEVELS:
                errors.append(
                    f'❌ Invalid --level "{lvl}". Allowed values: {" | ".join(VALID_LOG_LEVELS)}'
                )

    # Format
    if opts.get('format') and opts['format'] not in VALID_FORMATS:
        errors.append(
            f'❌ Invalid --format "{opts["format"]}". Allowed values: {" | ".join(VALID_FORMATS)}'
        )

    # Timestamps
    for key in ('time-from', 'time-to', 'scan-from', 'scan-to'):
        if opts.get(key) and not is_valid_timestamp(opts[key]):
            errors.append(
                f'❌ Invalid --{key} "{opts[key]}". Expected format: YYYY.MM.DD HH:mm:ss\n'
                f'   Example: --{key} "2026.05.08 10:30:00"'
            )

    # Numeric options
    for key, minimum in (('page', 1), ('page-size', 1), ('context', 0)):
        if opts.get(key):
            valid, _, err = _validate_integer(opts[key], minimum)
            if not valid:
                errors.append(
                    f'❌ Invalid --{key} "{opts[key]}". {err}\n'
                    f'   Example: --{key} {"1" if key == "page" else "200" if key == "page-size" else "5"}'
                )

    if errors:
        sys.stderr.write('\n' + '\n'.join(errors) + '\n\n')
        sys.stderr.write('💡 For help, run: python neuf_log_viewer_cli.py help\n')
        sys.exit(1)


def build_filters(opts):
    """Build a filters dict from validated CLI options."""
    filters = {}

    if opts.get('preset'):
        filters['preset'] = expand_comma_separated(opts['preset'])
    if opts.get('device'):
        filters['deviceInclude'] = expand_comma_separated(opts['device'])
    if opts.get('level'):
        levels = expand_comma_separated(opts['level'])
        filters['logLevelInclude'] = [lvl.upper() for lvl in levels]
    if opts.get('component'):
        filters['componentInclude'] = expand_comma_separated(opts['component'])
    if opts.get('exclude-component'):
        filters['componentExclude'] = expand_comma_separated(opts['exclude-component'])
    if opts.get('search'):
        filters['search'] = opts['search']
    if opts.get('time-from'):
        filters['timeFrom'] = opts['time-from']
    if opts.get('time-to'):
        filters['timeTo'] = opts['time-to']
    if opts.get('context'):
        filters['contextLines'] = int(opts['context']) if opts['context'] else 0

    return filters


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def format_text(log):
    """Full human-readable format: timestamp [level] thread: <device> (component) message  [file]"""
    line = f"{log.get('timestamp', '')} [{log.get('log_level', '')}]"
    if log.get('thread_name'):
        line += f" {log['thread_name']}:"
    if log.get('device_id'):
        line += f" <{log['device_id']}>"
    if log.get('component_name'):
        line += f" ({log['component_name']})"
    line += f" {log.get('message', '')}"
    if log.get('filename'):
        line += f"  [{log['filename']}]"
    return line


def format_compact(log):
    """Compact one-liner: timestamp [level] (component) message"""
    line = f"{log.get('timestamp', '')} [{log.get('log_level', '')}]"
    if log.get('component_name'):
        line += f" ({log['component_name']})"
    line += f" {log.get('message', '')}"
    return line


def _print_pagination_info(result):
    """Print pagination summary to stdout."""
    sys.stdout.write(
        f"\n--- Page {result['page']}/{result['totalPages']}"
        f" | Showing {len(result['logs'])} of {result['total']} matching logs ---\n"
    )
    if result['page'] < result['totalPages']:
        sys.stdout.write(
            f"    (use --page {result['page'] + 1} to read the next batch)\n"
        )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def ensure_database(folder, log_service, scan_time_from=None, scan_time_to=None):
    """
    Ensure the database is indexed for the given folder.
    Writes status to stderr so stdout stays clean (e.g. for JSON output).
    """
    if log_service.is_database_scanned(folder):
        return

    sys.stderr.write(f'📁 Indexing logs in: {folder}\n')
    try:
        result = await log_service.scan_logs(folder, scan_time_from=scan_time_from,
                                             scan_time_to=scan_time_to)
        sys.stderr.write(
            f"✅ Indexed {result['data']['totalLogs']} log entries"
            f" from {result['data']['filesScanned']} file(s).\n\n"
        )
    except Exception as err:
        sys.stderr.write(f'❌ Indexing failed: {err}\n')
        sys.exit(1)


async def warn_if_scan_meta(folder, log_service):
    """Print a warning to stderr if the database was scanned with a time range restriction."""
    scan_meta = await log_service.get_db_scan_meta(folder)
    warning = log_service.build_scan_meta_warning(scan_meta)
    if warning:
        sys.stderr.write(f'\n{warning}\n\n')


async def cmd_presets(folder, _opts, log_service):
    """List all available presets for the given log folder."""
    await log_service.initialize()
    await ensure_database(folder, log_service,
                          scan_time_from=_opts.get('scan-from'),
                          scan_time_to=_opts.get('scan-to'))
    await warn_if_scan_meta(folder, log_service)

    result = await log_service.get_preset_suggestions(folder)

    if not result.get('success'):
        sys.stderr.write(f"❌ Failed to load presets: {result.get('error')}\n")
        sys.exit(1)

    suggestions = result['suggestions']
    if not suggestions:
        sys.stdout.write('ℹ️  No presets available for this folder.\n')
        return

    sys.stdout.write(f'\nAvailable presets ({len(suggestions)}):\n')
    sys.stdout.write('─' * 60 + '\n')
    for s in suggestions:
        sys.stdout.write(f"  ID:          {s['id']}\n")
        sys.stdout.write(f"  Label:       {s['label']}\n")
        if s.get('description') and s['description'] != s['label']:
            sys.stdout.write(f"  Description: {s['description']}\n")
        sys.stdout.write('\n')

    sys.stdout.write("Use --preset <ID> with the 'filter' command to apply a preset.\n")


async def cmd_filter(folder, opts, log_service):
    """Filter logs and print results."""
    await log_service.initialize()
    await ensure_database(folder, log_service,
                          scan_time_from=opts.get('scan-from'),
                          scan_time_to=opts.get('scan-to'))
    await warn_if_scan_meta(folder, log_service)

    filters = build_filters(opts)
    normalized = log_service.normalize_filters(filters)
    await log_service.apply_preset(folder, normalized)

    page = int(opts.get('page', 1) or 1)
    page_size = int(opts.get('page-size', 200) or 200)
    fmt = opts.get('format', 'text') or 'text'

    result = await log_service.filter_logs(folder, normalized, {'page': page, 'pageSize': page_size})

    if not result.get('success'):
        sys.stderr.write(f"❌ Filter failed: {result.get('error')}\n")
        sys.exit(1)

    if fmt == 'json':
        sys.stdout.write(
            json.dumps(
                {
                    'page': result['page'],
                    'totalPages': result['totalPages'],
                    'total': result['total'],
                    'pageSize': result['pageSize'],
                    'logs': result['logs'],
                },
                indent=2,
                default=str,
            ) + '\n'
        )
        return

    # text / compact output
    for log in result['logs']:
        line = format_compact(log) if fmt == 'compact' else format_text(log)
        sys.stdout.write(line + '\n')

    _print_pagination_info(result)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main():
    parsed = parse_args(sys.argv)
    command = parsed['command']
    folder = parsed['folder']
    options = parsed['options']

    if command == 'help' or options.get('help'):
        sys.stdout.write(HELP_TEXT + '\n')
        sys.exit(0)

    if not folder:
        sys.stderr.write(
            f"❌ Error: <folder> is required for the '{command}' command.\n\n"
            f'Usage: python neuf_log_viewer_cli.py {command} <folder> [options]\n'
            f'Example: python neuf_log_viewer_cli.py {command} /path/to/logs\n\n'
            '💡 For help, run: python neuf_log_viewer_cli.py help\n'
        )
        sys.exit(1)

    resolved_folder = os.path.realpath(os.path.abspath(folder))

    if not os.path.exists(resolved_folder):
        sys.stderr.write(
            f'❌ Error: Folder does not exist: {resolved_folder}\n\n'
            '💡 Please provide a valid folder path.\n'
        )
        sys.exit(1)

    if not os.path.isdir(resolved_folder):
        sys.stderr.write(
            f'❌ Error: Path is not a directory: {resolved_folder}\n\n'
            '💡 Please provide a directory path, not a file.\n'
        )
        sys.exit(1)

    if command == 'filter':
        validate_options(command, options)

    # Silent logger — suppress internal service noise on stdout
    log_service = NEUFLogService(logger=lambda *_: None)

    try:
        if command == 'presets':
            await cmd_presets(resolved_folder, options, log_service)
        elif command == 'filter':
            await cmd_filter(resolved_folder, options, log_service)
        else:
            sys.stderr.write(
                f"❌ Unknown command: '{command}'\n\n"
                'Available commands:\n'
                '  - presets <folder>          List available presets\n'
                '  - filter  <folder> [opts]   Filter logs with options\n'
                '  - help                      Show this help message\n\n'
                f'Example: python neuf_log_viewer_cli.py filter /path/to/logs --search "Error"\n\n'
                '💡 For help, run: python neuf_log_viewer_cli.py help\n'
            )
            sys.exit(1)
    except Exception as err:
        sys.stderr.write(f'❌ Error: {err}\n')
        if os.environ.get('DEBUG'):
            import traceback
            sys.stderr.write(traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
