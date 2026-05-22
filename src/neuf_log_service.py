"""
NEUF Log Service Module (Python port of src/neuf-log-service.js)
Business logic for log operations (scan, clear, filter, get options).
Responsibility: Core log operations — can be used by API, CLI, or any interface.
"""

import hashlib
import json
import os
import re
import sqlite3

from .log_parser import default_log_parser_service
from .log_file_scanner import LogFileScannerService
from .database import DatabaseWrapper, DatabaseService, DB_SCHEMA_VERSION
from .preset import PresetService


class NEUFLogService:
    """
    NEUF Log Service.
    Orchestrates scan, filter, preset, and output operations.
    Port of JavaScript NEUFLogService in src/neuf-log-service.js.
    """

    # Shared caches mirror JS static fields
    _sql = None          # not actually needed; Python uses sqlite3 natively
    _db_cache = {}

    def __init__(self, logger=print, sql_logger=None):
        self.parser_service  = default_log_parser_service
        self.logger          = logger
        self.sql_logger      = sql_logger
        self.scanner_service = LogFileScannerService(default_log_parser_service, logger)

    # ------------------------------------------------------------------ #
    #  SQL engine lifecycle (kept for API compatibility)                    #
    # ------------------------------------------------------------------ #

    async def initialize(self):
        """Backward-compatible instance method."""
        return await NEUFLogService.initialize_sql_js()

    @staticmethod
    async def initialize_sql_js():
        """
        In Python we use the built-in sqlite3 module — no async init needed.
        Returns a simple namespace that has a Database factory.
        """
        class _SQLiteNS:
            @staticmethod
            def Database():
                return sqlite3.connect(':memory:')
        return _SQLiteNS()

    async def get_sql(self):
        return await NEUFLogService.initialize_sql_js()

    # ------------------------------------------------------------------ #
    #  Path and cache helpers                                               #
    # ------------------------------------------------------------------ #

    def get_db_path(self, folder_path):
        """Resolve database-related paths for a given log folder."""
        log_folder_path = os.path.realpath(os.path.abspath(folder_path))
        db_dir  = os.path.join(log_folder_path, 'log-filter-db')
        db_path = os.path.join(db_dir, 'neuf-logs.db')
        return {'logFolderPath': log_folder_path, 'dbDir': db_dir, 'dbPath': db_path}

    def _get_resolved_path(self, folder_path):
        return os.path.realpath(os.path.abspath(folder_path))

    def _invalidate_folder_caches(self, folder_path):
        resolved = self._get_resolved_path(folder_path)
        NEUFLogService._db_cache.pop(resolved, None)

    def normalize_filters(self, filters):
        """Normalize filters object — ensure arrays, remove empty values."""
        array_fields = [
            'filenameInclude', 'filenameExclude',
            'logLevelInclude', 'logLevelExclude',
            'threadInclude', 'threadExclude',
            'deviceInclude', 'deviceExclude',
            'componentInclude', 'componentExclude',
        ]
        for key in array_fields:
            if key in filters and not isinstance(filters[key], list):
                filters[key] = [filters[key]]
            if isinstance(filters.get(key), list) and len(filters[key]) == 0:
                del filters[key]

        if not filters.get('search'):
            filters.pop('search', None)
        if not filters.get('timeFrom'):
            filters.pop('timeFrom', None)
        if not filters.get('timeTo'):
            filters.pop('timeTo', None)

        return filters

    def is_database_scanned(self, folder_path):
        """Check whether neuf-logs.db exists for a folder."""
        try:
            return os.path.exists(self.get_db_path(folder_path)['dbPath'])
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #  Database lifecycle                                                   #
    # ------------------------------------------------------------------ #

    def _create_database_service(self, sql_db, sql_logger=None):
        """Build DatabaseWrapper + DatabaseService pair from a raw sqlite3 connection."""
        db = DatabaseWrapper(sql_db, sql_logger)
        svc = DatabaseService(db, self.logger)
        svc.register_custom_functions()
        return {'db': db, 'databaseService': svc}

    async def load_database(self, folder_path):
        """Load database file for a folder; result is cached."""
        paths     = self.get_db_path(folder_path)
        db_path   = paths['dbPath']
        resolved  = self._get_resolved_path(folder_path)

        if resolved in NEUFLogService._db_cache:
            return NEUFLogService._db_cache[resolved]

        if not os.path.exists(db_path):
            raise Exception('Database not found. Please scan logs first.')

        # Verify schema version before loading into memory to avoid wasted work
        file_conn = sqlite3.connect(db_path)
        stored_version = self._create_database_service(file_conn)['databaseService'].get_schema_version()
        file_conn.close()
        if stored_version != DB_SCHEMA_VERSION:
            os.unlink(db_path)
            self.logger(
                f'⚠️  Schema mismatch (stored v{stored_version}, expected v{DB_SCHEMA_VERSION}). '
                f'Database cleared: {db_path}'
            )
            raise Exception(
                f'Database schema outdated (v{stored_version} → v{DB_SCHEMA_VERSION}). '
                f'Please re-scan logs.'
            )

        # Load file DB entirely into memory for faster queries
        file_conn = sqlite3.connect(db_path)
        conn = sqlite3.connect(':memory:')
        file_conn.backup(conn)
        file_conn.close()
        # Enable sql_logger only on the query-time connection
        result = self._create_database_service(conn, self.sql_logger)
        result['dbPath'] = db_path
        # Attach scan time range metadata so callers can surface it to users
        result['scanMeta'] = result['databaseService'].get_scan_meta()

        NEUFLogService._db_cache[resolved] = result
        return result

    async def get_db_scan_meta(self, folder_path):
        """Return scan meta dict {scanTimeFrom, scanTimeTo} for an existing database, or all None."""
        try:
            cached = await self.load_database(folder_path)
            return cached.get('scanMeta', {'scanTimeFrom': None, 'scanTimeTo': None})
        except Exception:
            return {'scanTimeFrom': None, 'scanTimeTo': None}

    @staticmethod
    def build_scan_meta_warning(scan_meta):
        """Build a user-facing warning string from scan meta dict, or None if no restriction."""
        time_from = scan_meta.get('scanTimeFrom')
        time_to   = scan_meta.get('scanTimeTo')
        if not time_from and not time_to:
            return None
        if time_from and time_to:
            range_str = f'from {time_from} to {time_to}'
        elif time_from:
            range_str = f'from {time_from} onwards'
        else:
            range_str = f'up to {time_to}'
        return (
            f'⚠️  This database only contains logs {range_str}. '
            f'To include more logs, delete the database and re-scan.'
        )

    def _create_already_scanned_result(self, db_path, log_folder_path):
        return {
            'success': True,
            'message': 'Database already exists. Use clear command to re-scan.',
            'data': {
                'dbPath': db_path,
                'logFolderPath': log_folder_path,
                'alreadyScanned': True,
                'totalLogs': 0,
                'filesScanned': 0,
            }
        }

    def _save_database_to_file(self, db, db_dir, db_path):
        """Persist in-memory sqlite3 database to disk."""
        os.makedirs(db_dir, exist_ok=True)
        # Backup in-memory DB to the file path
        disk_conn = sqlite3.connect(db_path)
        db.db.backup(disk_conn)
        disk_conn.close()
        self.logger(f'💾 Database saved to {db_path}')

    def _get_expected_format_help_text(self):
        return (
            '\nExpected log format (each line):\n'
            '  YYYY.MM.DD HH:mm:ss.SSS [LEVEL] ThreadName: Message\n'
            '  YYYY.MM.DD HH:mm:ss.SSS [LEVEL] class ClassName: ThreadName: Message\n'
            '  YYYY.MM.DD HH:mm:ss.SSS [LEVEL] class ClassName: ThreadName: '
            '<DeviceID> (com.example.component) Message\n'
            '\nExample:\n'
            '  2024.01.15 10:30:45.123 [INFO] main: Application started\n'
            '  2024.01.15 10:30:45.123 [INFO] class com.example.Main: main: Application started\n'
            '  2024.01.15 10:30:46.456 [DEBUG] class com.example.Worker: worker-1: '
            '<device-001> (com.example.app) Initializing'
        )

    def _clear_db_file(self, db_path, folder_path):
        """Delete a stale DB file and invalidate folder caches."""
        self._invalidate_folder_caches(folder_path)
        if os.path.exists(db_path):
            os.unlink(db_path)
            self.logger(f'🗑️  Removed empty database: {db_path}')

    async def scan_logs(self, folder_path, scan_time_from=None, scan_time_to=None):
        """Scan NEUF-*.log files and create indexed SQLite database.

        @param scan_time_from: Optional timestamp string (YYYY.MM.DD HH:mm:ss) — skip entries before
        @param scan_time_to:   Optional timestamp string (YYYY.MM.DD HH:mm:ss) — skip entries after
        """
        paths = self.get_db_path(folder_path)
        log_folder_path = paths['logFolderPath']
        db_path         = paths['dbPath']
        db_dir          = paths['dbDir']

        self._invalidate_folder_caches(folder_path)

        # Return early if DB already exists and schema version matches
        if os.path.exists(db_path):
            try:
                file_conn = sqlite3.connect(db_path)
                stored_version = self._create_database_service(file_conn)['databaseService'].get_schema_version()
                file_conn.close()
            except Exception:
                stored_version = None

            if stored_version == DB_SCHEMA_VERSION:
                self.logger('⚠️  Database already exists. Skipping scan.')
                return self._create_already_scanned_result(db_path, log_folder_path)
            else:
                self.logger(
                    f'⚠️  Schema mismatch (stored v{stored_version}, expected v{DB_SCHEMA_VERSION}). '
                    f'Re-scanning: {db_path}'
                )
                os.unlink(db_path)
                self._invalidate_folder_caches(folder_path)
                # Fall through to full re-scan

        self.logger('📊 Scanning and indexing logs...')

        # Log scan time range if specified
        if scan_time_from or scan_time_to:
            range_parts = []
            if scan_time_from:
                range_parts.append(f'from {scan_time_from}')
            if scan_time_to:
                range_parts.append(f'to {scan_time_to}')
            self.logger(f'⏰ Scan time range: {", ".join(range_parts)}')

        # Convert time range strings to unix timestamps for scanner filtering
        scan_time_from_unix = self.parser_service.get_time_bucket(scan_time_from) if scan_time_from else None
        scan_time_to_unix   = self.parser_service.get_time_bucket(scan_time_to)   if scan_time_to   else None

        # Fail fast if no log files
        log_files = self.scanner_service.find_neuf_log_files(log_folder_path)
        files_scanned = len(log_files)

        if files_scanned == 0:
            raise Exception(
                f'No NEUF log files found in: {log_folder_path}\n'
                f'\nLog files must be named NEUF-*.log '
                f'(e.g. NEUF-device.log, NEUF-app-2024.log).\n'
                + self._get_expected_format_help_text()
            )

        # Use an in-memory SQLite database during scan
        conn = sqlite3.connect(':memory:')
        result = self._create_database_service(conn)
        db              = result['db']
        database_service = result['databaseService']

        # Scan all files → temp table → main logs
        database_service.init_temp_logs_table()
        insert_temp     = database_service.prepare_insert_temp()
        insert_many_temp = database_service.create_batch_insert_temp(insert_temp)

        parse_result = await self.scanner_service.parse_files(
            log_folder_path,
            lambda batch: insert_many_temp(batch),
            log_files,
            scan_time_from=scan_time_from_unix,
            scan_time_to=scan_time_to_unix,
        )
        total_logs  = parse_result['totalEntries']
        file_stats  = parse_result.get('fileStats', [])

        if total_logs == 0:
            self._invalidate_folder_caches(folder_path)
            if os.path.exists(db_path):
                os.unlink(db_path)
                self.logger(f'🗑️  Removed empty database: {db_path}')

            file_details = '\n'.join(
                f"    - {s['filename']}: {s['lines']} lines, {s['entries']} entries"
                for s in file_stats
            )
            raise Exception(
                f'Found {files_scanned} NEUF-*.log file(s) in {log_folder_path} '
                f'but could not parse any log entries.\n'
                f'\nFile details:\n{file_details}\n'
                f'\nPlease check that the log files use the correct format.\n'
                + self._get_expected_format_help_text()
            )

        database_service.init_database()
        database_service.insert_from_temp_to_logs()
        database_service.drop_temp_logs_table()
        self.logger(f'✅ Inserted {total_logs:,} entries into logs table.')

        # Save scan time range metadata so users can detect a partial-range DB
        if scan_time_from or scan_time_to:
            database_service.save_scan_meta(scan_time_from, scan_time_to)

        os.makedirs(db_dir, exist_ok=True)

        # Generate and save preset snapshot
        presets_path = PresetService.get_presets_path(db_dir)
        presets      = self._generate_install_presets(database_service)
        count = len(presets)
        self.logger(f'Generated {count} install presets.')
        PresetService.save_preset(presets_path, presets, self.logger)

        self._save_database_to_file(db, db_dir, db_path)

        return {
            'success': True,
            'data': {
                'totalLogs':    total_logs,
                'filesScanned': files_scanned,
                'dbPath':       db_path,
            }
        }

    def clear_database(self, folder_path):
        """Delete neuf-logs.db and invalidate caches."""
        paths   = self.get_db_path(folder_path)
        db_path = paths['dbPath']

        self._invalidate_folder_caches(folder_path)

        if not os.path.exists(db_path):
            return {
                'success': True,
                'message': 'Database does not exist. Nothing to clear.',
                'dbPath':  db_path,
            }

        os.unlink(db_path)
        self.logger(f'🗑️  Database deleted: {db_path}')
        return {
            'success': True,
            'message': 'Database cleared successfully.',
            'dbPath':  db_path,
        }

    # ------------------------------------------------------------------ #
    #  Filter pipeline                                                      #
    # ------------------------------------------------------------------ #

    _ARRAY_FILTER_KEYS = [
        'filenameInclude', 'filenameExclude',
        'logLevelInclude', 'logLevelExclude',
        'threadInclude',   'threadExclude',
        'deviceInclude',   'deviceExclude',
        'componentInclude','componentExclude',
    ]

    def _has_active_filters(self, filters):
        """Return True if any meaningful filter is present."""
        if not filters:
            return False
        if filters.get('preset'):
            return True
        if filters.get('search'):
            return True
        if filters.get('timeFrom') is not None or filters.get('timeTo') is not None:
            return True
        for key in self._ARRAY_FILTER_KEYS:
            if filters.get(key):
                return True
        return False

    def _get_filter_output_table(self, normalized_filters):
        filters_key = json.dumps(normalized_filters, sort_keys=True)
        h = hashlib.md5(filters_key.encode()).hexdigest()
        return f'filter_{h}'


    def _is_valid_table(self, input_table):
        return bool(isinstance(input_table, str)
                    and re.match(r'^filter_[a-f0-9]{32}$', input_table))

    def _get_paging_options(self, options=None):
        options = options or {}
        return {
            'page':     options.get('page', 1),
            'pageSize': options.get('pageSize', 1000),
        }

    def _get_output_table_count(self, database_service, output_table):
        row = database_service.db.db.execute(
            f'SELECT COUNT(*) as count FROM {output_table}'
        ).fetchone()
        if row is None:
            return 0
        if isinstance(row, sqlite3.Row):
            return row['count']
        return row[0]

    async def filter_logs(self, folder_path, filters, options=None):
        """Apply filters and return a paginated page of log rows."""
        cached = await self.load_database(folder_path)
        database_service = cached['databaseService']

        paging        = self._get_paging_options(options)
        page          = paging['page']
        page_size     = paging['pageSize']
        norm_filters  = filters or {}
        source_table  = 'logs_view'

        self.logger(
            f'🔍 Filtering logs with page: {page}, pageSize: {page_size}, '
            f'sourceTable: {source_table}, filtersKey: {json.dumps(norm_filters)}'
        )

        if self._has_active_filters(norm_filters):
            output_table = self._get_filter_output_table(norm_filters)
            database_service.execute_filter_step(norm_filters, source_table, output_table)
        else:
            # No filters active — read directly from logs, skip temp table
            output_table = source_table
        total  = self._get_output_table_count(database_service, output_table)
        offset = (page - 1) * page_size

        database_service.db.db.row_factory = sqlite3.Row
        rows = database_service.db.db.execute(
            f'SELECT * FROM {output_table} ORDER BY timestamp ASC LIMIT ? OFFSET ?',
            (page_size, offset)
        ).fetchall()
        logs = [dict(r) for r in rows]

        return {
            'success':    True,
            'total':      total,
            'page':       page,
            'pageSize':   page_size,
            'totalPages': max(1, -(-total // page_size)),  # ceiling division
            'outputTable': output_table,
            'logs':       logs,
        }

    async def apply_preset(self, folder_path, filters):
        """Mutate filters dict by applying preset IDs it contains."""
        if not filters or not filters.get('preset'):
            return
        paths = self.get_db_path(folder_path)
        presets = PresetService.load_preset(paths['dbDir'], self.logger)
        PresetService.apply_preset(filters, presets, self.logger)

    async def get_preset_suggestions(self, folder_path):
        """Return all available preset suggestions."""
        self.logger('💡 Getting preset suggestions')
        paths   = self.get_db_path(folder_path)
        presets = PresetService.load_preset(paths['dbDir'], self.logger)
        client  = [
            {'id': p['id'], 'label': p['label'], 'description': p['description']}
            for p in presets.values()
        ]
        return {'success': True, 'suggestions': client}

    async def get_filter_options(self, folder_path, input_table=None, limited_options=True):
        """Return available filter option values."""
        cached           = await self.load_database(folder_path)
        database_service = cached['databaseService']

        source_table = input_table if self._is_valid_table(input_table) else 'logs_view'
        self.logger(
            f'📋 Getting filter options, sourceTable: {source_table}, '
            f'limitedOptions: {limited_options}'
        )

        filter_options = database_service.get_filter_options(source_table, limited_options)
        return {'success': True, 'data': filter_options}

    # ------------------------------------------------------------------ #
    #  Install presets                                                      #
    # ------------------------------------------------------------------ #

    def _generate_install_presets(self, database_service):
        """Query LifecycleProvider install events and generate install presets."""
        conn = database_service.db.db
        conn.row_factory = sqlite3.Row
        install_logs = conn.execute(
            "SELECT device_id, timestamp FROM logs_view "
            "WHERE component_name LIKE '%LifecycleProvider' "
            "AND message LIKE 'Fujifilm dws:install%' "
            "ORDER BY device_id, timestamp ASC"
        ).fetchall()
        install_logs = [dict(r) for r in install_logs]

        if not install_logs:
            self.logger('ℹ️  No LifecycleProvider install events found.')
            return {}

        self.logger(f'🔍 Found {len(install_logs)} LifecycleProvider install events.')
        return PresetService.create_install_presets(install_logs)

    async def create_install_preset(self, folder_path):
        """Create install presets from LifecycleProvider events, save to disk."""
        paths = self.get_db_path(folder_path)
        cached = await self.load_database(folder_path)

        self.logger('📦 Creating install presets from LifecycleProvider events...')

        install_presets = self._generate_install_presets(cached['databaseService'])

        presets_path      = PresetService.get_presets_path(paths['dbDir'])
        existing_presets  = PresetService.load_preset_file(presets_path, self.logger) or {}
        merged            = {**existing_presets, **install_presets}
        PresetService.save_preset(presets_path, merged, self.logger)

        count = len(install_presets)
        self.logger(f'💡 Created {count} install presets.')
        return {'success': True, 'count': count}

    # ------------------------------------------------------------------ #
    #  Output formatting                                                    #
    # ------------------------------------------------------------------ #

    def format_log_entry(self, log, format_type):
        """Delegate log row formatting to the parser service."""
        return self.parser_service.format_log_entry(log, format_type)
