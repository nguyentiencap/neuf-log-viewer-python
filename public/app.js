/**
 * NEUF Log Viewer - Client-Side Application (SSR-Style)
 * Pure JavaScript with jQuery for API calls
 */

(function() {
  'use strict';

  // Application state
  const state = {
    currentPage: 1,
    pageSize: 1000,
    totalPages: 1,
    total: 0,
    folderPath: './logs',
    filters: {},
    inputTable: null,
    filterOptions: {},
    presetSteps: new Map(),  // applied preset suggestions: id -> label
    activeFilterStep: 0,  // step number to query filter options from (0 = logs, N = filter_N)
    presetSuggestions: []  // cached suggestions loaded once on startup
  };

  // API base URL
  const API_BASE = '';

  // Initialize application
  $(document).ready(function() {
    initEventHandlers();
    checkHealth();
  });

  /**
   * Initialize event handlers
   */
  function initEventHandlers() {
    // Filter actions
    $('#applyFilterBtn').on('click', applyFilters);
    $('#clearFilterBtn').on('click', clearFilters);
    $('#exportLogBtn').on('click', exportLogs);

    // Show all checkbox
    $('#showAllCheckbox').on('change', function() {
      toggleLogTruncation();
    });

    // Time bucket checkboxes: auto-fill timeFrom/timeTo if empty
    $('#timeBucketCheckboxes').on('change', '.timeBucket-checkbox', function() {
      if (!$(this).is(':checked')) return;
      const bucketLabel = $(this).val();
      const bucketWithSeconds = normalizeTimeFilterInput(bucketLabel);
      if (!$('#timeFromFilter').val().trim()) {
        $('#timeFromFilter').val(bucketWithSeconds);
      }
      if (!$('#timeToFilter').val().trim()) {
        $('#timeToFilter').val(addOneHour(bucketWithSeconds));
      }
    });

    // Pagination
    $('#prevPageBtn').on('click', previousPage);
    $('#nextPageBtn').on('click', nextPage);
    $('#jumpPageBtn').on('click', jumpToPage);
    $('#jumpPageInput').on('keypress', function(e) {
      if (e.key === 'Enter') {
        jumpToPage();
      }
    });
  }

  /**
   * Export logs with current filters as a downloadable file.
   */
  function exportLogs() {
    const exportButton = $('#exportLogBtn');
    const requestFilters = buildRequestFilters();
    const exportFormat = $('#exportFormatSelect').val() || 'full';

    exportButton.prop('disabled', true).text('Exporting...');

    fetch(API_BASE + '/export_log', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ filters: requestFilters, format: exportFormat })
    })
      .then(function(response) {
        if (!response.ok) {
          return response.text().then(function(bodyText) {
            let errorPayload;
            try {
              errorPayload = JSON.parse(bodyText);
            } catch (parseError) {
              errorPayload = null;
            }

            const errorMessage = (errorPayload && errorPayload.error) || bodyText || 'Unknown error';
            throw new Error(errorMessage);
          });
        }

        const contentDisposition = response.headers.get('content-disposition') || '';
        const filenameMatch = contentDisposition.match(/filename="([^"]+)"/i);
        const filename = filenameMatch ? filenameMatch[1] : 'neuf-logs-export.log';

        return response.blob().then(function(blob) {
          return { blob: blob, filename: filename };
        });
      })
      .then(function(result) {
        const downloadUrl = window.URL.createObjectURL(result.blob);
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = result.filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(downloadUrl);
        showStatus('✅ Export logs completed', 'success');
      })
      .catch(function(error) {
        showStatus('❌ Failed to export logs: ' + error.message, 'error');
      })
      .finally(function() {
        exportButton.prop('disabled', false).text(' Export Logs');
      });
  }

  /**
   * Check API health and load initial data
   */
  function checkHealth() {
    $.ajax({
      url: API_BASE + '/health?folderPath=' + encodeURIComponent(state.folderPath),
      method: 'GET',
      success: function(response) {
        if (response.databaseScanned) {
          loadLogs();
          loadPresetSuggestions();
        } else {
          showStatus('⚠️ No database found. Please start the server with a log folder path.', 'warning');
          clearLogsDisplay();
        }
      },
      error: function() {
        showStatus('❌ Cannot connect to API server', 'error');
      }
    });
  }


  /**
   * Load preset suggestions once on startup, then re-render the preset panel.
   */
  function loadPresetSuggestions() {
    $.ajax({
      url: API_BASE + '/preset_suggestions',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({}),
      success: function(response) {
        state.presetSuggestions = response.success ? (response.suggestions || []) : [];
        renderPresetPanel();
      },
      error: function() {
        state.presetSuggestions = [];
      }
    });
  }

  /**
   * Single render entry point — called after any state update.
   * Handles all UI: filter options, preset panel, active filters.
   */
  function renderAll() {
    renderPresetPanel();
    renderFilterOptions();
    renderActiveFilters(state.presetSteps, state.filters, {
      onRemovePreset: withReload(removePresetStep),
      onRemoveArrayFilter: withReload(removeArrayFilter),
      onRemoveSearch: withReload(removeSearchFilter),
      onRemoveTimeRange: withReload(removeTimeRangeFilter)
    });
  }

  /**
   * Wrap a state-mutating function with page reset and log reload.
   * @param {Function} mutateFn - Function that mutates state
   * @returns {Function}
   */
  function withReload(mutateFn) {
    return function() {
      mutateFn.apply(null, arguments);
      state.currentPage = 1;
      loadLogs();
    };
  }

  /**
   * Render preset suggestions panel visibility and content.
   * Hides panel when total < 1000, no suggestions, or all already applied.
   */
  function renderPresetPanel() {
    const suggestions = state.presetSuggestions;

    if (state.total < 1000 || !suggestions || suggestions.length === 0) {
      $('#presetGroup').hide();
      return;
    }

    const visibleSuggestions = suggestions.filter(function(s) { return !state.presetSteps.has(s.id); });

    if (visibleSuggestions.length === 0) {
      $('#presetGroup').hide();
      return;
    }

    const container = $('#presetSuggestions');
    container.empty();

    visibleSuggestions.forEach(function(suggestion) {
      const btn = $('<button class="preset-btn" type="button"></button>');
      btn.attr('title', suggestion.description);
      btn.html('<span class="preset-btn-label">' + escapeHtml(suggestion.label) + '</span>' +
               '<span class="preset-btn-desc">' + escapeHtml(suggestion.description) + '</span>');
      btn.on('click', function() {
        withReload(applyPresetSuggestion)(suggestion);
      });
      container.append(btn);
    });

    $('#presetGroup').show();
  }

  /**
   * Apply a preset suggestion by sending its preset ID to the API
   * @param {Object} suggestion - Suggestion object with id and label
   */
  function applyPresetSuggestion(suggestion) {
    state.presetSteps.set(suggestion.id, suggestion.label);
  }

  /**
   * Render filter options
   */
  function renderFilterOptions() {
    const options = state.filterOptions;

    // Save checked values for all fields before re-rendering
    const allFields = [
      'filenameInclude', 'filenameExclude',
      'logLevelInclude', 'logLevelExclude',
      'deviceInclude', 'deviceExclude',
      'componentInclude', 'componentExclude',
      'threadInclude', 'threadExclude'
    ];
    const savedChecked = {};
    allFields.forEach(function(field) {
      savedChecked[field] = getSelectedValues(field);
    });

    // Render checkboxes for each filter type
    renderCheckboxes('timeBucket', options.timeBuckets || [], false); // Time: single column (auto-fill only)
    renderCheckboxes('filenameInclude', options.filenames || [], true);
    renderCheckboxes('filenameExclude', options.filenames || [], true);
    renderCheckboxes('logLevelInclude', options.logLevels || [], true);
    renderCheckboxes('logLevelExclude', options.logLevels || [], true);
    renderCheckboxes('deviceInclude', options.devices || [], true);
    renderCheckboxes('deviceExclude', options.devices || [], true);
    renderCheckboxes('componentInclude', options.components || [], true);
    renderCheckboxes('componentExclude', options.components || [], true);
    renderCheckboxes('threadInclude', options.threads || [], true);
    renderCheckboxes('threadExclude', options.threads || [], true);

    // Restore checked state after re-render
    allFields.forEach(function(field) {
      if (savedChecked[field].length === 0) return;
      savedChecked[field].forEach(function(value) {
        const checkboxValue = value === null ? '__NULL__' : String(value);
        $('.' + field + '-checkbox').each(function() {
          if ($(this).val() === checkboxValue) {
            $(this).prop('checked', true);
          }
        });
      });
      updateSelectAll(field);
    });

    // Show/hide advanced filters based on total logs
    const showAdvanced = options.totalLogs > 200;
    $('#componentFilterGroup').toggle(showAdvanced);
    $('#threadFilterGroup').toggle(showAdvanced);
  }


  /**
   * Get selected values from checkboxes
   * Converts "__NULL__" sentinel back to null
   */
  function getSelectedValues(fieldName) {
    const values = [];
    $('.' + fieldName + '-checkbox:checked').each(function() {
      const val = $(this).val();
      values.push(val === '__NULL__' ? null : val);
    });
    return values;
  }

  /**
   * Apply filters
   */
  function applyFilters() {
    state.currentPage = 1;
    
    // Build filters object
    const timeFromValue = normalizeTimeFilterInput($('#timeFromFilter').val());
    const timeToValue = normalizeTimeFilterInput($('#timeToFilter').val());
    const filenameIncludeValues = getSelectedValues('filenameInclude');
    const filenameExcludeValues = getSelectedValues('filenameExclude');
    const logLevelIncludeValues = getSelectedValues('logLevelInclude');
    const logLevelExcludeValues = getSelectedValues('logLevelExclude');
    const deviceIncludeValues = getSelectedValues('deviceInclude');
    const deviceExcludeValues = getSelectedValues('deviceExclude');
    const componentIncludeValues = getSelectedValues('componentInclude');
    const componentExcludeValues = getSelectedValues('componentExclude');
    const threadIncludeValues = getSelectedValues('threadInclude');
    const threadExcludeValues = getSelectedValues('threadExclude');

    state.filters = {
      search: $('#searchFilter').val(),
      contextLines: parseInt($('#contextLinesFilter').val()) || 0,
      strictContext: $('#strictContextFilter').is(':checked')
    };

    // Add time range if provided
    if (timeFromValue) {
      state.filters.timeFrom = timeFromValue;
    }
    if (timeToValue) {
      state.filters.timeTo = timeToValue;
    }

    // Add filters only if they have values
    if (filenameIncludeValues.length > 0) {
      state.filters.filenameInclude = filenameIncludeValues;
    }
    if (filenameExcludeValues.length > 0) {
      state.filters.filenameExclude = filenameExcludeValues;
    }
    if (logLevelIncludeValues.length > 0) {
      state.filters.logLevelInclude = logLevelIncludeValues;
    }
    if (logLevelExcludeValues.length > 0) {
      state.filters.logLevelExclude = logLevelExcludeValues;
    }
    if (deviceIncludeValues.length > 0) {
      state.filters.deviceInclude = deviceIncludeValues;
    }
    if (deviceExcludeValues.length > 0) {
      state.filters.deviceExclude = deviceExcludeValues;
    }
    if (componentIncludeValues.length > 0) {
      state.filters.componentInclude = componentIncludeValues;
    }
    if (componentExcludeValues.length > 0) {
      state.filters.componentExclude = componentExcludeValues;
    }
    if (threadIncludeValues.length > 0) {
      state.filters.threadInclude = threadIncludeValues;
    }
    if (threadExcludeValues.length > 0) {
      state.filters.threadExclude = threadExcludeValues;
    }

    loadLogs();
  }

  /**
   * Clear filter input fields (checkboxes are re-rendered by renderFilterOptions).
   */
  function clearFiltersUI() {
    $('#searchFilter').val('');
    $('#contextLinesFilter').val('0');
    $('#strictContextFilter').prop('checked', true);
    $('#timeFromFilter').val('');
    $('#timeToFilter').val('');
  }

  /**
   * Clear filters
   */
  function clearFilters() {
    state.filters = {};
    state.currentPage = 1;
    state.presetSteps = new Map();
    state.activeFilterStep = 0;
    state.inputTable = null;

    // Clear UI
    clearFiltersUI();

    loadLogs();
  }


  /**
   * Remove one value from an array filter and uncheck its checkbox.
   * @param {string} field - Filter field name
   * @param {*} value - Value to remove (null allowed)
   */
  function removeArrayFilter(field, value) {
    if (!state.filters[field]) return;
    state.filters[field] = state.filters[field].filter(function(v) { return v !== value; });
    if (state.filters[field].length === 0) {
      delete state.filters[field];
    }

    // Uncheck corresponding checkbox
    const checkboxValue = value === null ? '__NULL__' : String(value);
    $('.' + field + '-checkbox').each(function() {
      if ($(this).val() === checkboxValue) {
        $(this).prop('checked', false);
      }
    });
    updateSelectAll(field);
  }

  /**
   * Remove search filter.
   */
  function removeSearchFilter() {
    delete state.filters.search;
    $('#searchFilter').val('');
  }

  /**
   * Remove timeFrom or timeTo filter.
   * @param {string} field - 'timeFrom' or 'timeTo'
   */
  function removeTimeRangeFilter(field) {
    delete state.filters[field];
    if (field === 'timeFrom') $('#timeFromFilter').val('');
    if (field === 'timeTo') $('#timeToFilter').val('');
  }

  /**
   * Remove a preset step by id.
   * @param {string} id - Preset id to remove
   */
  function removePresetStep(id) {
    state.presetSteps.delete(id);
  }

  function loadLogs(pageOnly) {
    const requestFilters = buildRequestFilters();

    $.ajax({
      url: API_BASE + '/filter_log',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({
        filters: requestFilters,
        page: state.currentPage,
        pageSize: state.pageSize,
        inputTable: state.inputTable
      }),
      success: function(response) {
        console.log('[loadLogs] success, response.success=', response.success, 'pageOnly=', pageOnly, 'outputTable=', response.outputTable);
        if (response.success) {
          state.total = response.total;
          state.totalPages = response.totalPages;
          state.inputTable = response.outputTable || null;
          state.activeFilterStep = 1;
          renderLogs(response.logs);
          updatePagination();
          if (!pageOnly) {
            console.log('[loadLogs] calling loadFilterOptions with', state.inputTable);
            loadFilterOptions(state.inputTable);
          } else {
            renderAll();
          }
        } else {
          showStatus('❌ Failed to load logs: ' + response.error, 'error');
        }
      },
      error: function(xhr) {
        console.error('[loadLogs] error, status=', xhr.status, xhr.responseJSON);
        const error = xhr.responseJSON ? xhr.responseJSON.error : 'Unknown error';
        showStatus('❌ Failed to load logs: ' + error, 'error');
      }
    });
  }

  /**
   * Load filter options for the current output table.
   * @param {string|null} outputTable
   */
  function loadFilterOptions(outputTable) {
    $.ajax({
      url: API_BASE + '/filter_option',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ outputTable: outputTable || null }),
      success: function(response) {
        state.filterOptions = (response.success ? response.data : null) || {};
        renderAll();
      },
      error: function() {
        state.filterOptions = {};
        renderAll();
      }
    });
  }

  /**
   * Build API filters payload from current manual filters and preset chain.
   * @returns {Object} filters payload
   */
  function buildRequestFilters() {
    const requestFilters = Object.assign({}, state.filters);
    const presetIds = Array.from(state.presetSteps.keys()).filter(Boolean);

    if (presetIds.length > 0) {
      requestFilters.preset = presetIds;
    } else {
      delete requestFilters.preset;
    }

    return requestFilters;
  }


  /**
   * Render logs
   */
  function renderLogs(logs) {
    const container = $('#log-container');
    container.empty();

    if (!logs || logs.length === 0) {
      container.append('<div class="loading">No logs found with current filters.</div>');
      return;
    }

    // Get search term from filters
    const searchTerm = state.filters.search || '';

    // Render each log as a div with CSS class for log level
    logs.forEach(function(log) {
      // Use formattedLog from API if available, otherwise fallback to manual formatting
      const logLine = log.formattedLog || (log.timestamp + ' [' + log.log_level + '] ' + log.message);
      const displayLine = searchTerm ? highlightSearchTerm(logLine, searchTerm) : escapeHtml(logLine);
      const logDiv = $('<div class="log-entry ' + log.log_level + '"></div>');
      logDiv.html(displayLine);
      container.append(logDiv);
    });

    // Apply truncation to container based on checkbox state
    container.toggleClass('log-truncated', !$('#showAllCheckbox').is(':checked'));
  }

  /**
   * Clear logs display
   */
  function clearLogsDisplay() {
    $('#log-container').html('<div class="logs-placeholder">No logs loaded. Please start the server with a log folder path.</div>');
    $('#resultsInfo').text('Log from 0 to 0/0 logs');
    $('#pageInfo').text('Page 1/1');
    state.currentPage = 1;
    state.totalPages = 1;
    state.total = 0;
    updatePagination();
  }

  /**
   * Update pagination
   */
  function updatePagination() {
    const start = (state.currentPage - 1) * state.pageSize + 1;
    const end = Math.min(state.currentPage * state.pageSize, state.total);
    
    $('#pageInfo').text('Page ' + state.currentPage + '/' + state.totalPages);
    $('#resultsInfo').text('Log from ' + start.toLocaleString() + ' to ' + end.toLocaleString() + '/' + state.total.toLocaleString() + ' logs');
    $('#jumpPageInput').attr('max', state.totalPages);
    $('#jumpPageInput').val(state.currentPage);

    // Enable/disable buttons
    $('#prevPageBtn').prop('disabled', state.currentPage <= 1);
    $('#nextPageBtn').prop('disabled', state.currentPage >= state.totalPages);
  }

  /**
   * Previous page
   */
  function previousPage() {
    if (state.currentPage > 1) {
      state.currentPage--;
      loadLogs(true);
    }
  }

  /**
   * Next page
   */
  function nextPage() {
    if (state.currentPage < state.totalPages) {
      state.currentPage++;
      loadLogs(true);
    }
  }

  /**
   * Jump to page
   */
  function jumpToPage() {
    const targetPage = parseInt($('#jumpPageInput').val());
    
    if (targetPage >= 1 && targetPage <= state.totalPages) {
      state.currentPage = targetPage;
      loadLogs(true);
    } else {
      alert('Please enter a valid page number between 1 and ' + state.totalPages);
    }
  }



  /**
   * Normalize time filter input to second precision.
   * Accepts both "YYYY.MM.DD HH:mm" and "YYYY.MM.DD HH:mm:ss".
   * @param {string} value
   * @returns {string}
   */
  function normalizeTimeFilterInput(value) {
    const raw = (value || '').trim();
    if (!raw) return '';

    const minuteMatch = raw.match(/^(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2})$/);
    if (minuteMatch) {
      return minuteMatch[1] + ':00';
    }

    return raw;
  }

  /**
   * Add 1 hour to a date string in "YYYY.MM.DD HH:mm:ss" format.
   * @param {string} dateStr
   * @returns {string}
   */
  function addOneHour(dateStr) {
    const normalizedDateStr = normalizeTimeFilterInput(dateStr);
    const match = normalizedDateStr.match(/^(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2})$/);
    if (!match) return dateStr;
    const d = new Date(
      parseInt(match[1]), parseInt(match[2]) - 1, parseInt(match[3]),
      parseInt(match[4]), parseInt(match[5]), parseInt(match[6])
    );
    d.setHours(d.getHours() + 1);
    const pad = function(n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + '.' + pad(d.getMonth() + 1) + '.' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

})();
