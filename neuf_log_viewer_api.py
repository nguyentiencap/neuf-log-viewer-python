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
    max_patterns: int = 50
    min_pattern_significance: int = 10


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
# Pattern post-processing helpers
# ---------------------------------------------------------------------------

def _message_fingerprint(pattern: dict) -> tuple:
    """
    Build a fingerprint from the pattern's block content that ignores
    timestamps.  Two patterns whose log messages (component + level +
    message text) are identical will get the same fingerprint even if
    they were recorded at different times.

    Used as a secondary deduplication key so that structurally-identical
    blocks that differ only in per-line timestamps are merged.
    """
    block_rows = pattern.get('block_rows') or []
    return tuple(
        (
            row.get('component_name') or '',
            row.get('log_level') or '',
            row.get('message') or '',
        )
        for row in block_rows
    )


def _deduplicate_patterns(patterns: list) -> list:
    """
    Merge patterns that represent the same structural repeat.

    Two-pass deduplication:
    1. Primary key  = _key_sequence (tuple of line fingerprints, exact match).
       Catches identical blocks at different log positions within the same run.
    2. Secondary key = message fingerprint (tuple of (component, level, message)
       per row, timestamps ignored).
       Catches blocks that are structurally identical but were recorded at
       different times — RE-PAIR treats each occurrence as a separate rule when
       per-line hashes differ due to timestamp inclusion.

    @param patterns: List of pattern dicts from _build_patterns_from_result.
    @returns: Deduplicated list; occurrences merged and sorted by line number.
    """
    def _merge_into(target: dict, source: dict) -> None:
        target['occurrences'].extend(source['occurrences'])
        target['occurrences'].sort(key=lambda o: o['line'])
        target['repeat_count'] = len(target['occurrences'])

    # --- Pass 1: exact key_sequence match ---
    seen_exact: dict = {}
    for p in patterns:
        key = p.get('_key_sequence', ())
        if key in seen_exact:
            _merge_into(seen_exact[key], p)
        else:
            seen_exact[key] = dict(p)
            seen_exact[key]['occurrences'] = list(p['occurrences'])

    # --- Pass 2: message-content fingerprint (timestamp-agnostic) ---
    # fp is already a tuple of tuples — directly usable as a dict key.
    seen_msg: dict = {}
    for p in seen_exact.values():
        # Skip synthetic combined patterns — their block_rows are artificial
        if p.get('_is_combined'):
            msg_key: object = id(p)   # unique per object → never merged
        else:
            fp = _message_fingerprint(p)
            msg_key = fp if fp else id(p)

        if msg_key in seen_msg:
            _merge_into(seen_msg[msg_key], p)
        else:
            seen_msg[msg_key] = p

    result = list(seen_msg.values())
    # Re-sort after merging (total wasted lines may have changed)
    result.sort(
        key=lambda p: p['repeat_count'] * p['pattern_length'],
        reverse=True,
    )
    return result


def _is_contiguous_subsequence(needle: tuple, haystack: tuple) -> bool:
    """
    Return True if *needle* appears as a contiguous sub-sequence inside *haystack*.

    Uses a simple sliding-window comparison — needle is short in practice
    (bounded by RE-PAIR's max rule expansion which is at most len(haystack)).
    """
    n, h = len(needle), len(haystack)
    if n == 0 or n >= h:
        return False
    for i in range(h - n + 1):
        if haystack[i: i + n] == needle:
            return True
    return False


