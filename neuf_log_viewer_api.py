#!/usr/bin/env python3
"""
NEUF Log Viewer — REST API Server (Python/FastAPI port of neuf-log-viewer-api.js)

Usage:
  python neuf_log_viewer_api.py <folderPath>

Provides REST API endpoints for log analysis:
  POST /filter_log          - Filter logs with pagination
  POST /filter_option       - Get filter options for a result table
  POST /export_log          - Export filtered logs
  POST /preset_suggestions  - Get preset filter suggestions
  GET  /health              - Health check
"""

import io
import json
import os
import sys
import traceback
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Bootstrap: make python-port/src importable
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from src.neuf_log_service import NEUFLogService  # noqa: E402


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class FilterLogRequest(BaseModel):
    filters: Optional[Dict[str, Any]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    page: int = 1
    pageSize: int = 2000
    raw: bool = False
    dedup: str = 'annotate'


class ExportLogRequest(BaseModel):
    filters: Optional[Dict[str, Any]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    format: str = 'full'
    dedup: str = 'annotate'
    # Supported format values:
    #   'full', 'compact', 'csv', 'json'


class FilterOptionRequest(BaseModel):
    outputTable: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_filters_from_request(query: dict, log_service) -> dict:
    """
    Build a normalised filters dict from a raw request body dict.
    This is the API layer's responsibility (mirrors parseFiltersFromRequest in JS).
    """
    has_context_lines = 'contextLines' in query
    has_strict_context = 'strictContext' in query

    raw_context = query.get('contextLines')
    if has_context_lines:
        try:
            context_lines = int(raw_context) if raw_context is not None else 0
        except (ValueError, TypeError):
            context_lines = 0
    else:
        context_lines = None  # sentinel: not present

    raw_strict = query.get('strictContext')
    if has_strict_context:
        strict_context = raw_strict is True or str(raw_strict).lower() == 'true'
    else:
        strict_context = None  # sentinel: not present

    filters = {
        'filenameInclude': query.get('filenameInclude') or [],
        'logLevelInclude': query.get('logLevelInclude') or [],
        'threadInclude': query.get('threadInclude') or [],
        'deviceInclude': query.get('deviceInclude') or [],
        'componentInclude': query.get('componentInclude') or [],

        'filenameExclude': query.get('filenameExclude') or [],
        'logLevelExclude': query.get('logLevelExclude') or [],
        'threadExclude': query.get('threadExclude') or [],
        'deviceExclude': query.get('deviceExclude') or [],
        'componentExclude': query.get('componentExclude') or [],

        'timeFrom': query.get('timeFrom') or None,
        'timeTo': query.get('timeTo') or None,
        'search': query.get('search') or '',
        'preset': query.get('preset') or '',
    }

    if has_context_lines:
        filters['contextLines'] = context_lines
    if has_strict_context:
        filters['strictContext'] = strict_context

    return log_service.normalize_filters(filters)


def escape_csv_value(value) -> str:
    """Escape a value for CSV output."""
    if value is None:
        return ''
    s = str(value)
    if ',' in s or '"' in s or '\n' in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def _export_timestamp() -> str:
    """Generate a YYYY.MM.DD_HH-mm-ss timestamp string for file names."""
    now = datetime.now()
    return now.strftime('%Y.%m.%d_%H-%M-%S')


def _format_patterns_markdown(patterns: list, generated_at: str) -> str:
    """
    Render a repeated-patterns list (from dedup_and_extract_patterns) as a
    human-readable Markdown report.

    Each pattern dict is expected to have a 'block_lines' key containing
    the already-formatted log lines (full or compact) for the first occurrence
    of the block.  Falls back to 'message' if block_lines is absent.
    """
    out = []
    out.append('# NEUF Log — Repeated Patterns Report')
    out.append('')
    out.append(f'**Generated:** {generated_at}')
    out.append(f'**Total patterns found:** {len(patterns)}')
    out.append('')
    out.append('---')
    out.append('')

    if not patterns:
        out.append('_No repeated patterns detected._')
        return '\n'.join(out)

    for i, p in enumerate(patterns, 1):
        count = p.get('repeat_count', 0)
        times_label = 'time' if count == 1 else 'times'
        out.append(f'## Pattern #{i} — Repeated {count} {times_label}')
        out.append('')

        component = p.get('component_name') or ''
        device    = p.get('device_id')     or ''
        level     = p.get('log_level')     or ''
        plen      = p.get('pattern_length', 1)

        if component:
            out.append(f'**Component:** `{component}`  ')
        if device:
            out.append(f'**Device:** `{device}`  ')
        if level:
            out.append(f'**Level:** `{level}`  ')
        out.append(f'**Block length:** {plen} consecutive line{"s" if plen != 1 else ""}  ')
        out.append(f'**First seen:** {p.get("first_occurrence", "")}  ')
        out.append('')

        # block_lines: formatted log lines for the first occurrence of this block.
        # Falls back to the raw message field when not available.
        block_lines = p.get('block_lines')
        if block_lines:
            label = 'Message' if len(block_lines) == 1 else f'Block ({len(block_lines)} lines)'
        else:
            block_lines = [p.get('message', '')]
            label = 'Message'
        out.append(f'**{label}:**')
        out.append('```')
        for line in block_lines:
            out.append(line)
        out.append('```')
        out.append('')

        occurrences = p.get('occurrences', [])
        out.append(f'**All occurrences ({len(occurrences)}):**')
        out.append('')
        out.append('| # | Line | Timestamp |')
        out.append('|---|------|-----------|')
        for j, occ in enumerate(occurrences, 1):
            out.append(f'| {j} | {occ.get("line", "")} | {occ.get("timestamp", "")} |')
        out.append('')
        out.append('---')
        out.append('')

    return '\n'.join(out)


# ---------------------------------------------------------------------------
# App factory (dependency-injection friendly for tests)
# ---------------------------------------------------------------------------

def create_app(folder_path: str, log_service=None) -> FastAPI:
    """
    Create and return a FastAPI application bound to folder_path.
    If log_service is None, a new NEUFLogService is created.
    """
    if log_service is None:
        log_service = NEUFLogService(logger=print, sql_logger=print)

    app = FastAPI(title='NEUF Log Viewer API', version='1.0.0')

    # CORS — mirrors the JS API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_methods=['*'],
        allow_headers=['*'],
    )

    # -----------------------------------------------------------------------
    # Request logging middleware
    # -----------------------------------------------------------------------

    @app.middleware('http')
    async def log_requests(request: Request, call_next):
        body_bytes = await request.body()
        try:
            body_str = body_bytes.decode('utf-8') if body_bytes else ''
        except Exception:
            body_str = '<binary>'
        print(f'[REQUEST] {request.method} {request.url.path} body={body_str}')

        # Re-inject body so downstream handlers can read it
        async def receive():
            return {'type': 'http.request', 'body': body_bytes}

        request = Request(request.scope, receive)
        response = await call_next(request)
        return response

    # -----------------------------------------------------------------------
    # GET /health
    # -----------------------------------------------------------------------

    @app.get('/health')
    async def health():
        scanned = log_service.is_database_scanned(folder_path)
        scan_meta = await log_service.get_db_scan_meta(folder_path) if scanned else \
                    {'scanTimeFrom': None, 'scanTimeTo': None}
        return JSONResponse({
            'success': True,
            'status': 'healthy',
            'version': '1.0.0',
            'databaseScanned': scanned,
            'folderPath': folder_path,
            'scanMeta': scan_meta,
        })

    # -----------------------------------------------------------------------
    # POST /preset_suggestions
    # -----------------------------------------------------------------------

    @app.post('/preset_suggestions')
    async def preset_suggestions():
        try:
            result = await log_service.get_preset_suggestions(folder_path)
            return JSONResponse(result)
        except Exception:
            traceback.print_exc()
            return JSONResponse({'success': False, 'error': 'Internal server error'}, status_code=500)

    # -----------------------------------------------------------------------
    # POST /filter_log
    # -----------------------------------------------------------------------

    @app.post('/filter_log')
    async def filter_log(body: FilterLogRequest):
        try:
            # Resolve which filters object to use (new-style or legacy steps)
            raw_filters = body.filters or {}
            if not raw_filters and body.steps:
                raw_filters = (body.steps[0] or {}).get('filters', {})

            parsed_filters = parse_filters_from_request(raw_filters, log_service)
            await log_service.apply_preset(folder_path, parsed_filters)

            result = await log_service.filter_logs(
                folder_path, parsed_filters, {'page': body.page, 'pageSize': body.pageSize}
            )

            if body.raw:
                return JSONResponse(result)

            # Apply per-page dedup before formatting
            dedup_mode = body.dedup if body.dedup in ('none', 'annotate', 'skip') else 'annotate'
            logs, _ = log_service.dedup_and_extract_patterns(result.get('logs', []), dedup_mode)

            # Format logs (API layer responsibility)
            formatted_logs = [log_service.format_log_entry(log, 'full') for log in logs]
            return JSONResponse({
                **result,
                'logs': formatted_logs,
            })

        except Exception:
            traceback.print_exc()
            return JSONResponse({'success': False, 'error': 'Internal server error'}, status_code=500)

    # -----------------------------------------------------------------------
    # POST /filter_option
    # -----------------------------------------------------------------------

    @app.post('/filter_option')
    async def filter_option(body: FilterOptionRequest):
        try:
            result = await log_service.get_filter_options(folder_path, body.outputTable)
            return JSONResponse(result)
        except Exception:
            traceback.print_exc()
            return JSONResponse({'success': False, 'error': 'Internal server error'}, status_code=500)

    # -----------------------------------------------------------------------
    # POST /export_log
    # -----------------------------------------------------------------------

    @app.post('/export_log')
    async def export_log(body: ExportLogRequest):
        try:
            raw_filters = body.filters or {}
            if not raw_filters and body.steps:
                raw_filters = (body.steps[0] or {}).get('filters', {})

            fmt = body.format
            if fmt not in ('full', 'compact', 'json', 'csv'):
                fmt = 'full'

            dedup_mode = body.dedup if body.dedup in ('none', 'annotate', 'skip') else 'annotate'

            parsed_filters = parse_filters_from_request(raw_filters, log_service)
            await log_service.apply_preset(folder_path, parsed_filters)

            export_page_size = 5000
            first_result = await log_service.filter_logs(
                folder_path, parsed_filters, {'page': 1, 'pageSize': export_page_size}
            )

            # Collect all pages (raw logs first, dedup applied across full dataset)
            all_raw_logs = list(first_result.get('logs', []))
            total_pages = first_result.get('totalPages', 1)
            for page in range(2, total_pages + 1):
                page_result = await log_service.filter_logs(
                    folder_path, parsed_filters, {'page': page, 'pageSize': export_page_size}
                )
                all_raw_logs.extend(page_result.get('logs', []))

            ts = _export_timestamp()

            def _build_export_content(logs_list, format_type, ts_str, prefix=""):
                pfx = f'{prefix}-' if prefix else ''
                if format_type in ('json', 'csv'):
                    exported = logs_list
                else:
                    exported = [log_service.format_log_entry(lg, format_type) for lg in logs_list]

                if format_type == 'json':
                    filename = f'neuf-logs-export-{pfx}json-{ts_str}.json'
                    content = json.dumps(exported, indent=2, default=str).encode('utf-8')
                    return filename, content, 'application/json; charset=utf-8'

                elif format_type == 'csv':
                    filename = f'neuf-logs-export-{pfx}csv-{ts_str}.csv'
                    lines = []
                    if exported:
                        headers = ['filename', 'timestamp', 'log_level', 'thread', 'device', 'component', 'message']
                        lines.append(','.join(escape_csv_value(h) for h in headers))
                        for lg in exported:
                            row = [
                                f'({lg.get("filename", "")})',
                                lg.get('timestamp', ''),
                                f'[{lg.get("log_level", "")}]',
                                lg.get('thread_name', ''),
                                f'<{lg.get("device_id", "")}>',
                                f'({lg.get("component_name", "")})',
                                lg.get('message', ''),
                            ]
                            lines.append(','.join(escape_csv_value(v) for v in row))
                    content = '\n'.join(lines).encode('utf-8')
                    return filename, content, 'text/csv; charset=utf-8'

                else:
                    # 'full' or 'compact'
                    format_suffix = 'compact' if format_type == 'compact' else 'full'
                    filename = f'neuf-logs-export-{pfx}{format_suffix}-{ts_str}.log'
                    lines = [lg.get('formattedLog', '') if isinstance(lg, dict) else str(lg) for lg in exported]
                    content = '\n'.join(lines).encode('utf-8')
                    return filename, content, 'text/plain; charset=utf-8'

            if dedup_mode == 'none':
                filename, content, media_type = _build_export_content(all_raw_logs, fmt, ts)
                return Response(
                    content=content,
                    media_type=media_type,
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'},
                )
            else:
                # 1. Original format without deduplication
                orig_filename, orig_content, _ = _build_export_content(all_raw_logs, fmt, ts, prefix='original')

                # 2. Deduped format & 3. Markdown pattern report (processed together)
                deduped_logs, patterns = log_service.dedup_and_extract_patterns(all_raw_logs, dedup_mode)
                dedup_filename, dedup_content, _ = _build_export_content(deduped_logs, fmt, ts, prefix='dedup')

                for p in patterns:
                    raw_block = p.pop('block_rows', [])
                    block_formatted = [log_service.format_log_entry(row, 'full') for row in raw_block]
                    p['block_lines'] = [
                        f.get('formattedLog', '') if isinstance(f, dict) else str(f)
                        for f in block_formatted
                    ]
                generated_at = datetime.now().strftime('%Y.%m.%d %H:%M:%S')
                md_content = _format_patterns_markdown(patterns, generated_at).encode('utf-8')
                md_filename = f'neuf-logs-repeated-patterns-{ts}.md'

                # Pack into a ZIP
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(orig_filename, orig_content)
                    zf.writestr(dedup_filename, dedup_content)
                    zf.writestr(md_filename, md_content)
                zip_buffer.seek(0)

                zip_filename = f'neuf-logs-export-{ts}.zip'
                return Response(
                    content=zip_buffer.read(),
                    media_type='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="{zip_filename}"'},
                )

        except Exception:
            traceback.print_exc()
            return JSONResponse({'success': False, 'error': 'Internal server error'}, status_code=500)

    # Mount static frontend files AFTER all API routes so API routes take precedence
    _public_dir = os.path.join(_HERE, 'public')
    if os.path.isdir(_public_dir):
        app.mount('/', StaticFiles(directory=_public_dir, html=True), name='public')

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _main():
    args = sys.argv[1:]
    if not args:
        sys.stderr.write('❌ Error: Folder path is required\n')
        sys.stderr.write('Usage: python neuf_log_viewer_api.py <folderPath> [--scan-from <ts>] [--scan-to <ts>]\n')
        sys.exit(1)

    folder_arg = args[0]
    folder_path = os.path.realpath(os.path.abspath(folder_arg))

    # Parse optional --scan-from / --scan-to args
    scan_time_from = None
    scan_time_to   = None
    i = 1
    while i < len(args):
        if args[i] == '--scan-from' and i + 1 < len(args):
            scan_time_from = args[i + 1]
            i += 2
        elif args[i] == '--scan-to' and i + 1 < len(args):
            scan_time_to = args[i + 1]
            i += 2
        else:
            i += 1

    if not os.path.exists(folder_path):
        sys.stderr.write(f'❌ Error: Folder path does not exist: {folder_path}\n')
        sys.exit(1)

    if not os.path.isdir(folder_path):
        sys.stderr.write(f'❌ Error: Path is not a directory: {folder_path}\n')
        sys.exit(1)

    print(f'📁 Folder path: {folder_path}')

    log_service = NEUFLogService(logger=print, sql_logger=print)
    await log_service.initialize()

    print('\n🔍 Scanning logs...')
    try:
        scan_result = await log_service.scan_logs(folder_path,
                                                   scan_time_from=scan_time_from,
                                                   scan_time_to=scan_time_to)
    except Exception as scan_err:
        sys.stderr.write(f'\n❌ Failed to scan logs:\n{scan_err}\n')
        sys.exit(1)

    if scan_result.get('success'):
        data = scan_result.get('data', {})
        if not data.get('alreadyScanned'):
            print(f"✅ Scanned {data.get('totalLogs', 0)} log entries from {data.get('filesScanned', 0)} files")
    else:
        sys.stderr.write(f"❌ Failed to scan logs: {scan_result.get('error')}\n")
        sys.exit(1)

    # Print scan range warning on startup if applicable
    scan_meta = await log_service.get_db_scan_meta(folder_path)
    scan_meta_warning = NEUFLogService.build_scan_meta_warning(scan_meta)
    if scan_meta_warning:
        print(f'\n{scan_meta_warning}\n')

    base_port = int(os.environ.get('PORT', '3001'))
    max_attempts = 10

    app = create_app(folder_path=folder_path, log_service=log_service)

    print()
    print('╔════════════════════════════════════════╗')
    print('║   🚀 NEUF Log Viewer API v1.0 (Python) ║')
    print('╚════════════════════════════════════════╝')
    print()
    print(f'🌐 API Server running at http://localhost:{base_port}')
    print(f'📁 Folder path: {folder_path}')
    print()
    print('📋 Available endpoints:')
    print('  POST   /filter_log           - Filter logs')
    print('  POST   /filter_option         - Get filter options for a result table')
    print('  POST   /export_log           - Export filtered logs')
    print('  POST   /preset_suggestions   - Get preset filter suggestions')
    print('  GET    /health               - Health check')
    print('  GET    /                     - Frontend UI')
    print()
    print('Press Ctrl+C to stop the server')

    # Try successive ports
    for attempt in range(max_attempts):
        port = base_port + attempt
        try:
            config = uvicorn.Config(app, host='0.0.0.0', port=port, log_level='warning')
            server = uvicorn.Server(config)
            await server.serve()
            break
        except OSError:
            if attempt < max_attempts - 1:
                print(f'⚠️  Port {port} is in use, trying {port + 1}...')
            else:
                sys.stderr.write('❌ Could not find an available port.\n')
                sys.exit(1)


if __name__ == '__main__':
    import asyncio
    asyncio.run(_main())
