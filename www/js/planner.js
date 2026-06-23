/**
 * Year / month planner view.
 *
 * Renders a calendar-year grid of month blocks (free/busy day dots) that
 * drills into a full month calendar showing cards on the days they span.
 * Reuses BoardManager for card data/modals/API calls (getCardData,
 * openEditCardModal, openAddCardModal, createCard, updateCard, toasts).
 */
const PLANNER_MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
];
const PLANNER_WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const PLANNER_WEEKDAY_INITIALS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
const PLANNER_MAX_CHIPS_PER_DAY = 3;

// Monday-start week matrix covering a calendar month, including the leading/
// trailing days of adjacent months needed to fill complete weeks.
function buildPlannerMonthMatrix(year, month) {
  const firstOfMonth = new Date(year, month - 1, 1);
  const startOffset = (firstOfMonth.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month, 0).getDate();
  const totalCells = Math.ceil((startOffset + daysInMonth) / 7) * 7;

  const current = new Date(year, month - 1, 1 - startOffset);
  const weeks = [];
  for (let w = 0; w < totalCells / 7; w++) {
    const week = [];
    for (let d = 0; d < 7; d++) {
      week.push({ date: new Date(current), inMonth: current.getMonth() === month - 1 });
      current.setDate(current.getDate() + 1);
    }
    weeks.push(week);
  }
  return weeks;
}