def _filter_maximal_patterns(patterns: list) -> list:
    """
    Discard patterns whose key_sequence is a contiguous sub-sequence of
    any longer already-accepted pattern.

    RE-PAIR creates intermediate rules for every merging step
    (e.g. R1=(L1,L2), R2=(R1,L3), …, R73=(full 147-line block)).
    Only the maximal rule — the 147-line block — is meaningful to a human.
    All 72 shorter intermediate rules are dropped by this filter.

    Patterns are processed longest-first so that the maximal rule is always
    accepted before its constituent sub-rules are evaluated.

    @param patterns: List of pattern dicts, each with '_key_sequence'.
    @returns: Filtered list containing only maximal (non-dominated) patterns.
    """
    sorted_by_len = sorted(
        patterns,
        key=lambda p: p['pattern_length'],
        reverse=True,
    )
    accepted_keys: list = []
    maximal: list = []

    for p in sorted_by_len:
        seq = p.get('_key_sequence', ())
        dominated = any(
            _is_contiguous_subsequence(seq, ak)
            for ak in accepted_keys
        )
        if not dominated:
            maximal.append(p)
            accepted_keys.append(seq)

    # Restore original sort order (wasted lines DESC)
    maximal.sort(
        key=lambda p: p['repeat_count'] * p['pattern_length'],
        reverse=True,
    )
    return maximal


def _filter_by_significance(patterns: list, min_significance: int) -> list:
    """
    Keep only patterns whose total repeated-line count meets the threshold.

    Significance = repeat_count × pattern_length.
    E.g. min_significance=10 drops a 2-line pattern that repeats only 3×
    (score=6) while keeping a 5-line pattern repeating 3× (score=15).

    @param patterns:         List of pattern dicts.
    @param min_significance: Minimum score to retain a pattern.
    @returns: Filtered list.
    """
    if min_significance <= 0:
        return patterns
    return [
        p for p in patterns
        if p['repeat_count'] * p['pattern_length'] >= min_significance
    ]


_BLOCK_PREVIEW_LINES = 999  # max lines shown in block preview inside report (set high to show all)


def _log_elapsed(message: str, start_time: float) -> None:
    """Print message with elapsed time in milliseconds."""
    import time
    elapsed_ms = (time.time() - start_time) * 1000
    print(f'[EXPORT] {message} ({elapsed_ms:.0f}ms)', flush=True)


