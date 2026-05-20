/**
 * NEUF Log Viewer - Client-Side Helper Utilities
 * Pure utility functions with no dependency on application state.
 */

'use strict';

/**
 * Escape HTML special characters
 * @param {string|null} text
 * @returns {string}
 */
function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Highlight search term in text.
 * Tries to use searchTerm as a regex pattern first; falls back to literal text match.
 * @param {string} text
 * @param {string} searchTerm
 * @returns {string} HTML string with highlights
 */
function highlightSearchTerm(text, searchTerm) {
  if (!searchTerm || !text) return escapeHtml(text);

  const escapedText = escapeHtml(text);
  const escapedSearchTerm = escapeHtml(searchTerm);

  let regex;
  try {
    regex = new RegExp('(' + escapedSearchTerm + ')', 'gi');
    regex.test('');
  } catch (e) {
    regex = new RegExp('(' + escapedSearchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
  }

  return escapedText.replace(regex, '<mark class="search-highlight">$1</mark>');
}

/**
 * Show a status message in the status bar.
 * Success messages auto-hide after 5 seconds.
 * @param {string} message
 * @param {string} type - 'success' | 'error' | 'warning' | 'info'
 */
function showStatus(message, type) {
  const statusBar = $('#statusBar');
  statusBar.removeClass('success error warning info');
  statusBar.addClass(type);
  statusBar.text(message);
  statusBar.show();

  if (type === 'success') {
    setTimeout(function() {
      statusBar.fadeOut();
    }, 5000);
  }
}

/**
 * Toggle log entry truncation based on showAllCheckbox state.
 */
function toggleLogTruncation() {
  const showAll = $('#showAllCheckbox').is(':checked');
  $('#log-container').toggleClass('log-truncated', !showAll);
}

// Global functions for inline HTML event handlers (onclick / onchange attributes)

function toggleFilter(header) {
  const content = $(header).next('.filter-content');
  const toggle = $(header).find('.toggle');
  content.toggleClass('collapsed');
  toggle.toggleClass('collapsed');
}

function toggleAll(selectAllCheckbox, fieldName) {
  const checkboxes = $('.' + fieldName + '-checkbox');
  checkboxes.prop('checked', selectAllCheckbox.checked);
}

function updateSelectAll(fieldName) {
  const checkboxes = $('.' + fieldName + '-checkbox');
  const selectAllCheckbox = $('#selectAll_' + fieldName);
  const allChecked = checkboxes.length > 0 && checkboxes.length === checkboxes.filter(':checked').length;
  selectAllCheckbox.prop('checked', allChecked);
}

/**
 * Render checkboxes for a filter type.
 * @param {string} fieldName
 * @param {Array} items
 * @param {boolean} isColumn - If true, skip "No options" placeholder when empty
 */
function renderCheckboxes(fieldName, items, isColumn) {
  const container = $('#' + fieldName + 'Checkboxes');
  container.empty();

  if (!items || items.length === 0) {
    if (!isColumn) {
      container.append('<div class="checkbox-item"><label>No options available</label></div>');
    }
    return;
  }

  items.forEach(function(item) {
    // Extract value and count from item
    // Use 'in' operator to detect null values (|| would skip null)
    let value, count;
    if (typeof item === 'object' && item !== null) {
      value = 'filename' in item ? item.filename :
              'log_level' in item ? item.log_level :
              'thread_name' in item ? item.thread_name :
              'device_id' in item ? item.device_id :
              'component_name' in item ? item.component_name :
              'time_label' in item ? item.time_label : '';
      count = item.count || 0;
    } else {
      value = item;
      count = 0;
    }

    // Use sentinel "__NULL__" as checkbox value for null entries
    const isNull = value === null || value === undefined;
    const checkboxValue = isNull ? '__NULL__' : String(value);
    const displayLabel = isNull ? '<em>(empty)</em>' : escapeHtml(String(value));
    const id = fieldName + '_' + checkboxValue.replace(/[^a-zA-Z0-9]/g, '_');
    const countText = count ? ' <span class="count">(' + count.toLocaleString() + ')</span>' : '';

    const html = `
      <div class="checkbox-item">
        <input type="checkbox" id="${id}" value="${escapeHtml(checkboxValue)}" class="${fieldName}-checkbox" onchange="updateSelectAll('${fieldName}')">
        <label for="${id}">${displayLabel}${countText}</label>
      </div>
    `;
    container.append(html);
  });
}

/**
 * Render active filter tags above the filter panel.
 * @param {Map} presetSteps - Map of id -> label
 * @param {Object} filters - Current filters object
 * @param {Object} handlers - { onRemovePreset, onRemoveArrayFilter, onRemoveSearch, onRemoveTimeRange }
 */
function renderActiveFilters(presetSteps, filters, handlers) {
  const container = $('#activeFilterTags');
  container.empty();

  let hasActive = false;

  // Preset steps
  presetSteps.forEach(function(label, id) {
    hasActive = true;
    const tag = $('<span class="active-filter-tag preset-tag"></span>');
    tag.append($('<span></span>').text('⚡ ' + label));
    const btn = $('<button class="remove-tag-btn" title="Remove">×</button>');
    btn.on('click', function() { handlers.onRemovePreset(id); });
    tag.append(btn);
    container.append(tag);
  });

  // Array-type filters
  const fieldLabels = {
    timeBucket:       '⏰',
    filenameInclude:  '📄✅',
    filenameExclude:  '📄❌',
    logLevelInclude:  '📊✅',
    logLevelExclude:  '📊❌',
    deviceInclude:    '📱✅',
    deviceExclude:    '📱❌',
    componentInclude: '🔧✅',
    componentExclude: '🔧❌',
    threadInclude:    '🧵✅',
    threadExclude:    '🧵❌'
  };

  Object.keys(fieldLabels).forEach(function(field) {
    if (!filters[field] || filters[field].length === 0) return;
    filters[field].forEach(function(value) {
      hasActive = true;
      const displayVal = value === null ? '(empty)' : String(value);
      const tag = $('<span class="active-filter-tag"></span>');
      tag.append($('<span></span>').text(fieldLabels[field] + ' ' + displayVal));
      const btn = $('<button class="remove-tag-btn" title="Remove">×</button>');
      btn.on('click', function() { handlers.onRemoveArrayFilter(field, value); });
      tag.append(btn);
      container.append(tag);
    });
  });

  // Search filter
  if (filters.search) {
    hasActive = true;
    const tag = $('<span class="active-filter-tag"></span>');
    tag.append($('<span></span>').text('🔎 ' + filters.search));
    const btn = $('<button class="remove-tag-btn" title="Remove">×</button>');
    btn.on('click', handlers.onRemoveSearch);
    tag.append(btn);
    container.append(tag);
  }

  // Time range filters
  if (filters.timeFrom) {
    hasActive = true;
    const tag = $('<span class="active-filter-tag"></span>');
    tag.append($('<span></span>').text('⏰From ' + filters.timeFrom));
    const btn = $('<button class="remove-tag-btn" title="Remove">×</button>');
    btn.on('click', function() { handlers.onRemoveTimeRange('timeFrom'); });
    tag.append(btn);
    container.append(tag);
  }
  if (filters.timeTo) {
    hasActive = true;
    const tag = $('<span class="active-filter-tag"></span>');
    tag.append($('<span></span>').text('⏰To ' + filters.timeTo));
    const btn = $('<button class="remove-tag-btn" title="Remove">×</button>');
    btn.on('click', function() { handlers.onRemoveTimeRange('timeTo'); });
    tag.append(btn);
    container.append(tag);
  }

  $('#activeFiltersGroup').toggle(hasActive);
}