function plannerDateKey(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

class PlannerView {
  constructor(boardId, container, boardManager) {
    this.boardId = boardId;
    this.container = container;
    this.boardManager = boardManager;
    this.includeScheduled = false;
    this.showColumns = false;
    this.showTimes = false;
    this.mode = 'year';
    this.currentYear = new Date().getFullYear();
    this.currentMonth = new Date().getMonth() + 1;
    this.placement = null; // { cardId, cardTitle, durationMs }
  }

  async _fetchJson(url) {
    const response = await fetch(url);
    const data = await this.boardManager.parseResponse(response);
    if (!data.success) {
      throw new Error(data.message || 'Request failed');
    }
    return data;
  }

  _toolbarHtml() {
    return `
      <div class="planner-toolbar">
        ${this.mode === 'month' ? '<button type="button" class="btn btn-secondary" id="planner-back-btn">← Back to Year</button>' : ''}
        ${this.mode === 'year' ? `
          <button type="button" class="btn btn-secondary" id="planner-prev-year-btn">‹</button>
          <span class="planner-year-label">${this.currentYear}</span>
          <button type="button" class="btn btn-secondary" id="planner-next-year-btn">›</button>
        ` : `
          <button type="button" class="btn btn-secondary" id="planner-prev-month-btn">‹</button>
          <span class="planner-month-label">${PLANNER_MONTH_NAMES[this.currentMonth - 1]} ${this.currentYear}</span>
          <button type="button" class="btn btn-secondary" id="planner-next-month-btn">›</button>
        `}
        <div class="planner-toggle-group">
          <label class="planner-toggle">
            <input type="checkbox" id="planner-include-scheduled-toggle" ${this.includeScheduled ? 'checked' : ''}>
            Show scheduled tasks
            <span class="planner-legend-dot" title="Scheduled tasks render in this colour"></span>
          </label>
          ${this.mode === 'month' ? `
            <label class="planner-toggle">
              <input type="checkbox" id="planner-show-columns-toggle" ${this.showColumns ? 'checked' : ''}>
              Show columns
            </label>
            <label class="planner-toggle">
              <input type="checkbox" id="planner-show-times-toggle" ${this.showTimes ? 'checked' : ''}>
              Show times
            </label>
          ` : ''}
        </div>
        ${this.placement ? `
          <div class="planner-placement-banner">
            Placing: <strong>${escapeHtml(this.placement.cardTitle)}</strong> &mdash; click a day to move it
            <button type="button" class="btn btn-secondary" id="planner-cancel-placement-btn">Cancel</button>
          </div>
        ` : ''}
      </div>
    `;
  }

  _attachToolbarHandlers() {
    const backBtn = document.getElementById('planner-back-btn');
    if (backBtn) {
      backBtn.addEventListener('click', () => this.renderYear(this.currentYear));
    }
    const prevYearBtn = document.getElementById('planner-prev-year-btn');
    if (prevYearBtn) {
      prevYearBtn.addEventListener('click', () => this.renderYear(this.currentYear - 1));
    }
    const nextYearBtn = document.getElementById('planner-next-year-btn');
    if (nextYearBtn) {
      nextYearBtn.addEventListener('click', () => this.renderYear(this.currentYear + 1));
    }
    const prevMonthBtn = document.getElementById('planner-prev-month-btn');
    if (prevMonthBtn) {
      prevMonthBtn.addEventListener('click', () => {
        const month = this.currentMonth - 1;
        if (month < 1) {
          this.renderMonth(this.currentYear - 1, 12);
        } else {
          this.renderMonth(this.currentYear, month);
        }
      });
    }
    const nextMonthBtn = document.getElementById('planner-next-month-btn');
    if (nextMonthBtn) {
      nextMonthBtn.addEventListener('click', () => {
        const month = this.currentMonth + 1;
        if (month > 12) {
          this.renderMonth(this.currentYear + 1, 1);
        } else {
          this.renderMonth(this.currentYear, month);
        }
      });
    }
    const toggle = document.getElementById('planner-include-scheduled-toggle');
    if (toggle) {
      toggle.addEventListener('change', () => this.setIncludeScheduled(toggle.checked));
    }
    const showColumnsToggle = document.getElementById('planner-show-columns-toggle');
    if (showColumnsToggle) {
      showColumnsToggle.addEventListener('change', () => this.setShowColumns(showColumnsToggle.checked));
    }
    const showTimesToggle = document.getElementById('planner-show-times-toggle');
    if (showTimesToggle) {
      showTimesToggle.addEventListener('change', () => this.setShowTimes(showTimesToggle.checked));
    }
    const cancelPlacementBtn = document.getElementById('planner-cancel-placement-btn');
    if (cancelPlacementBtn) {
      cancelPlacementBtn.addEventListener('click', () => this.exitPlacementMode());
    }
  }

  async setIncludeScheduled(checked) {
    this.includeScheduled = checked;
    if (this.mode === 'year') {
      await this.renderYear(this.currentYear);
    } else {
      await this.renderMonth(this.currentYear, this.currentMonth);
    }
  }

  async setShowColumns(checked) {
    this.showColumns = checked;
    await this.renderMonth(this.currentYear, this.currentMonth);
  }

  async setShowTimes(checked) {
    this.showTimes = checked;
    await this.renderMonth(this.currentYear, this.currentMonth);
  }

  enterPlacementMode(cardId, cardTitle, durationMs, startDate) {
    this.placement = { cardId, cardTitle, durationMs };
    const year = startDate instanceof Date && !Number.isNaN(startDate.getTime())
      ? startDate.getFullYear()
      : this.currentYear;
    this.renderYear(year);
  }

  exitPlacementMode() {
    this.placement = null;
    if (this.mode === 'year') {
      this.renderYear(this.currentYear);
    } else {
      this.renderMonth(this.currentYear, this.currentMonth);
    }
  }

  async renderYear(year) {
    this.mode = 'year';
    this.currentYear = year;

    let data;
    try {
      data = await this._fetchJson(
        `/api/boards/${this.boardId}/planner/year/${year}?include_scheduled=${this.includeScheduled}`
      );
    } catch (err) {
      this.boardManager.showErrorToast(`Failed to load planner year: ${err.message}`);
      return;
    }

    const busyByMonth = {};
    const scheduledByMonth = {};
    data.months.forEach((m) => {
      busyByMonth[m.month] = new Set(m.busy_days);
      scheduledByMonth[m.month] = new Set(m.scheduled_days || []);
    });

    const monthBlocks = PLANNER_MONTH_NAMES.map((name, idx) => {
      const month = idx + 1;
      const busyDays = busyByMonth[month] || new Set();
      const scheduledDays = scheduledByMonth[month] || new Set();
      const weeks = buildPlannerMonthMatrix(year, month);
      const dotsHtml = weeks.map((week) => `
        <div class="planner-mini-week">
          ${week.map((cell) => {
            if (!cell.inMonth) return '<span class="planner-day-dot planner-day-dot-empty"></span>';
            const day = cell.date.getDate();
            // busy (real card) takes precedence over scheduled-only (projected occurrence)
            const state = busyDays.has(day) ? 'busy' : (scheduledDays.has(day) ? 'scheduled' : 'free');
            return `<span class="planner-day-dot ${state}" title="${cell.date.toDateString()}"></span>`;
          }).join('')}
        </div>
      `).join('');

      const weekdayHeaderHtml = PLANNER_WEEKDAY_INITIALS.map((initial) => `<span class="planner-mini-weekday-label">${initial}</span>`).join('');

      return `
        <div class="planner-month-block" data-month="${month}">
          <div class="planner-month-block-header">${name}</div>
          <div class="planner-mini-week planner-mini-weekday-row">${weekdayHeaderHtml}</div>
          <div class="planner-mini-grid">${dotsHtml}</div>
        </div>
      `;
    }).join('');

    this.container.innerHTML = `
      ${this._toolbarHtml()}
      <div class="planner-year-grid">${monthBlocks}</div>
    `;
    this._attachToolbarHandlers();

    this.container.querySelectorAll('.planner-month-block').forEach((block) => {
      block.addEventListener('click', () => {
        this.renderMonth(year, parseInt(block.dataset.month, 10));
      });
    });
  }

  async renderMonth(year, month) {
    this.mode = 'month';
    this.currentYear = year;
    this.currentMonth = month;

    let data;
    try {
      data = await this._fetchJson(
        `/api/boards/${this.boardId}/planner/month/${year}/${month}?include_scheduled=${this.includeScheduled}`
      );
    } catch (err) {
      this.boardManager.showErrorToast(`Failed to load planner month: ${err.message}`);
      return;
    }

    let entries = [
      ...data.cards.map((c) => ({ ...c, is_virtual: false })),
      ...data.virtual
    ];

    // While moving a card, hide it from its current slot - it only
    // reappears (and saves) once placed on a new day.
    if (this.placement) {
      entries = entries.filter((e) => !(e.id === this.placement.cardId && !e.is_virtual));
    }

    const weeks = buildPlannerMonthMatrix(year, month);
    const weekdayHeader = PLANNER_WEEKDAY_LABELS.map((label) => `<div class="planner-weekday-label">${label}</div>`).join('');

    const weeksHtml = weeks.map((week) => week.map((cell) => {
      const dateKey = plannerDateKey(cell.date);
      const dayEntries = entries.filter((entry) => {
        if (!entry.start_date) return false;
        const start = new Date(entry.start_date);
        const end = entry.end_date ? new Date(entry.end_date) : start;
        return cell.date >= new Date(start.getFullYear(), start.getMonth(), start.getDate()) &&
          cell.date <= new Date(end.getFullYear(), end.getMonth(), end.getDate());
      });

      const overflowCount = Math.max(0, dayEntries.length - PLANNER_MAX_CHIPS_PER_DAY);

      const chipsHtml = dayEntries.map((entry, index) => {
        const isOverflow = index >= PLANNER_MAX_CHIPS_PER_DAY;
        const columnName = (this.showColumns && !entry.is_virtual) ? this._getColumnName(entry.column_id) : '';
        const timeLabel = this.showTimes ? this._formatChipTimeForDay(entry, cell.date) : '';
        return `
        <div class="planner-card-chip ${entry.is_virtual ? 'virtual' : ''} ${entry.done ? 'done' : ''}${isOverflow ? ' planner-chip-overflow' : ''}"
             data-card-id="${entry.is_virtual ? entry.template_card_id : entry.id}">
          ${columnName ? `<span class="planner-card-chip-column">${escapeHtml(columnName)}</span>` : ''}
          <span class="planner-card-chip-title">${escapeHtml(entry.title)}</span>
          ${timeLabel ? `<span class="planner-card-chip-time">${escapeHtml(timeLabel)}</span>` : ''}
        </div>
      `;
      }).join('');

      return `
        <div class="planner-day-cell ${cell.inMonth ? '' : 'outside-month'}" data-date="${dateKey}">
          <div class="planner-day-number">${cell.date.getDate()}</div>
          <div class="planner-day-chips">
            ${chipsHtml}
            ${overflowCount > 0 ? `<button class="planner-day-more" data-overflow="${overflowCount}">+${overflowCount} more</button>` : ''}
          </div>
          <div class="planner-day-empty-space"></div>
        </div>
      `;
    }).join('')).join('');

    this.container.innerHTML = `
      ${this._toolbarHtml()}
      <div class="planner-month-grid">
        ${weekdayHeader}
        ${weeksHtml}
      </div>
    `;
    this._attachToolbarHandlers();
    this._attachMonthCellHandlers();
  }

  _attachMonthCellHandlers() {
    this.container.querySelectorAll('.planner-card-chip').forEach((chip) => {
      chip.addEventListener('click', async (e) => {
        e.stopPropagation();
        const cardId = parseInt(chip.dataset.cardId, 10);
        if (chip.classList.contains('virtual')) {
          // Scheduled-preview chips aren't a real placed card - open the
          // template card (and its schedule) directly.
          this._openCard(cardId);
          return;
        }
        const chipTitle = chip.querySelector('.planner-card-chip-title');
        const action = await this._promptCardAction(chipTitle ? chipTitle.textContent.trim() : chip.textContent.trim());
        if (action === 'edit') {
          this._openCard(cardId);
        } else if (action === 'move') {
          await this._startMovingCard(cardId);
        }
      });
    });

    this.container.querySelectorAll('.planner-day-more').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const cell = btn.closest('.planner-day-cell');
        const expanded = cell.classList.toggle('expanded');
        const overflowCount = parseInt(btn.dataset.overflow, 10);
        btn.textContent = expanded ? 'show less' : `+${overflowCount} more`;
      });
    });

    const cellsByDate = new Map();
    this.container.querySelectorAll('.planner-day-cell').forEach((cell) => {
      cellsByDate.set(cell.dataset.date, cell);
    });

    let previewCells = [];
    const clearPreview = () => {
      previewCells.forEach((cell) => {
        const preview = cell.querySelector('.planner-card-chip.preview');
        if (preview) preview.remove();
      });
      previewCells = [];
    };

    this.container.querySelectorAll('.planner-day-cell').forEach((cell) => {
      // While placing/moving a card, the whole day block is clickable to
      // place on that day - including over the hover-preview chip, which is
      // pointer-events:none and would otherwise swallow the click. Real
      // chips still take priority (their own handler calls
      // stopPropagation()), so clicking an existing card still opens the
      // edit/move prompt rather than placing here.
      cell.addEventListener('click', () => {
        if (!this.placement) return;
        const [y, m, d] = cell.dataset.date.split('-').map((n) => parseInt(n, 10));
        this._placeCardOnDate(new Date(y, m - 1, d));
      });

      const emptySpace = cell.querySelector('.planner-day-empty-space');
      if (!emptySpace) return;
      emptySpace.addEventListener('click', (e) => {
        if (this.placement) return; // handled by the cell-level listener above
        e.stopPropagation();
        const [y, m, d] = cell.dataset.date.split('-').map((n) => parseInt(n, 10));
        const clickedDate = new Date(y, m - 1, d);
        if (cell.classList.contains('outside-month')) {
          // Avoid confusing creation on a dimmed adjacent-month day
          return;
        }
        this._createCardOnDate(clickedDate);
      });

      // While placing/moving a card, preview it across every day it would
      // span (start day @ 09:00 through start + duration), not just the
      // hovered cell.
      cell.addEventListener('mouseenter', () => {
        if (!this.placement) return;
        clearPreview();

        const [y, m, d] = cell.dataset.date.split('-').map((n) => parseInt(n, 10));
        const previewStart = new Date(y, m - 1, d, 9, 0, 0);
        const previewEnd = new Date(previewStart.getTime() + this.placement.durationMs);

        const current = new Date(previewStart.getFullYear(), previewStart.getMonth(), previewStart.getDate());
        const lastDay = new Date(previewEnd.getFullYear(), previewEnd.getMonth(), previewEnd.getDate());
        while (current <= lastDay) {
          const targetCell = cellsByDate.get(plannerDateKey(current));
          if (targetCell) {
            const chipsContainer = targetCell.querySelector('.planner-day-chips');
            if (chipsContainer && !chipsContainer.querySelector('.planner-card-chip.preview')) {
              const preview = document.createElement('div');
              preview.className = 'planner-card-chip preview';
              preview.textContent = this.placement.cardTitle;
              chipsContainer.appendChild(preview);
              previewCells.push(targetCell);
            }
          }
          current.setDate(current.getDate() + 1);
        }
      });

      cell.addEventListener('mouseleave', clearPreview);
    });
  }

  _getColumnName(columnId) {
    const columns = this.boardManager.columns || [];
    const column = columns.find((c) => c.id === columnId);
    return column ? column.name : '';
  }

  // Multi-day entries only show a time on the day(s) it's actually
  // anchored to - the start day, the end day, or both when they coincide.
  // Days the entry merely spans through show no time.
  _formatChipTimeForDay(entry, cellDate) {
    if (!entry.start_date) return '';
    const start = new Date(entry.start_date);
    const end = entry.end_date ? new Date(entry.end_date) : start;
    const fmt = (d) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

    const cellKey = plannerDateKey(cellDate);
    const isStartDay = cellKey === plannerDateKey(start);
    const isEndDay = cellKey === plannerDateKey(end);

    if (isStartDay && isEndDay) return `${fmt(start)}–${fmt(end)}`;
    if (isStartDay) return `from ${fmt(start)}`;
    if (isEndDay) return `until ${fmt(end)}`;
    return '';
  }

  async _openCard(cardId) {
    const cardData = await this.boardManager.getCardData(cardId);
    if (cardData) {
      this.boardManager.openEditCardModal(cardId, cardData);
    }
  }

  _promptCardAction(cardTitle) {
    return new Promise((resolve) => {
      const modalHtml = `
        <div class="modal" id="planner-card-action-modal">
          <div class="modal-content">
            <h2>${escapeHtml(cardTitle)}</h2>
            <div class="planner-card-action-list">
              <button type="button" class="btn btn-secondary" id="planner-action-edit">Edit Card</button>
              <button type="button" class="btn btn-secondary" id="planner-action-move">Move on Planner</button>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="planner-action-cancel">Cancel</button>
            </div>
          </div>
        </div>
      `;
      document.body.insertAdjacentHTML('beforeend', modalHtml);
      const modal = document.getElementById('planner-card-action-modal');

      let removeEscapeClose = () => {};
      const cleanup = (result) => {
        removeEscapeClose();
        modal.remove();
        resolve(result);
      };

      removeEscapeClose = setupModalEscapeClose(modal, () => cleanup(null));

      document.getElementById('planner-action-edit').addEventListener('click', () => cleanup('edit'));
      document.getElementById('planner-action-move').addEventListener('click', () => cleanup('move'));
      document.getElementById('planner-action-cancel').addEventListener('click', () => cleanup(null));
      modal.addEventListener('click', (e) => {
        if (e.target === modal) cleanup(null);
      });
    });
  }

  async _startMovingCard(cardId) {
    const cardData = await this.boardManager.getCardData(cardId);
    if (!cardData) return;

    const durationMs = (cardData.start_date && cardData.end_date)
      ? new Date(cardData.end_date) - new Date(cardData.start_date)
      : 60 * 60 * 1000;

    this.placement = { cardId, cardTitle: cardData.title, durationMs };
    if (this.mode === 'year') {
      await this.renderYear(this.currentYear);
    } else {
      await this.renderMonth(this.currentYear, this.currentMonth);
    }
  }

  async _placeCardOnDate(clickedDate) {
    const { cardId, durationMs } = this.placement;
    const cardData = await this.boardManager.getCardData(cardId);
    if (!cardData) return;

    const newStart = new Date(clickedDate.getFullYear(), clickedDate.getMonth(), clickedDate.getDate(), 9, 0, 0);
    const newEnd = new Date(newStart.getTime() + durationMs);

    const success = await this.boardManager.updateCard(cardId, cardData.title, cardData.description, newStart, newEnd);
    if (success) {
      this.boardManager.showSuccessToast(`"${cardData.title}" placed on ${newStart.toDateString()}`);
      this.exitPlacementMode();
    }
  }

  async _createCardOnDate(clickedDate) {
    const columns = this.boardManager.columns || [];
    if (columns.length === 0) {
      this.boardManager.showErrorToast('Add a column to the board before creating cards');
      return;
    }

    const columnId = await this._pickColumn(columns);
    if (columnId === null) return;

    const startDate = new Date(clickedDate.getFullYear(), clickedDate.getMonth(), clickedDate.getDate(), 9, 0, 0);
    const endDate = new Date(startDate.getTime() + 60 * 60 * 1000);

    this.boardManager.openAddCardModal(columnId, null, false, startDate.toISOString(), endDate.toISOString());

    // After the add-card modal closes (createCard() already refreshes the
    // hidden board container), re-render this month so the new card shows up.
    const modalObserver = new MutationObserver(() => {
      if (!document.getElementById('add-card-modal')) {
        modalObserver.disconnect();
        this.renderMonth(this.currentYear, this.currentMonth);
      }
    });
    modalObserver.observe(document.body, { childList: true });
  }

  _pickColumn(columns) {
    return new Promise((resolve) => {
      const modalHtml = `
        <div class="modal" id="planner-column-picker-modal">
          <div class="modal-content">
            <h2>Add Card To...</h2>
            <div class="planner-column-picker-list">
              ${columns.map((col) => `<button type="button" class="btn btn-secondary planner-column-picker-item" data-column-id="${col.id}">${escapeHtml(col.name)}</button>`).join('')}
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="planner-column-picker-cancel">Cancel</button>
            </div>
          </div>
        </div>
      `;
      document.body.insertAdjacentHTML('beforeend', modalHtml);
      const modal = document.getElementById('planner-column-picker-modal');

      let removeEscapeClose = () => {};
      const cleanup = (result) => {
        removeEscapeClose();
        modal.remove();
        resolve(result);
      };

      removeEscapeClose = setupModalEscapeClose(modal, () => cleanup(null));

      modal.querySelectorAll('.planner-column-picker-item').forEach((btn) => {
        btn.addEventListener('click', () => cleanup(parseInt(btn.dataset.columnId, 10)));
      });
      document.getElementById('planner-column-picker-cancel').addEventListener('click', () => cleanup(null));
      modal.addEventListener('click', (e) => {
        if (e.target === modal) cleanup(null);
      });
    });
  }
}
