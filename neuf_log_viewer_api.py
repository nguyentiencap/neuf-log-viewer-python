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

import os
import sys
import traceback
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
    pageSize: int = 1000
    raw: bool = False


class ExportLogRequest(BaseModel):
    filters: Optional[Dict[str, Any]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    format: str = 'full'


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

            # Format logs (API layer responsibility)
            formatted_logs = [log_service.format_log_entry(log, 'full') for log in result.get('logs', [])]
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

            parsed_filters = parse_filters_from_request(raw_filters, log_service)
            await log_service.apply_preset(folder_path, parsed_filters)

            export_page_size = 5000
            first_result = await log_service.filter_logs(
                folder_path, parsed_filters, {'page': 1, 'pageSize': export_page_size}
            )

            # Collect all pages
            if fmt in ('json', 'csv'):
                exported = list(first_result.get('logs', []))
            else:
                exported = [log_service.format_log_entry(log, fmt) for log in first_result.get('logs', [])]

            total_pages = first_result.get('totalPages', 1)
            for page in range(2, total_pages + 1):
                page_result = await log_service.filter_logs(
                    folder_path, parsed_filters, {'page': page, 'pageSize': export_page_size}
                )
                if fmt in ('json', 'csv'):
                    exported.extend(page_result.get('logs', []))
                else:
                    exported.extend([
                        log_service.format_log_entry(log, fmt)
                        for log in page_result.get('logs', [])
                    ])

            ts = _export_timestamp()

            if fmt == 'json':
                filename = f'neuf-logs-export-{ts}-json.json'
                import json as _json
                content = _json.dumps(exported, indent=2, default=str)
                return Response(
                    content=content.encode('utf-8'),
                    media_type='application/json; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'},
                )

            elif fmt == 'csv':
                filename = f'neuf-logs-export-{ts}-csv.csv'
                lines = []
                if exported:
                    headers = ['filename', 'timestamp', 'log_level', 'thread', 'device', 'component', 'message']
                    lines.append(','.join(escape_csv_value(h) for h in headers))
                    for log in exported:
                        row = [
                            f'({log.get("filename", "")})',
                            log.get('timestamp', ''),
                            f'[{log.get("log_level", "")}]',
                            log.get('thread_name', ''),
                            f'<{log.get("device_id", "")}>',
                            f'({log.get("component_name", "")})',
                            log.get('message', ''),
                        ]
                        lines.append(','.join(escape_csv_value(v) for v in row))
                csv_content = '\n'.join(lines)
                return Response(
                    content=csv_content.encode('utf-8'),
                    media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'},
                )

            else:
                # 'full' or 'compact' — exported is a list of formatted log objects
                format_suffix = 'compact' if fmt == 'compact' else 'full'
                filename = f'neuf-logs-export-{ts}-{format_suffix}.log'
                lines = [log.get('formattedLog', '') if isinstance(log, dict) else str(log) for log in exported]
                text_content = '\n'.join(lines)
                return Response(
                    content=text_content.encode('utf-8'),
                    media_type='text/plain; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'},
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
