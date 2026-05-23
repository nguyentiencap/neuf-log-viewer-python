"""
Database Module (Python port of src/database.js)
Handles all database operations including wrapper, queries, and data retrieval.
Responsibility: Database abstraction and all SQL operations.
Note: Uses Python's built-in sqlite3 module instead of sql.js.
"""

import hashlib
import re
import sqlite3
import struct
import time

from .log_parser import log_parser_service

# Bump this value whenever the database schema changes.
# load_database will auto-clear any DB whose stored version differs.
DB_SCHEMA_VERSION = 3


def compute_hash_lo_hi(device_id, component_name, message):
    """
    Compute MD5 of (device_id + '\\0' + component_name + '\\0' + message).
    Returns (hash_lo, hash_hi) as two signed 64-bit integers (big-endian).
    Storing as two INT8 columns allows fast equality-join deduplication.
    """
    key = f"{device_id or ''}\x00{component_name or ''}\x00{message or ''}"
    digest = hashlib.md5(key.encode('utf-8')).digest()
    hash_lo = struct.unpack_from('>q', digest, 0)[0]
    hash_hi = struct.unpack_from('>q', digest, 8)[0]
    return hash_lo, hash_hi


class _Statement:
    """
    Statement-like wrapper returned by DatabaseWrapper.prepare().
    Mirrors the interface produced by the JS DatabaseWrapper.prepare() shim.
    """

    def __init__(self, wrapper, sql):
        self._wrapper = wrapper
        self._sql = sql

    def run(self, *params):
        self._wrapper.execute(self._sql, params)

    def get(self, *params):
        self._wrapper.db.row_factory = sqlite3.Row
        cur = self._wrapper.execute(self._sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def all(self, *params):
        self._wrapper.db.row_factory = sqlite3.Row
        cur = self._wrapper.execute(self._sql, params)
        return [dict(r) for r in cur.fetchall()]

    def each(self, callback, *params):
        self._wrapper.db.row_factory = sqlite3.Row
        cur = self._wrapper.execute(self._sql, params)
        for row in cur:
            callback(dict(row))


class DatabaseWrapper:
    """
    Database Wrapper Class.
    Wraps a sqlite3.Connection to mirror the JavaScript DatabaseWrapper API.
    """

    def __init__(self, db, sql_logger=None):
        self.db = db
        self.db.row_factory = sqlite3.Row
        self._sql_logger = sql_logger
        self._trace_enabled = sql_logger is not None

    def execute(self, sql, params=()):
        """Execute a single SQL statement, logging execution time when trace is enabled."""
        if self._trace_enabled and self._sql_logger is not None:
            t0 = time.perf_counter()
            result = self.db.execute(sql, params)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            self._sql_logger(f'[{elapsed_ms:.2f}ms] {sql.strip()}')
            return result
        return self.db.execute(sql, params)

    def disable_trace(self):
        """Temporarily disable SQL trace callback (e.g. during bulk inserts)."""
        self._trace_enabled = False

    def restore_trace(self):
        """Re-enable SQL trace callback after disable_trace()."""
        if self._sql_logger is not None:
            self._trace_enabled = True

    def exec(self, sql):
        """Execute one or more semicolon-separated SQL statements."""
        self.db.executescript(sql)

    def prepare(self, sql):
        """Return a statement-like object with run / get / all / each methods."""
        return _Statement(self, sql)

    def transaction(self, fn):
        """
        Wrap a function in a transaction.
        Returns callable(items) that runs fn(items) inside BEGIN/COMMIT.
        """
        def run(items):
            with self.db:   # sqlite3 context manager handles BEGIN/COMMIT/ROLLBACK
                fn(items)
        return run

    def register_function(self, name, fn):
        """Register a custom SQL scalar function."""
        # Determine arity from function signature
        import inspect
        try:
            sig = inspect.signature(fn)
            narg = len(sig.parameters)
        except (ValueError, TypeError):
            narg = -1
        self.db.create_function(name, narg, fn)

    def export(self):
        """Export database content as bytes."""
        import io
        buf = io.BytesIO()
        for chunk in self.db.iterdump():
            buf.write((chunk + '\n').encode())
        return buf.getvalue()


class DatabaseService:
    """
    Database Service.
    Encapsulates all database query helpers and schema management.
    Port of JavaScript DatabaseService in src/database.js.
    """

    def __init__(self, db, logger=print):
        """
        @param db: DatabaseWrapper instance
        @param logger: Callable logger
        """
        self.db = db
        self.logger = logger

    # ------------------------------------------------------------------ #
    #  WHERE clause builder                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _sql_literal(value):
        """Convert a Python value to a safe SQL literal for embedding in VIEW definitions."""
        if value is None:
            return 'NULL'
        if isinstance(value, bool):
            return '1' if value else '0'
        if isinstance(value, (int, float)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    def _build_literal_where(self, filters):
        """
        Build a WHERE clause string with literal values embedded (no ? placeholders).
        Used for CREATE TEMP VIEW where parameterized queries are not supported.
        """
        clause = self.build_where_clause(filters)
        where = clause['where']
        params = iter(clause['params'])
        return ''.join(
            self._sql_literal(next(params)) if ch == '?' else ch
            for ch in where
        )

    def build_where_clause(self, filters, exclude_field=None):
        """
        Build SQL WHERE clause string and parameter list from a filters dict.

        @param filters: Dict of filter key -> value/list
        @param exclude_field: Field name to skip (used when fetching options)
        @returns: Dict { 'where': str, 'params': list }
        """
        where = 'WHERE 1=1'
        params = []

        filename_include  = filters.get('filenameInclude', [])
        filename_exclude  = filters.get('filenameExclude', [])
        log_level_include = filters.get('logLevelInclude', [])
        log_level_exclude = filters.get('logLevelExclude', [])
        thread_include    = filters.get('threadInclude', [])
        thread_exclude    = filters.get('threadExclude', [])
        device_include    = filters.get('deviceInclude', [])
        device_exclude    = filters.get('deviceExclude', [])
        component_include = filters.get('componentInclude', [])
        component_exclude = filters.get('componentExclude', [])

        def is_like(v):
            return isinstance(v, str) and '%' in v

        def add_filter(field, db_col, inc_list, exc_list):
            nonlocal where
            if exclude_field == field:
                return

            # ---- include ----
            if inc_list:
                include_nulls = None in inc_list
                non_null_inc = [v for v in inc_list if v is not None]
                like_inc  = [v for v in non_null_inc if is_like(v)]
                exact_inc = [v for v in non_null_inc if not is_like(v)]

                parts = []
                if exact_inc:
                    placeholders = ','.join(['?' for _ in exact_inc])
                    parts.append(f'{db_col} IN ({placeholders})')
                    params.extend(exact_inc)
                for pat in like_inc:
                    parts.append(f'{db_col} LIKE ?')
                    params.append(pat)
                if include_nulls:
                    parts.append(f'{db_col} IS NULL')
                if parts:
                    where += f' AND ({" OR ".join(parts)})'

            # ---- exclude ----
            if exc_list:
                exclude_nulls = None in exc_list
                non_null_exc = [v for v in exc_list if v is not None]
                like_exc  = [v for v in non_null_exc if is_like(v)]
                exact_exc = [v for v in non_null_exc if not is_like(v)]

                if exact_exc and exclude_nulls:
                    placeholders = ','.join(['?' for _ in exact_exc])
                    where += (f' AND ({db_col} NOT IN ({placeholders})'
                              f' AND {db_col} IS NOT NULL)')
                    params.extend(exact_exc)
                elif exact_exc:
                    placeholders = ','.join(['?' for _ in exact_exc])
                    where += f' AND {db_col} NOT IN ({placeholders})'
                    params.extend(exact_exc)
                elif exclude_nulls:
                    where += f' AND {db_col} IS NOT NULL'

                if like_exc:
                    if len(like_exc) == 1:
                        if exclude_nulls:
                            where += f' AND {db_col} NOT LIKE ?'
                        else:
                            where += f' AND ({db_col} NOT LIKE ? OR {db_col} IS NULL)'
                        params.append(like_exc[0])
                    else:
                        not_like_parts = ' AND '.join(f'{db_col} NOT LIKE ?' for _ in like_exc)
                        if exclude_nulls:
                            where += f' AND ({not_like_parts})'
                        else:
                            where += f' AND ({db_col} IS NULL OR ({not_like_parts}))'
                        params.extend(like_exc)

        add_filter('filename',  'filename',       filename_include,  filename_exclude)
        add_filter('logLevel',  'log_level',      log_level_include, log_level_exclude)
        add_filter('thread',    'thread_name',    thread_include,    thread_exclude)
        add_filter('device',    'device_id',      device_include,    device_exclude)
        add_filter('component', 'component_name', component_include, component_exclude)

        # Time range
        if filters.get('timeFrom') is not None or filters.get('timeTo') is not None:
            time_from_unix = 0
            time_to_unix   = 2147483647

            if filters.get('timeFrom') is not None:
                tf = filters['timeFrom']
                if isinstance(tf, str):
                    tf = log_parser_service.get_time_bucket(tf)
                time_from_unix = tf if tf is not None else 0

            if filters.get('timeTo') is not None:
                tt = filters['timeTo']
                if isinstance(tt, str):
                    tt = log_parser_service.get_time_bucket(tt)
                time_to_unix = tt if tt is not None else 2147483647

            where += ' AND time_bucket BETWEEN ? AND ?'
            params.extend([time_from_unix, time_to_unix])

        # Search text: LIKE + REGEXP
        if filters.get('search'):
            if filters.get('searchRegex'):
                where += ' AND REGEXP(?, message)'
                params.append(filters['search'])
            else:
                where += ' AND (message LIKE ? OR REGEXP(?, message))'
                params.extend([f"%{filters['search']}%", filters['search']])

        return {'where': where, 'params': params}

    # ------------------------------------------------------------------ #
    #  Custom SQL functions                                                 #
    # ------------------------------------------------------------------ #

    def register_custom_functions(self):
        """Register REGEXP and BUCKET_LABEL custom SQL functions."""
        import datetime

        def regexp_fn(pattern, value):
            if value is None:
                return 0
            try:
                return 1 if re.search(pattern, value, re.IGNORECASE) else 0
            except re.error:
                return 0

        def bucket_label_fn(unix_ts):
            if unix_ts is None:
                return None
            d = datetime.datetime.utcfromtimestamp(unix_ts)
            return f'{d.year:04d}.{d.month:02d}.{d.day:02d} {d.hour:02d}:00'

        self.db.register_function('REGEXP', regexp_fn)
        self.db.register_function('BUCKET_LABEL', bucket_label_fn)

    def get_schema_version(self):
        """Return the stored schema version integer, or None if not present."""
        try:
            row = self.db.prepare(
                "SELECT value FROM schema_meta WHERE key = 'version'"
            ).get()
            return int(row['value']) if row else None
        except Exception:
            return None

    def save_scan_meta(self, scan_time_from, scan_time_to):
        """Persist scan time range into schema_meta. None values are stored as empty string."""
        self.db.prepare(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('scan_time_from', ?)"
        ).run(scan_time_from or '')
        self.db.prepare(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('scan_time_to', ?)"
        ).run(scan_time_to or '')

    def get_scan_meta(self):
        """Return scan time range metadata dict with keys scanTimeFrom/scanTimeTo (str or None)."""
        try:
            row_from = self.db.prepare(
                "SELECT value FROM schema_meta WHERE key = 'scan_time_from'"
            ).get()
            row_to = self.db.prepare(
                "SELECT value FROM schema_meta WHERE key = 'scan_time_to'"
            ).get()
            return {
                'scanTimeFrom': (row_from['value'] or None) if row_from else None,
                'scanTimeTo':   (row_to['value']   or None) if row_to   else None,
            }
        except Exception:
            return {'scanTimeFrom': None, 'scanTimeTo': None}

    # ------------------------------------------------------------------ #
    #  Schema management                                                    #
    # ------------------------------------------------------------------ #

    def init_database(self):
        """Create lookup tables, logs table, logs_view, and indexes."""
        self.register_custom_functions()
        # Enable auto_vacuum to automatically reclaim free pages on next VACUUM
        self.db.db.execute('PRAGMA auto_vacuum = FULL')
        self.db.exec("""
            CREATE TABLE IF NOT EXISTS files (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS threads (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS devices (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS components (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS log_levels (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS logs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                filename_id  INTEGER NOT NULL REFERENCES files(id),
                timestamp    TEXT    NOT NULL,
                thread_id    INTEGER NOT NULL REFERENCES threads(id),
                device_id    INTEGER          REFERENCES devices(id),
                component_id INTEGER          REFERENCES components(id),
                log_level_id INTEGER          REFERENCES log_levels(id),
                time_bucket  INTEGER,
                message      TEXT    NOT NULL,
                hash_lo      INTEGER,
                hash_hi      INTEGER
            );
            CREATE VIEW IF NOT EXISTS logs_view AS
                SELECT l.id,
                       f.filename,
                       l.timestamp,
                       t.name  AS thread_name,
                       d.name  AS device_id,
                       c.name  AS component_name,
                       ll.name AS log_level,
                       l.time_bucket,
                       l.message,
                       l.hash_lo,
                       l.hash_hi
                FROM logs l
                JOIN  files      f  ON f.id  = l.filename_id
                JOIN  threads    t  ON t.id  = l.thread_id
                LEFT JOIN devices    d  ON d.id  = l.device_id
                LEFT JOIN components c  ON c.id  = l.component_id
                LEFT JOIN log_levels ll ON ll.id = l.log_level_id;
            CREATE INDEX IF NOT EXISTS idx_filename_id  ON logs(filename_id);
            CREATE INDEX IF NOT EXISTS idx_thread_id    ON logs(thread_id);
            CREATE INDEX IF NOT EXISTS idx_device_id    ON logs(device_id);
            CREATE INDEX IF NOT EXISTS idx_component_id ON logs(component_id);
            CREATE INDEX IF NOT EXISTS idx_log_level_id ON logs(log_level_id);
            CREATE INDEX IF NOT EXISTS idx_time_bucket  ON logs(time_bucket);
            CREATE INDEX IF NOT EXISTS idx_hash         ON logs(hash_lo, hash_hi);
            CREATE TABLE IF NOT EXISTS schema_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('version', '3');
        """)

    # ------------------------------------------------------------------ #
    #  Filter options                                                       #
    # ------------------------------------------------------------------ #

    def get_filter_options(self, table_name='logs_view', limited_options=True):
        """Return grouped distinct values with counts for each filter field."""

        def get_opts(column, order_by, limit=None):
            limit_clause = f' LIMIT {limit}' if limit else ''
            sql = (f'SELECT {column}, COUNT(*) as count FROM {table_name}'
                   f' GROUP BY {column} ORDER BY {order_by}{limit_clause}')
            return self.db.prepare(sql).all()

        total_row = self.db.prepare(f'SELECT COUNT(*) as total FROM {table_name}').get()
        total_logs = total_row['total'] if total_row else 0

        def get_time_buckets():
            sql = f"""
                SELECT BUCKET_LABEL(time_bucket) as time_label, COUNT(*) as count
                FROM {table_name}
                WHERE time_bucket IS NOT NULL
                GROUP BY BUCKET_LABEL(time_bucket)
                ORDER BY time_label ASC
                LIMIT 100
            """
            return self.db.prepare(sql).all()

        thread_limit    = 20 if limited_options else None
        component_limit = 20 if limited_options else None

        return {
            'filenames':   get_opts('filename',       'filename ASC'),
            'timeBuckets': get_time_buckets(),
            'logLevels':   get_opts('log_level',      'log_level ASC'),
            'threads':     get_opts('thread_name',    'count DESC', thread_limit),
            'devices':     get_opts('device_id',      'count DESC'),
            'components':  get_opts('component_name', 'count DESC', component_limit),
            'totalLogs':   total_logs,
        }

    # ------------------------------------------------------------------ #
    #  Temp table for scan pipeline                                         #
    # ------------------------------------------------------------------ #

    def init_temp_logs_table(self):
        self.db.exec("""
            CREATE TABLE IF NOT EXISTS temp_parsed_logs (
                filename TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                thread_name TEXT NOT NULL,
                device_id TEXT,
                component_name TEXT,
                log_level TEXT,
                time_bucket INTEGER,
                message TEXT NOT NULL,
                hash_lo INTEGER,
                hash_hi INTEGER
            )
        """)

    def prepare_insert_temp(self):
        return self.db.prepare("""
            INSERT INTO temp_parsed_logs
                (filename, timestamp, thread_name, device_id, component_name,
                 log_level, time_bucket, message, hash_lo, hash_hi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)

    def create_batch_insert_temp(self, insert_stmt):
        return self.db.transaction(
            lambda logs: [
                insert_stmt.run(
                    log['filename'], log['timestamp'], log['threadName'],
                    log.get('deviceId'), log.get('componentName'),
                    log.get('logLevel'), log.get('timeBucket'), log['message'],
                    *compute_hash_lo_hi(
                        log.get('deviceId'), log.get('componentName'), log['message']
                    )
                )
                for log in logs
            ]
        )

    def insert_from_temp_to_logs(self):
        self.db.exec("""
            INSERT OR IGNORE INTO files(filename)
            SELECT DISTINCT filename FROM temp_parsed_logs;
            INSERT OR IGNORE INTO threads(name)
            SELECT DISTINCT thread_name FROM temp_parsed_logs;
            INSERT OR IGNORE INTO devices(name)
            SELECT DISTINCT device_id FROM temp_parsed_logs WHERE device_id IS NOT NULL;
            INSERT OR IGNORE INTO components(name)
            SELECT DISTINCT component_name FROM temp_parsed_logs WHERE component_name IS NOT NULL;
            INSERT OR IGNORE INTO log_levels(name)
            SELECT DISTINCT log_level FROM temp_parsed_logs WHERE log_level IS NOT NULL;
            INSERT INTO logs
                (filename_id, timestamp, thread_id, device_id, component_id,
                 log_level_id, time_bucket, message, hash_lo, hash_hi)
            SELECT f.id, tp.timestamp, t.id, d.id, c.id, ll.id,
                   tp.time_bucket, tp.message, tp.hash_lo, tp.hash_hi
            FROM temp_parsed_logs tp
            JOIN  files      f  ON f.filename = tp.filename
            JOIN  threads    t  ON t.name     = tp.thread_name
            LEFT JOIN devices    d  ON d.name = tp.device_id
            LEFT JOIN components c  ON c.name = tp.component_name
            LEFT JOIN log_levels ll ON ll.name = tp.log_level
            ORDER BY tp.timestamp ASC
        """)

    def drop_temp_logs_table(self):
        self.db.exec('DROP TABLE IF EXISTS temp_parsed_logs')
        # Reclaim pages freed by the temp table drop
        self.db.db.execute('VACUUM')

    # ------------------------------------------------------------------ #
    #  Filter pipeline                                                      #
    # ------------------------------------------------------------------ #

    def execute_filter_step(self, filters, input_table, output_table):
        """
        Materialize filtered rows from input_table into output_table.

        When contextLines is active, data is copied into a TEMP TABLE (required for
        the multi-step proximity expansion). Otherwise a lightweight TEMP VIEW is
        created so no data is copied at all.

        @param filters: Dict of filter parameters
        @param input_table: Source table name
        @param output_table: Destination temp table/view name
        @returns: Dict { 'count': int }
        """
        if input_table != output_table:
            needs_temp_table = bool(
                filters.get('search') and (filters.get('contextLines') or 0) > 0
            )

            if needs_temp_table:
                # Materialize into a temp table (context lines requires multi-step expansion)
                self.db.execute(f"""
                    CREATE TEMP TABLE IF NOT EXISTS {output_table} (
                        id INTEGER PRIMARY KEY,
                        filename TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        thread_name TEXT NOT NULL,
                        device_id TEXT,
                        component_name TEXT,
                        log_level TEXT,
                        time_bucket INTEGER,
                        message TEXT NOT NULL,
                        hash_lo INTEGER,
                        hash_hi INTEGER
                    )
                """)

                # Only populate if newly created (empty table means first time for this filter)
                existing_count = self.db.db.execute(
                    f'SELECT COUNT(*) FROM {output_table}'
                ).fetchone()[0]
                if existing_count == 0:
                    # Step 1: insert matching rows (all filters including search)
                    clause = self.build_where_clause(filters)
                    sql = (f'INSERT INTO {output_table} SELECT * FROM {input_table} '
                           f'{clause["where"]} ORDER BY timestamp ASC')
                    self.db.execute(sql, clause['params'])

                    # Step 2: context lines expansion
                    context_lines = filters['contextLines']

                    # Context rows matching all non-search filters, within ±N of any match
                    # Rewrite EXISTS so SQLite can use the PK index on output_table.id
                    # (m.id BETWEEN i.id-N AND i.id+N  vs  i.id BETWEEN m.id-N AND m.id+N).
                    # Also pre-filter i.id to the MIN/MAX range to avoid a full logs_view scan.
                    no_search_clause = self.build_where_clause({**filters, 'search': None})
                    self.db.execute(f"""
                        INSERT OR IGNORE INTO {output_table}
                        SELECT * FROM {input_table} i
                        {no_search_clause['where']}
                        AND i.id BETWEEN (SELECT MIN(id) FROM {output_table}) - ?
                                     AND (SELECT MAX(id) FROM {output_table}) + ?
                        AND EXISTS (
                            SELECT 1 FROM {output_table} m
                            WHERE m.id BETWEEN i.id - ? AND i.id + ?
                        )
                    """, no_search_clause['params'] + [context_lines, context_lines,
                                                       context_lines, context_lines])

                    # Step 3: any rows within ±N of current output (pure proximity, no filter)
                    if not filters.get('strictContext'):
                        self.db.execute(f"""
                            INSERT OR IGNORE INTO {output_table}
                            SELECT * FROM {input_table} i
                            WHERE i.id BETWEEN (SELECT MIN(id) FROM {output_table}) - ?
                                           AND (SELECT MAX(id) FROM {output_table}) + ?
                            AND EXISTS (
                                SELECT 1 FROM {output_table} m
                                WHERE m.id BETWEEN i.id - ? AND i.id + ?
                            )
                        """, [context_lines, context_lines, context_lines, context_lines])

            else:
                # Create a lightweight temp view — no data copy, filter runs at query time
                literal_where = self._build_literal_where(filters)
                self.db.execute(
                    f'CREATE TEMP VIEW IF NOT EXISTS {output_table} AS '
                    f'SELECT * FROM {input_table} {literal_where}'
                )

        self.db.db.row_factory = sqlite3.Row
        row = self.db.execute(
            f'SELECT COUNT(*) as count FROM {output_table}'
        ).fetchone()
        count = row['count'] if row else 0
        self.logger(f'executeFilterStep completed: {count} rows in {output_table}')
        return {'count': count}

    # ------------------------------------------------------------------ #
    #  Batch insert for main logs table                                     #
    # ------------------------------------------------------------------ #

    def prepare_insert(self):
        # Return lookup upsert statements + logs insert for create_batch_insert
        files_stmt      = self.db.prepare('INSERT OR IGNORE INTO files(filename) VALUES (?)')
        threads_stmt    = self.db.prepare('INSERT OR IGNORE INTO threads(name) VALUES (?)')
        devices_stmt    = self.db.prepare('INSERT OR IGNORE INTO devices(name) VALUES (?)')
        components_stmt = self.db.prepare('INSERT OR IGNORE INTO components(name) VALUES (?)')
        log_levels_stmt = self.db.prepare('INSERT OR IGNORE INTO log_levels(name) VALUES (?)')
        return (files_stmt, threads_stmt, devices_stmt, components_stmt, log_levels_stmt)

    def create_batch_insert(self, insert_stmt):
        files_stmt, threads_stmt, devices_stmt, components_stmt, log_levels_stmt = insert_stmt

        def _get_id(table, col, value):
            if value is None:
                return None
            row = self.db.execute(f'SELECT id FROM {table} WHERE {col} = ?', (value,)).fetchone()
            return row[0] if row else None

        def insert_many(logs):
            for log in logs:
                files_stmt.run(log['filename'])
                threads_stmt.run(log['threadName'])
                if log.get('deviceId'):
                    devices_stmt.run(log['deviceId'])
                if log.get('componentName'):
                    components_stmt.run(log['componentName'])
                if log.get('logLevel'):
                    log_levels_stmt.run(log['logLevel'])
                self.db.execute(
                    'INSERT INTO logs (filename_id, timestamp, thread_id, device_id, '
                    'component_id, log_level_id, time_bucket, message) VALUES (?,?,?,?,?,?,?,?)',
                    (
                        _get_id('files',      'filename', log['filename']),
                        log['timestamp'],
                        _get_id('threads',    'name', log['threadName']),
                        _get_id('devices',    'name', log.get('deviceId')),
                        _get_id('components', 'name', log.get('componentName')),
                        _get_id('log_levels', 'name', log.get('logLevel')),
                        log.get('timeBucket'),
                        log['message'],
                    )
                )
        return self.db.transaction(insert_many)
