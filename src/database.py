"""
Database Module (Python port of src/database.js)
Handles all database operations including wrapper, queries, and data retrieval.
Responsibility: Database abstraction and all SQL operations.
Note: Uses Python's built-in sqlite3 module instead of sql.js.
"""

import re
import sqlite3

from .log_parser import log_parser_service


class _Statement:
    """
    Statement-like wrapper returned by DatabaseWrapper.prepare().
    Mirrors the interface produced by the JS DatabaseWrapper.prepare() shim.
    """

    def __init__(self, conn, sql):
        self._conn = conn
        self._sql = sql

    def run(self, *params):
        self._conn.execute(self._sql, params)

    def get(self, *params):
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute(self._sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def all(self, *params):
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute(self._sql, params)
        return [dict(r) for r in cur.fetchall()]

    def each(self, callback, *params):
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.execute(self._sql, params)
        for row in cur:
            callback(dict(row))


class DatabaseWrapper:
    """
    Database Wrapper Class.
    Wraps a sqlite3.Connection to mirror the JavaScript DatabaseWrapper API.
    """

    def __init__(self, db):
        """
        @param db: sqlite3.Connection
        """
        self.db = db
        self.db.row_factory = sqlite3.Row

    def exec(self, sql):
        """Execute one or more semicolon-separated SQL statements."""
        self.db.executescript(sql)

    def prepare(self, sql):
        """Return a statement-like object with run / get / all / each methods."""
        return _Statement(self.db, sql)

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

    # ------------------------------------------------------------------ #
    #  Schema management                                                    #
    # ------------------------------------------------------------------ #

    def init_database(self):
        """Create logs table and indexes."""
        self.register_custom_functions()
        self.db.exec("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                thread_name TEXT NOT NULL,
                device_id TEXT,
                component_name TEXT,
                log_level TEXT,
                time_bucket INTEGER,
                message TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_filename ON logs(filename);
            CREATE INDEX IF NOT EXISTS idx_timestamp ON logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_thread_name ON logs(thread_name);
            CREATE INDEX IF NOT EXISTS idx_device_id ON logs(device_id);
            CREATE INDEX IF NOT EXISTS idx_component_name ON logs(component_name);
            CREATE INDEX IF NOT EXISTS idx_log_level ON logs(log_level);
            CREATE INDEX IF NOT EXISTS idx_time_bucket ON logs(time_bucket);
        """)

    # ------------------------------------------------------------------ #
    #  Filter options                                                       #
    # ------------------------------------------------------------------ #

    def get_filter_options(self, table_name='logs', limited_options=True):
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
                message TEXT NOT NULL
            )
        """)

    def prepare_insert_temp(self):
        return self.db.prepare("""
            INSERT INTO temp_parsed_logs
                (filename, timestamp, thread_name, device_id, component_name,
                 log_level, time_bucket, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """)

    def create_batch_insert_temp(self, insert_stmt):
        def insert_many(logs):
            for log in logs:
                insert_stmt.run(
                    log['filename'], log['timestamp'], log['threadName'],
                    log.get('deviceId'), log.get('componentName'),
                    log.get('logLevel'), log.get('timeBucket'), log['message']
                )
        return self.db.transaction(insert_many)

    def insert_from_temp_to_logs(self):
        self.db.exec("""
            INSERT INTO logs
                (filename, timestamp, thread_name, device_id, component_name,
                 log_level, time_bucket, message)
            SELECT filename, timestamp, thread_name, device_id, component_name,
                   log_level, time_bucket, message
            FROM temp_parsed_logs
            ORDER BY timestamp ASC
        """)

    def drop_temp_logs_table(self):
        self.db.exec('DROP TABLE IF EXISTS temp_parsed_logs')

    # ------------------------------------------------------------------ #
    #  Filter pipeline                                                      #
    # ------------------------------------------------------------------ #

    def execute_filter_step(self, filters, input_table, output_table):
        """
        Materialize filtered rows from input_table into output_table.

        @param filters: Dict of filter parameters
        @param input_table: Source table name
        @param output_table: Destination temp table name
        @returns: Dict { 'count': int }
        """
        conn = self.db.db

        if input_table != output_table:
            conn.execute(f'DROP TABLE IF EXISTS {output_table}')
            conn.execute(f"""
                CREATE TEMP TABLE {output_table} (
                    id INTEGER PRIMARY KEY,
                    filename TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    thread_name TEXT NOT NULL,
                    device_id TEXT,
                    component_name TEXT,
                    log_level TEXT,
                    time_bucket INTEGER,
                    message TEXT NOT NULL
                )
            """)

            # Step 1: insert matching rows (all filters including search)
            clause = self.build_where_clause(filters)
            sql = (f'INSERT INTO {output_table} SELECT * FROM {input_table} '
                   f'{clause["where"]} ORDER BY timestamp ASC')
            self.logger(sql)
            conn.execute(sql, clause['params'])

            # Step 2: context lines expansion
            if filters.get('search') and (filters.get('contextLines') or 0) > 0:
                context_lines = filters['contextLines']

                # Context rows matching all non-search filters, within ±N of any match
                no_search_clause = self.build_where_clause({**filters, 'search': None})
                conn.execute(f"""
                    INSERT OR IGNORE INTO {output_table}
                    SELECT * FROM {input_table} i
                    {no_search_clause['where']}
                    AND EXISTS (
                        SELECT 1 FROM {output_table} m
                        WHERE i.id BETWEEN m.id - ? AND m.id + ?
                    )
                """, no_search_clause['params'] + [context_lines, context_lines])

                # Step 3: any rows within ±N of current output (pure proximity, no filter)
                if not filters.get('strictContext'):
                    conn.execute(f"""
                        INSERT OR IGNORE INTO {output_table}
                        SELECT * FROM {input_table} i
                        WHERE EXISTS (
                            SELECT 1 FROM {output_table} m
                            WHERE i.id BETWEEN m.id - ? AND m.id + ?
                        )
                    """, [context_lines, context_lines])

        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f'SELECT COUNT(*) as count FROM {output_table}'
        ).fetchone()
        count = row['count'] if row else 0
        self.logger(f'executeFilterStep completed: {count} rows in {output_table}')
        return {'count': count}

    # ------------------------------------------------------------------ #
    #  Batch insert for main logs table                                     #
    # ------------------------------------------------------------------ #

    def prepare_insert(self):
        return self.db.prepare("""
            INSERT INTO logs
                (filename, timestamp, thread_name, device_id, component_name,
                 log_level, time_bucket, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """)

    def create_batch_insert(self, insert_stmt):
        def insert_many(logs):
            for log in logs:
                insert_stmt.run(
                    log['filename'], log['timestamp'], log['threadName'],
                    log.get('deviceId'), log.get('componentName'),
                    log.get('logLevel'), log.get('timeBucket'), log['message']
                )
        return self.db.transaction(insert_many)
