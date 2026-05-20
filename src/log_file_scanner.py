"""
Log File Scanner Module (Python port of src/log-file-scanner.js)
Handles scanning log directories and reading log files.
Responsibility: File system operations ONLY - NO DATABASE CODE.
"""

import os
import re


class LogFileScannerService:
    """
    Log File Scanner Service.
    Encapsulates all file scanning and parsing operations.
    Port of JavaScript LogFileScannerService in src/log-file-scanner.js.
    """

    _NEUF_FILE_RE = re.compile(r'^neuf-.*\.log', re.IGNORECASE)

    def __init__(self, parser_service, logger=print):
        """
        @param parser_service: LogParserService instance
        @param logger: Callable logger
        """
        self.parser_service = parser_service
        self.logger = logger

    def find_neuf_log_files(self, directory):
        """
        Find all NEUF log files in a directory (top level only, non-recursive).
        Files must match pattern: NEUF-*.log (case-insensitive).
        Returns sorted list of full absolute file paths.

        @param directory: Path to directory to scan
        @returns: Sorted list of absolute file paths
        """
        files = []
        try:
            for entry in os.scandir(directory):
                if entry.is_file() and self._NEUF_FILE_RE.match(entry.name):
                    files.append(entry.path)
        except OSError as e:
            self.logger(f'  Warning: Cannot read directory {directory}: {e}')
        return sorted(files)

    async def parse_files(self, log_folder_path, on_batch_ready, precomputed_files=None):
        """
        Scan all log files, parse each line, deliver batches via callback.

        @param log_folder_path: Path to log folder
        @param on_batch_ready: Callable(batch: list[dict])
        @param precomputed_files: Optional pre-computed file list
        @returns: Dict { 'totalEntries': int, 'fileStats': [...] }
        """
        self.logger(f'🔍 Scanning log folder: {log_folder_path}')

        log_files = precomputed_files if precomputed_files is not None else \
                    self.find_neuf_log_files(log_folder_path)

        if not log_files:
            self.logger('❌ No NEUF-*.log files found.')
            return {'totalEntries': 0, 'fileStats': []}

        self.logger(f'📁 Found {len(log_files)} log file(s):')
        for f in log_files:
            self.logger(f'  - {os.path.relpath(f, log_folder_path)}')
        self.logger('')

        batch_size    = 1000
        batch         = []
        total_lines   = 0
        total_entries = 0
        file_stats    = []

        for filepath in log_files:
            filename    = os.path.basename(filepath)
            file_lines  = 0
            file_entries = 0
            current_entry = None

            self.logger(f'📄 Processing: {os.path.relpath(filepath, log_folder_path)}...')

            with open(filepath, encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    line = line.rstrip('\n').rstrip('\r')
                    total_lines += 1
                    file_lines  += 1

                    line_start = self.parser_service.detect_log_line_start(line)

                    if line_start:
                        # Flush previous entry
                        if current_entry is not None:
                            raw = '\n'.join(current_entry['raw_parts'])
                            log_obj = self.parser_service.parse_line(
                                current_entry['timestamp'] + ' ' + raw,
                                current_entry['filename']
                            )
                            if log_obj is not None:
                                batch.append(log_obj)
                                total_entries  += 1
                                file_entries   += 1

                                if len(batch) >= batch_size:
                                    on_batch_ready(batch)
                                    batch = []

                        raw_content = line[len(line_start['timestamp']):].strip()
                        current_entry = {
                            'filename': filename,
                            'timestamp': line_start['timestamp'],
                            'raw_parts': [raw_content],
                        }
                    else:
                        if current_entry is not None:
                            current_entry['raw_parts'].append(line)

            # Flush last entry for this file
            if current_entry is not None:
                raw = '\n'.join(current_entry['raw_parts'])
                log_obj = self.parser_service.parse_line(
                    current_entry['timestamp'] + ' ' + raw,
                    current_entry['filename']
                )
                if log_obj is not None:
                    batch.append(log_obj)
                    total_entries  += 1
                    file_entries   += 1

            self.logger(f'  ✅ {file_lines} lines / {file_entries} entries.')
            file_stats.append({
                'filename': os.path.relpath(filepath, log_folder_path),
                'lines':    file_lines,
                'entries':  file_entries,
            })

        # Flush remaining batch
        if batch:
            on_batch_ready(batch)

        self.logger('')
        self.logger(
            f'✅ Scan complete! Total lines: {total_lines:,}, entries: {total_entries:,}'
        )
        self.logger('')

        return {'totalEntries': total_entries, 'fileStats': file_stats}