def _format_patterns_markdown(
    patterns: list,
    generated_at: str,
    raw_total: int = 0,
    max_patterns: int = 50,
) -> str:
    """
    Render the post-processed repeated-patterns list as a human-readable
    Markdown report.

    Layout
    ------
    1. Header with generation time, raw vs. filtered counts.
    2. Executive summary table (one row per pattern, sorted by wasted lines).
    3. Detail section — one sub-section per pattern, capped at *max_patterns*.
       Long blocks are shown as a preview (first N lines) + "… (M more lines)".

    @param patterns:      Post-processed pattern list (deduped + maximal-filtered).
    @param generated_at:  Human-readable timestamp string.
    @param raw_total:     Number of patterns before filtering (for transparency).
    @param max_patterns:  Cap on the number of patterns shown in full detail.
    """
    out: list = []
    displayed = patterns[:max_patterns]
    filtered_count = len(patterns)

    out.append('# NEUF Log — Repeated Patterns Report')
    out.append('')
    out.append(f'**Generated:** {generated_at}')
    if raw_total and raw_total != filtered_count:
        out.append(f'**Total raw patterns detected:** {raw_total}')
        out.append(f'**After deduplication and filtering:** {filtered_count} meaningful pattern{"s" if filtered_count != 1 else ""}')
    else:
        out.append(f'**Total patterns found:** {filtered_count}')
    if len(patterns) > max_patterns:
        out.append(f'**Showing top:** {max_patterns} of {filtered_count} (sorted by total wasted lines)')
    out.append('')
    out.append('---')
    out.append('')

    if not patterns:
        out.append('_No repeated patterns detected._')
        return '\n'.join(out)

    # -----------------------------------------------------------------------
    # Executive summary table
    # -----------------------------------------------------------------------
    out.append('## Executive Summary')
    out.append('')
    out.append('| Rank | Pattern # | Device | Component | Block Lines | Repeats | Total Wasted Lines |')
    out.append('|------|-----------|--------|-----------|-------------|---------|-------------------|')
    for rank, p in enumerate(displayed, 1):
        pattern_num = p.get('rule_id', rank - 1) + 1
        device    = p.get('device_id')     or '—'
        component = p.get('component_name') or '—'
        plen      = p.get('pattern_length', 1)
        count     = p.get('repeat_count', 0)
        wasted    = plen * count
        out.append(f'| {rank} | #{pattern_num} | `{device}` | `{component}` | {plen} | {count}× | {wasted:,} |')
    out.append('')
    out.append('---')
    out.append('')

    # -----------------------------------------------------------------------
    # Detail section
    # -----------------------------------------------------------------------
    out.append('## Pattern Details')
    out.append('')

    for rank, p in enumerate(displayed, 1):
        count       = p.get('repeat_count', 0)
        plen        = p.get('pattern_length', 1)
        wasted      = plen * count
        component   = p.get('component_name') or ''
        device      = p.get('device_id')     or ''
        level       = p.get('log_level')     or ''
        pattern_num = p.get('rule_id', rank - 1) + 1

        out.append(f'### Pattern #{pattern_num} (Rank {rank}) — {plen} line{"s" if plen != 1 else ""} × {count} repeat{"s" if count != 1 else ""} = {wasted:,} wasted lines')
        out.append('')

        if component:
            out.append(f'**Component:** `{component}`  ')
        if device:
            out.append(f'**Device:** `{device}`  ')
        if level:
            out.append(f'**Level:** `{level}`  ')
        out.append(f'**First seen:** {p.get("first_occurrence", "")}  ')
        out.append('')

        # Block preview
        block_lines = p.get('block_lines') or [p.get('message', '')]
        total_block = len(block_lines)
        preview = block_lines[:_BLOCK_PREVIEW_LINES]
        remaining = total_block - len(preview)

        if total_block == 1:
            label = 'Message'
        else:
            label = f'Block preview (first {len(preview)} of {total_block} lines)'
        out.append(f'**{label}:**')
        out.append('```')
        for line in preview:
            out.append(line)
        out.append('```')
        if remaining > 0:
            out.append(f'_… ({remaining} more line{"s" if remaining != 1 else ""})_')
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
            import time
            t_start = time.time()

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
            t_fetch = time.time()
            print('[EXPORT] Fetching logs...', flush=True)
            first_result = await log_service.filter_logs(
                folder_path, parsed_filters, {'page': 1, 'pageSize': export_page_size}
            )

            # Collect all pages (raw logs first, dedup applied across full dataset)
            all_raw_logs = list(first_result.get('logs', []))
            total_pages = first_result.get('totalPages', 1)
            if total_pages > 1:
                print(f'[EXPORT] Collected page 1/{total_pages} ({len(all_raw_logs)} logs)', flush=True)
            for page in range(2, total_pages + 1):
                page_result = await log_service.filter_logs(
                    folder_path, parsed_filters, {'page': page, 'pageSize': export_page_size}
                )
                all_raw_logs.extend(page_result.get('logs', []))
                print(f'[EXPORT] Collected page {page}/{total_pages} ({len(all_raw_logs)} logs)', flush=True)
            _log_elapsed(f'Fetched {len(all_raw_logs)} logs', t_fetch)

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
                t_build = time.time()
                print(f'[EXPORT] Building {fmt} format ({len(all_raw_logs)} logs)...', flush=True)
                filename, content, media_type = _build_export_content(all_raw_logs, fmt, ts)
                _log_elapsed(f'Done! Created {filename}', t_build)
                _log_elapsed(f'Total time', t_start)
                return Response(
                    content=content,
                    media_type=media_type,
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'},
                )
            else:
                # 1. Original format without deduplication
                t_orig = time.time()
                print(f'[EXPORT] Building original format ({len(all_raw_logs)} logs)...', flush=True)
                orig_filename, orig_content, _ = _build_export_content(all_raw_logs, fmt, ts, prefix='original')
                _log_elapsed('Original format done', t_orig)

                # 2. Deduped format & 3. Markdown pattern report (processed together)
                t_dedup = time.time()
                print('[EXPORT] Deduplicating and extracting patterns... (this may take a few minutes)', flush=True)
                deduped_logs, patterns = log_service.dedup_and_extract_patterns(all_raw_logs, dedup_mode)
                _log_elapsed(f'Found {len(patterns)} patterns, deduped to {len(deduped_logs)} logs', t_dedup)

                t_dedup_fmt = time.time()
                dedup_filename, dedup_content, _ = _build_export_content(deduped_logs, fmt, ts, prefix='dedup')
                _log_elapsed('Dedup format built', t_dedup_fmt)

                # Format block_lines for the report before post-processing
                # (block_rows are needed here; they are removed afterwards)
                for p in patterns:
                    raw_block = p.pop('block_rows', [])
                    block_formatted = [log_service.format_log_entry(row, 'full') for row in raw_block]
                    p['block_lines'] = [
                        f.get('formattedLog', '') if isinstance(f, dict) else str(f)
                        for f in block_formatted
                    ]

                # Post-processing pipeline: dedup → maximality filter → significance filter
                raw_pattern_count = len(patterns)
                max_patterns    = body.max_patterns
                min_significance = body.min_pattern_significance

                t_postproc = time.time()
                print('[EXPORT] Post-processing patterns...', flush=True)
                patterns = _deduplicate_patterns(patterns)
                patterns = _filter_maximal_patterns(patterns)
                patterns = _filter_by_significance(patterns, min_significance)
                _log_elapsed(f'After filtering: {len(patterns)}/{raw_pattern_count} patterns', t_postproc)

                t_md = time.time()
                print('[EXPORT] Building markdown report...', flush=True)
                generated_at = datetime.now().strftime('%Y.%m.%d %H:%M:%S')
                md_content = _format_patterns_markdown(
                    patterns,
                    generated_at,
                    raw_total=raw_pattern_count,
                    max_patterns=max_patterns,
                ).encode('utf-8')
                md_filename = f'neuf-logs-repeated-patterns-{ts}.md'
                _log_elapsed('Markdown report done', t_md)

                # Pack into a ZIP
                t_zip = time.time()
                print('[EXPORT] Packing files into ZIP...', flush=True)
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(orig_filename, orig_content)
                    zf.writestr(dedup_filename, dedup_content)
                    zf.writestr(md_filename, md_content)
                zip_buffer.seek(0)

                zip_filename = f'neuf-logs-export-{ts}.zip'
                _log_elapsed('ZIP packed', t_zip)
                _log_elapsed(f'Done! Created {zip_filename}', t_start)
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
        sys.stderr.write('[ERROR] Folder path is required\n')
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
        sys.stderr.write(f'[ERROR] Folder path does not exist: {folder_path}\n')
        sys.exit(1)

    if not os.path.isdir(folder_path):
        sys.stderr.write(f'[ERROR] Path is not a directory: {folder_path}\n')
        sys.exit(1)

    print(f'[INFO] Folder path: {folder_path}')

    log_service = NEUFLogService(logger=print, sql_logger=print)
    await log_service.initialize()

    print('\n[INFO] Scanning logs...')
    try:
        scan_result = await log_service.scan_logs(folder_path,
                                                   scan_time_from=scan_time_from,
                                                   scan_time_to=scan_time_to)
    except Exception as scan_err:
        sys.stderr.write(f'\n[ERROR] Failed to scan logs:\n{scan_err}\n')
        sys.exit(1)

    if scan_result.get('success'):
        data = scan_result.get('data', {})
        if not data.get('alreadyScanned'):
            print(f"[OK] Scanned {data.get('totalLogs', 0)} log entries from {data.get('filesScanned', 0)} files")
    else:
        sys.stderr.write(f"[ERROR] Failed to scan logs: {scan_result.get('error')}\n")
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
    print('========================================')
    print('   NEUF Log Viewer API v1.0 (Python)')
    print('========================================')
    print()
    print(f'[INFO] API Server running at http://localhost:{base_port}')
    print(f'[INFO] Folder path: {folder_path}')
    print()
    print('[INFO] Available endpoints:')
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
                print(f'[WARN] Port {port} is in use, trying {port + 1}...')
            else:
                sys.stderr.write('[ERROR] Could not find an available port.\n')
                sys.exit(1)


if __name__ == '__main__':
    import asyncio
    asyncio.run(_main())
