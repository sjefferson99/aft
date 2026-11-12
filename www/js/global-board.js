/**
 * Global board page (#663).
 *
 * Shows cards promoted from agile boards in four states: New, In Progress,
 * Waiting and Done. Done is the card's own done flag, so moving a card into or
 * out of Done ticks or unticks it on its board.
 *
 * Everything is built from DOM nodes rather than HTML strings, because card
 * titles and names are user content.
 *
 * Real-time updates: the page joins the global_board_<id> room, whose
 * global_board_changed event carries no card content, and the rooms of the
 * boards its cards come from, so title, assignee and done edits arrive too.
 * Any of these schedules one debounced refetch through the scoped API.
 */

const GLOBAL_BOARD_STATES = [
  { key: 'new', label: 'New' },
  { key: 'in_progress', label: 'In Progress' },
  { key: 'waiting', label: 'Waiting' },
  { key: 'done', label: 'Done' },
];
const GLOBAL_BOARD_DONE_STATE = 'done';
const GLOBAL_BOARD_REQUEST_TIMEOUT_MS = 5000;
const GLOBAL_BOARD_REFRESH_DEBOUNCE_MS = 250;
const GLOBAL_BOARD_MOBILE_BREAKPOINT = 900;
const GLOBAL_BOARD_DEFAULT_AVATAR_COLOUR = '#90A4AE';
// How long to wait for a card's board to load and open its modal.
const GLOBAL_BOARD_CARD_OPEN_TIMEOUT_MS = 15000;
// A closed card's frame lingers hidden, so a save it started can finish.
const GLOBAL_BOARD_CARD_FRAME_LINGER_MS = 10000;

// Board room events that can change what the global board shows. card_created
// is left out: a new card can't already be promoted.
const GLOBAL_BOARD_SOURCE_EVENTS = [
  'card_updated',
  'card_deleted',
  'card_moved',
  'cards_moved',
  'card_archived',
  'card_unarchived',
  'card_done_status_changed',
  'column_updated',
  'column_deleted',
];

class GlobalBoardPage {
  constructor(container) {
    this.container = container;
    this.globalBoardId = null;
    this.globalBoard = null;
    this.states = {};
    this.epics = [];
    this.assignees = [];
    this.knownCardIds = new Set();
    this.filters = { assigneeIds: new Set(), unassigned: false, epicId: null };

    this.socket = null;
    this.hasConnected = false;
    this.roomJoined = false;
    this.joinedBoardIds = new Set();

    this.loading = false;
    this.reloadPending = false;
    this.refreshTimer = null;
    this.hasLoaded = false;

    this.dragState = null;
    this.renderPending = false;
    this.liveRegion = null;

    this.mobileQuery = window.matchMedia(`(max-width: ${GLOBAL_BOARD_MOBILE_BREAKPOINT}px)`);
    this.cardOverlay = null;
  }

  async init() {
    const boardsResult = await this.request('/api/global-boards');
    if (!boardsResult.ok) {
      this.renderMessage(this.describeFailure(boardsResult, 'Failed to load the global board.'));
      return;
    }

    const boards = boardsResult.data.global_boards || [];
    const requestedId = parseInt(new URLSearchParams(window.location.search).get('id'), 10);
    const globalBoard = Number.isInteger(requestedId)
      ? boards.find((board) => board.id === requestedId)
      : boards[0];

    if (!globalBoard) {
      this.renderMessage(boards.length === 0 ? 'No global board is available.' : 'Global board not found.');
      return;
    }

    this.globalBoardId = globalBoard.id;
    this.globalBoard = globalBoard;
    if (requestedId !== globalBoard.id) {
      const url = new URL(window.location.href);
      url.searchParams.set('id', String(globalBoard.id));
      window.history.replaceState(null, '', url);
    }

    this.loadFilters();
    await this.load();
    this.connectSocket();

    // Drag is desktop only, so re-render when the width or touchscreen mode
    // (a body class set once the user's setting loads) changes.
    this.mobileQuery.addEventListener('change', () => this.requestRender());
    let touchscreenMode = document.body.classList.contains('touchscreen-mode');
    new MutationObserver(() => {
      const enabled = document.body.classList.contains('touchscreen-mode');
      if (enabled !== touchscreenMode) {
        touchscreenMode = enabled;
        this.requestRender();
      }
    }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }

  // ---------------------------------------------------------------------------
  // Requests
  // ---------------------------------------------------------------------------

  async request(url, options = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), GLOBAL_BOARD_REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      let data = null;
      try {
        data = await response.json();
      } catch (e) {
        data = null;
      }
      return {
        ok: response.ok && !!data && data.success !== false,
        status: response.status,
        data,
        timedOut: false,
      };
    } catch (error) {
      return { ok: false, status: 0, data: null, timedOut: error.name === 'AbortError' };
    } finally {
      clearTimeout(timeoutId);
    }
  }

  describeFailure(result, fallback) {
    if (result.timedOut) {
      return 'The request timed out. Check your connection and try again.';
    }
    if (result.data && typeof result.data.message === 'string' && result.data.message) {
      return result.data.message;
    }
    return fallback;
  }

  async load() {
    if (this.loading) {
      this.reloadPending = true;
      return;
    }
    this.loading = true;
    try {
      const result = await this.request(`/api/global-boards/${this.globalBoardId}/cards`);
      if (!result.ok) {
        const message = this.describeFailure(result, 'Failed to load the global board.');
        if (this.hasLoaded) {
          this.showToast(message, true);
        } else {
          this.renderMessage(message);
        }
        return;
      }

      const data = result.data;
      this.globalBoard = data.global_board || this.globalBoard;
      this.states = data.states || {};
      this.epics = Array.isArray(data.epics) ? data.epics : [];
      this.collectAssignees();
      this.pruneFilters();
      this.hasLoaded = true;

      if (window.header && typeof window.header.setBoardName === 'function') {
        window.header.setBoardName(this.globalBoard.name);
      }

      this.requestRender();
      this.joinBoardRooms();
    } finally {
      this.loading = false;
      if (this.reloadPending) {
        this.reloadPending = false;
        this.load();
      }
    }
  }

  scheduleRefresh() {
    clearTimeout(this.refreshTimer);
    this.refreshTimer = setTimeout(() => this.load(), GLOBAL_BOARD_REFRESH_DEBOUNCE_MS);
  }

  async moveCard(cardId, state, afterCardId) {
    const card = this.findCard(cardId);
    const result = await this.request(`/api/global-boards/${this.globalBoardId}/cards/${cardId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state, after_card_id: afterCardId }),
    });

    if (result.ok) {
      const label = GLOBAL_BOARD_STATES.find((entry) => entry.key === state)?.label || state;
      this.announce(`Moved ${card ? card.title : 'card'} to ${label}`);
    } else {
      this.showToast(this.describeFailure(result, 'Failed to move the card.'), true);
    }
    await this.load();
  }

  // ---------------------------------------------------------------------------
  // Real-time updates
  // ---------------------------------------------------------------------------

  connectSocket() {
    if (typeof io === 'undefined') {
      return;
    }

    const socket = io({
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      transports: ['websocket', 'polling'],
    });
    this.socket = socket;
    // header.js reads this for the connection status widget.
    window.aftPageSocket = socket;

    socket.on('connect', () => {
      // utils.js tags API requests with this id, so the server skips this tab
      // when broadcasting the changes it makes itself.
      window.__aftSocketId = socket.id;
      this.joinedBoardIds.clear();
      this.roomJoined = false;
      socket.emit('join_global_board', { global_board_id: this.globalBoardId }, (ack) => {
        this.roomJoined = !!(ack && ack.success);
      });
      this.joinBoardRooms();
      if (this.hasConnected) {
        // Catch up on anything missed while disconnected.
        this.scheduleRefresh();
      }
      this.hasConnected = true;
      this.updateHeaderSocketStatus();
    });

    socket.on('disconnect', () => {
      if (window.__aftSocketId === socket.id) {
        window.__aftSocketId = null;
      }
      this.updateHeaderSocketStatus();
    });

    socket.on('global_board_changed', () => this.scheduleRefresh());

    GLOBAL_BOARD_SOURCE_EVENTS.forEach((eventName) => {
      socket.on(eventName, (data) => {
        // Edits to cards that aren't on this board don't change it.
        if (eventName === 'card_updated' && data && !this.knownCardIds.has(data.card_id)) {
          return;
        }
        this.scheduleRefresh();
      });
    });
  }

  joinBoardRooms() {
    if (!this.socket || !this.socket.connected) {
      return;
    }
    this.allCards().forEach((card) => {
      if (!this.joinedBoardIds.has(card.board_id)) {
        this.joinedBoardIds.add(card.board_id);
        this.socket.emit('join_board', { board_id: card.board_id });
      }
    });
  }

  updateHeaderSocketStatus() {
    if (window.header && typeof window.header.updateWebSocketStatus === 'function') {
      window.header.updateWebSocketStatus();
    }
  }

  // ---------------------------------------------------------------------------
  // Data helpers
  // ---------------------------------------------------------------------------

  allCards() {
    return GLOBAL_BOARD_STATES.flatMap((state) => this.states[state.key] || []);
  }

  findCard(cardId) {
    return this.allCards().find((card) => card.card_id === cardId) || null;
  }

  collectAssignees() {
    const users = new Map();
    this.knownCardIds = new Set();
    this.allCards().forEach((card) => {
      this.knownCardIds.add(card.card_id);
      [card.assigned_to, ...(card.secondary_assignees || [])].forEach((user) => {
        if (user && !users.has(user.id)) {
          users.set(user.id, user);
        }
      });
    });
    this.assignees = [...users.values()].sort((a, b) =>
      this.userName(a).localeCompare(this.userName(b), undefined, { sensitivity: 'base' })
    );
  }

  userName(user) {
    return (user && (user.display_name || user.username)) || 'Unknown';
  }

  initials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) {
      return '?';
    }
    const letters = parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0];
    return letters.toUpperCase();
  }

  // ---------------------------------------------------------------------------
  // Filters
  // ---------------------------------------------------------------------------

  filterStorageKey() {
    return `aft:global-board:${this.globalBoardId}:filters`;
  }

  loadFilters() {
    try {
      const saved = JSON.parse(localStorage.getItem(this.filterStorageKey()) || 'null');
      if (saved && typeof saved === 'object') {
        this.filters.assigneeIds = new Set(
          (Array.isArray(saved.assigneeIds) ? saved.assigneeIds : []).filter(Number.isInteger)
        );
        this.filters.unassigned = saved.unassigned === true;
        this.filters.epicId = Number.isInteger(saved.epicId) ? saved.epicId : null;
      }
    } catch (e) {
      // Storage can be unavailable; filters then start empty.
    }
  }

  saveFilters() {
    try {
      localStorage.setItem(this.filterStorageKey(), JSON.stringify({
        assigneeIds: [...this.filters.assigneeIds],
        unassigned: this.filters.unassigned,
        epicId: this.filters.epicId,
      }));
    } catch (e) {
      // Not saving filters is harmless.
    }
  }

  // Drop selections that no longer match anything, so a filter can't hide
  // every card with no button left to clear it.
  pruneFilters() {
    const userIds = new Set(this.assignees.map((user) => user.id));
    this.filters.assigneeIds = new Set([...this.filters.assigneeIds].filter((id) => userIds.has(id)));
    if (this.filters.epicId !== null && !this.epics.some((epic) => epic.id === this.filters.epicId)) {
      this.filters.epicId = null;
    }
  }

  filtersActive() {
    return this.filters.assigneeIds.size > 0 || this.filters.unassigned || this.filters.epicId !== null;
  }

  cardMatchesFilters(card) {
    if (this.filters.epicId !== null && card.board_id !== this.filters.epicId) {
      return false;
    }
    if (this.filters.assigneeIds.size === 0 && !this.filters.unassigned) {
      return true;
    }
    if (this.filters.unassigned && !card.assigned_to) {
      return true;
    }
    const cardUserIds = [card.assigned_to, ...(card.secondary_assignees || [])]
      .filter(Boolean)
      .map((user) => user.id);
    return cardUserIds.some((id) => this.filters.assigneeIds.has(id));
  }

  updateFilters(change) {
    change();
    this.saveFilters();
    this.requestRender();
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  canDrag() {
    return !this.mobileQuery.matches && !document.body.classList.contains('touchscreen-mode');
  }

  requestRender() {
    if (!this.hasLoaded) {
      return;
    }
    // Rebuilding mid-drag would drop the card being dragged.
    if (this.dragState) {
      this.renderPending = true;
      return;
    }
    this.render();
  }

  renderMessage(message) {
    this.container.replaceChildren(this.el('p', { className: 'gb-status-message', text: message }));
    this.container.setAttribute('aria-busy', 'false');
  }

  render() {
    this.renderPending = false;
    const focus = this.captureFocus();
    const scrollPositions = this.captureScroll();

    this.liveRegion = this.liveRegion || this.el('div', {
      className: 'visually-hidden',
      attrs: { 'aria-live': 'polite', role: 'status' },
    });

    const columns = this.el('div', { className: 'gb-columns' });
    GLOBAL_BOARD_STATES.forEach((state) => columns.appendChild(this.renderColumn(state)));

    const children = [this.renderToolbar()];
    if (this.allCards().length === 0) {
      children.push(this.el('p', {
        className: 'gb-hint',
        text: 'No cards yet. Cards promoted from agile boards appear here.',
      }));
    }
    children.push(columns, this.liveRegion);

    this.container.replaceChildren(...children);
    this.container.setAttribute('aria-busy', 'false');
    this.restoreScroll(scrollPositions);
    this.restoreFocus(focus);
  }

  renderToolbar() {
    const toolbar = this.el('div', {
      className: 'gb-toolbar',
      attrs: { role: 'region', 'aria-label': 'Global board filters' },
    });

    const assigneeGroup = this.el('div', {
      className: 'gb-assignee-filter',
      attrs: { role: 'group', 'aria-label': 'Filter by assignee' },
    });
    this.assignees.forEach((user) => {
      const name = this.userName(user);
      const selected = this.filters.assigneeIds.has(user.id);
      const button = this.el('button', {
        className: `gb-assignee-btn${selected ? ' selected' : ''}`,
        attrs: {
          type: 'button',
          title: name,
          'aria-label': `Filter ${name}`,
          'aria-pressed': String(selected),
          'data-filter-key': `user-${user.id}`,
        },
      });
      button.appendChild(this.renderAvatar(user, 'gb-avatar'));
      button.addEventListener('click', () => this.updateFilters(() => {
        if (this.filters.assigneeIds.has(user.id)) {
          this.filters.assigneeIds.delete(user.id);
        } else {
          this.filters.assigneeIds.add(user.id);
        }
      }));
      assigneeGroup.appendChild(button);
    });

    const unassignedButton = this.el('button', {
      className: `gb-assignee-btn${this.filters.unassigned ? ' selected' : ''}`,
      attrs: {
        type: 'button',
        title: 'Unassigned',
        'aria-label': 'Filter unassigned cards',
        'aria-pressed': String(this.filters.unassigned),
        'data-filter-key': 'unassigned',
      },
    });
    unassignedButton.appendChild(this.el('span', { className: 'gb-avatar gb-avatar--unassigned', text: 'U' }));
    unassignedButton.addEventListener('click', () => this.updateFilters(() => {
      this.filters.unassigned = !this.filters.unassigned;
    }));
    assigneeGroup.appendChild(unassignedButton);
    toolbar.appendChild(assigneeGroup);

    const epicId = 'gb-epic-filter';
    const epicWrap = this.el('div', { className: 'gb-epic-filter' });
    epicWrap.appendChild(this.el('label', { text: 'Epic', attrs: { for: epicId } }));
    const epicSelect = this.el('select', { attrs: { id: epicId, 'data-filter-key': 'epic' } });
    epicSelect.appendChild(this.el('option', { text: 'All epics', attrs: { value: '' } }));
    this.epics.forEach((epic) => {
      const option = this.el('option', { text: epic.name, attrs: { value: String(epic.id) } });
      option.selected = epic.id === this.filters.epicId;
      epicSelect.appendChild(option);
    });
    epicSelect.addEventListener('change', () => this.updateFilters(() => {
      const value = parseInt(epicSelect.value, 10);
      this.filters.epicId = Number.isInteger(value) ? value : null;
    }));
    epicWrap.appendChild(epicSelect);
    toolbar.appendChild(epicWrap);

    if (this.filtersActive()) {
      const clearButton = this.el('button', {
        className: 'btn btn-secondary gb-clear-filters',
        text: 'Clear filters',
        attrs: { type: 'button', 'data-filter-key': 'clear' },
      });
      clearButton.addEventListener('click', () => this.updateFilters(() => {
        this.filters.assigneeIds.clear();
        this.filters.unassigned = false;
        this.filters.epicId = null;
      }));
      toolbar.appendChild(clearButton);
    }

    return toolbar;
  }

  renderColumn(state) {
    const cards = (this.states[state.key] || []).filter((card) => this.cardMatchesFilters(card));
    const headingId = `gb-column-${state.key}-title`;

    const column = this.el('section', {
      className: 'gb-column',
      attrs: { 'data-state': state.key, 'aria-labelledby': headingId },
    });

    const header = this.el('div', { className: 'gb-column-header' });
    const heading = this.el('h2', { attrs: { id: headingId } });
    heading.appendChild(document.createTextNode(state.label));
    heading.appendChild(this.el('span', { className: 'gb-card-count', text: ` (${cards.length})` }));
    header.appendChild(heading);
    if (state.key === GLOBAL_BOARD_DONE_STATE && this.globalBoard && this.globalBoard.done_visible_days) {
      const days = this.globalBoard.done_visible_days;
      const note = `Done in the last ${days} ${days === 1 ? 'day' : 'days'}`;
      // Shares the heading's line, so it may be cut short; the title keeps it whole.
      header.appendChild(this.el('p', { className: 'gb-column-note', text: note, attrs: { title: note } }));
    }
    column.appendChild(header);

    const list = this.el('div', {
      className: 'gb-card-list',
      attrs: { role: 'list', 'data-state': state.key },
    });
    cards.forEach((card) => list.appendChild(this.renderCard(card)));
    list.appendChild(this.el('p', { className: 'gb-empty', text: 'No cards' }));

    if (this.canDrag()) {
      list.addEventListener('dragover', (event) => this.handleDragOver(event, list));
      list.addEventListener('dragleave', (event) => this.handleDragLeave(event, list));
      list.addEventListener('drop', (event) => this.handleDrop(event, list));
    }
    column.appendChild(list);
    return column;
  }

  renderCard(card) {
    const draggable = card.can_edit && this.canDrag();
    const element = this.el('div', {
      className: `gb-card${card.can_edit ? '' : ' gb-card--readonly'}`,
      attrs: {
        role: 'listitem',
        'data-card-id': String(card.card_id),
        'data-state': card.state,
        draggable: String(draggable),
      },
    });

    const link = this.el('a', {
      className: 'gb-card-title',
      text: card.title,
      attrs: {
        href: `/board.html?id=${encodeURIComponent(card.board_id)}&card=${encodeURIComponent(card.card_id)}`,
        draggable: 'false',
      },
    });
    element.appendChild(link);

    const context = `${card.board_name} › ${card.column_name}`;
    const contextLine = this.el('p', { className: 'gb-card-context' });
    contextLine.appendChild(this.el('a', {
      className: 'gb-card-board-link',
      text: context,
      attrs: {
        href: `/board.html?id=${encodeURIComponent(card.board_id)}`,
        title: `Open ${card.board_name}`,
        draggable: 'false',
      },
    }));
    element.appendChild(contextLine);

    const footer = this.el('div', { className: 'gb-card-footer' });
    if (card.assigned_to) {
      footer.appendChild(this.renderAvatar(card.assigned_to, 'gb-avatar gb-card-assignee', true));
    }

    if (card.can_edit) {
      const select = this.el('select', {
        className: 'gb-card-move',
        attrs: {
          'aria-label': `Move ${card.title} to`,
          title: 'Move to',
          'data-card-id': String(card.card_id),
          draggable: 'false',
        },
      });
      GLOBAL_BOARD_STATES.forEach((state) => {
        const option = this.el('option', { text: state.label, attrs: { value: state.key } });
        option.selected = state.key === card.state;
        select.appendChild(option);
      });
      select.addEventListener('change', () => {
        if (select.value !== card.state) {
          select.disabled = true;
          this.moveCard(card.card_id, select.value, null);
        }
      });
      footer.appendChild(select);
    } else {
      element.setAttribute('title', 'Read only');
    }
    element.appendChild(footer);

    if (draggable) {
      element.addEventListener('dragstart', (event) => this.handleDragStart(event, card, element));
      element.addEventListener('dragend', () => this.handleDragEnd(element));
    }

    // The card itself opens the edit modal here. Its links and controls keep
    // their own jobs: the title opens the card on its board, the context line
    // opens the board, and Move to moves it.
    element.tabIndex = 0;
    element.setAttribute('aria-label', `${card.title}. Press Enter to edit here.`);
    element.addEventListener('click', (event) => {
      if (!event.target.closest('a, select, button, input')) {
        this.openCardOverlay(card);
      }
    });
    element.addEventListener('keydown', (event) => {
      if (event.target === element && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        this.openCardOverlay(card);
      }
    });
    return element;
  }

  // ---------------------------------------------------------------------------
  // Card edit overlay
  // ---------------------------------------------------------------------------

  /**
   * Open a card's edit modal over the global board. The modal belongs to the
   * board page, so this shows the card's board in a frame in card-modal-only
   * mode, which shows just the modal and reports back when it closes.
   */
  openCardOverlay(card) {
    if (this.cardOverlay && !this.cardOverlay.closing) {
      return;
    }
    this.removeCardOverlay();

    const overlay = this.el('div', {
      className: 'gb-card-overlay',
      attrs: { role: 'dialog', 'aria-modal': 'true', 'aria-label': `Edit ${card.title}` },
    });
    const loading = this.el('div', { className: 'gb-card-overlay-loading', attrs: { role: 'status' } });
    loading.appendChild(this.el('span', { className: 'gb-card-overlay-spinner', attrs: { 'aria-hidden': 'true' } }));
    loading.appendChild(this.el('span', { text: 'Opening card...' }));
    const frame = this.el('iframe', {
      className: 'gb-card-frame',
      attrs: {
        title: `Edit ${card.title}`,
        src: `/board.html?id=${encodeURIComponent(card.board_id)}&card=${encodeURIComponent(card.card_id)}&embedded=1`,
      },
    });
    overlay.append(loading, frame);
    document.body.appendChild(overlay);
    document.body.classList.add('gb-card-overlay-open');

    const state = {
      element: overlay,
      frame,
      cardId: card.card_id,
      opened: false,
      closing: false,
      keyHandler: (event) => {
        if (event.key === 'Escape' && !state.opened) {
          this.closeCardOverlay(false);
        }
      },
      timer: setTimeout(() => {
        if (!state.opened) {
          this.showToast('The card took too long to open. Please try again.', true);
          this.closeCardOverlay(false);
        }
      }, GLOBAL_BOARD_CARD_OPEN_TIMEOUT_MS),
    };
    document.addEventListener('keydown', state.keyHandler);
    this.cardOverlay = state;
  }

  /**
   * Called by the card frame's board page (reportCardModalToParent in
   * board.js). The browser only lets a same-origin page reach this, and it
   * acts only for the frame this page opened.
   *
   * @param {Window} source - The calling frame's window.
   * @param {string} type - 'opened' or 'closed'.
   * @param {boolean} opened - For 'closed', whether the modal ever opened.
   * @param {string|null} reason - Why it didn't open: 'not_found' or 'unavailable'.
   */
  handleCardFrameEvent(source, type, opened = true, reason = null) {
    const state = this.cardOverlay;
    if (!state || state.closing || source !== state.frame.contentWindow) {
      return;
    }
    if (type === 'opened') {
      state.opened = true;
      clearTimeout(state.timer);
      state.element.classList.add('is-ready');
      state.frame.focus();
    } else if (type === 'closed') {
      if (!opened) {
        this.showToast(reason === 'unavailable'
          ? 'Couldn\'t open the card. Check your connection and try again.'
          : 'This card can\'t be opened. It may have been archived or deleted.', true);
      }
      this.closeCardOverlay(true);
    }
  }

  // Hide at once, but leave the frame running for a moment so a request the
  // modal started on its way out (such as Move to top) can finish.
  closeCardOverlay(refresh) {
    const state = this.cardOverlay;
    if (!state || state.closing) {
      return;
    }
    state.closing = true;
    clearTimeout(state.timer);
    document.removeEventListener('keydown', state.keyHandler);
    state.element.classList.add('is-closed');
    state.element.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('gb-card-overlay-open');
    state.removeTimer = setTimeout(() => this.removeCardOverlay(), GLOBAL_BOARD_CARD_FRAME_LINGER_MS);

    const cardElement = this.container.querySelector(`.gb-card[data-card-id="${state.cardId}"]`);
    if (cardElement) {
      cardElement.focus({ preventScroll: true });
    }
    if (refresh) {
      this.scheduleRefresh();
    }
  }

  removeCardOverlay() {
    const state = this.cardOverlay;
    if (!state) {
      return;
    }
    clearTimeout(state.timer);
    clearTimeout(state.removeTimer);
    document.removeEventListener('keydown', state.keyHandler);
    state.element.remove();
    document.body.classList.remove('gb-card-overlay-open');
    this.cardOverlay = null;
  }

  renderAvatar(user, className, labelled = false) {
    const name = this.userName(user);
    const avatar = this.el('span', { className, text: this.initials(name) });
    // Assigning through style rejects anything that isn't a colour.
    avatar.style.backgroundColor = user.profile_colour || GLOBAL_BOARD_DEFAULT_AVATAR_COLOUR;
    if (labelled) {
      avatar.setAttribute('title', name);
      avatar.setAttribute('role', 'img');
      avatar.setAttribute('aria-label', `Assigned to ${name}`);
    } else {
      avatar.setAttribute('aria-hidden', 'true');
    }
    return avatar;
  }

  el(tag, { className = '', text = null, attrs = {} } = {}) {
    const element = document.createElement(tag);
    if (className) {
      element.className = className;
    }
    if (text !== null) {
      element.textContent = text;
    }
    Object.entries(attrs).forEach(([name, value]) => element.setAttribute(name, value));
    return element;
  }

  // Re-rendering replaces every node, so keep keyboard focus and scrolling.
  captureFocus() {
    const active = document.activeElement;
    if (!active || !this.container.contains(active)) {
      return null;
    }
    const card = active.closest('.gb-card');
    if (card) {
      return {
        cardId: card.dataset.cardId,
        selector: active === card ? null
          : (active.classList.contains('gb-card-move') ? '.gb-card-move' : '.gb-card-title'),
      };
    }
    const filterKey = active.getAttribute('data-filter-key');
    return filterKey ? { filterKey } : null;
  }

  restoreFocus(focus) {
    if (!focus) {
      return;
    }
    let target = null;
    if (focus.cardId) {
      const card = this.container.querySelector(`.gb-card[data-card-id="${CSS.escape(focus.cardId)}"]`);
      target = card && focus.selector ? card.querySelector(focus.selector) : card;
    } else if (focus.filterKey) {
      target = this.container.querySelector(`[data-filter-key="${CSS.escape(focus.filterKey)}"]`);
    }
    if (target) {
      target.focus({ preventScroll: true });
    }
  }

  captureScroll() {
    const positions = {};
    this.container.querySelectorAll('.gb-card-list').forEach((list) => {
      positions[list.dataset.state] = list.scrollTop;
    });
    const columns = this.container.querySelector('.gb-columns');
    positions.__columns = columns ? columns.scrollLeft : 0;
    return positions;
  }

  restoreScroll(positions) {
    this.container.querySelectorAll('.gb-card-list').forEach((list) => {
      list.scrollTop = positions[list.dataset.state] || 0;
    });
    const columns = this.container.querySelector('.gb-columns');
    if (columns) {
      columns.scrollLeft = positions.__columns || 0;
    }
  }

  // ---------------------------------------------------------------------------
  // Drag and drop (desktop)
  // ---------------------------------------------------------------------------

  previousCardId(element) {
    let previous = element.previousElementSibling;
    while (previous && !previous.classList.contains('gb-card')) {
      previous = previous.previousElementSibling;
    }
    return previous ? parseInt(previous.dataset.cardId, 10) : null;
  }

  handleDragStart(event, card, element) {
    this.dragState = {
      cardId: card.card_id,
      fromState: card.state,
      fromAfterId: this.previousCardId(element),
      element,
      dropped: false,
    };
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', String(card.card_id));
    // Style after the browser has taken its drag image.
    requestAnimationFrame(() => element.classList.add('dragging'));
  }

  handleDragOver(event, list) {
    if (!this.dragState) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    list.classList.add('gb-drop-target');

    const dragged = this.dragState.element;
    if (list.dataset.state === GLOBAL_BOARD_DONE_STATE) {
      // Done is newest first, so a card dropped there goes to the top.
      if (list.firstElementChild !== dragged) {
        list.insertBefore(dragged, list.firstElementChild);
      }
      return;
    }

    const after = this.cardBelowPointer(list, event.clientY);
    const reference = after || list.querySelector('.gb-empty');
    if (reference !== dragged && dragged.nextElementSibling !== reference) {
      list.insertBefore(dragged, reference);
    }
  }

  cardBelowPointer(list, clientY) {
    const cards = [...list.querySelectorAll('.gb-card:not(.dragging)')];
    return cards.find((card) => {
      const rect = card.getBoundingClientRect();
      return clientY < rect.top + rect.height / 2;
    }) || null;
  }

  handleDragLeave(event, list) {
    if (!list.contains(event.relatedTarget)) {
      list.classList.remove('gb-drop-target');
    }
  }

  handleDrop(event, list) {
    if (!this.dragState) {
      return;
    }
    event.preventDefault();
    list.classList.remove('gb-drop-target');
    this.dragState.dropped = true;

    const { cardId, fromState, fromAfterId, element } = this.dragState;
    const toState = list.dataset.state;
    const afterId = toState === GLOBAL_BOARD_DONE_STATE ? null : this.previousCardId(element);
    const unchanged = toState === fromState
      && (toState === GLOBAL_BOARD_DONE_STATE || afterId === fromAfterId);

    this.finishDrag(element);
    if (unchanged) {
      this.render();
      return;
    }
    this.moveCard(cardId, toState, afterId);
  }

  handleDragEnd(element) {
    if (!this.dragState) {
      return;
    }
    const dropped = this.dragState.dropped;
    this.finishDrag(element);
    if (!dropped) {
      // Cancelled: put the card back where the data says it is.
      this.render();
    }
  }

  finishDrag(element) {
    element.classList.remove('dragging');
    this.container.querySelectorAll('.gb-drop-target').forEach((list) => list.classList.remove('gb-drop-target'));
    this.dragState = null;
    if (this.renderPending) {
      this.render();
    }
  }

  // ---------------------------------------------------------------------------
  // Feedback
  // ---------------------------------------------------------------------------

  announce(message) {
    if (this.liveRegion) {
      this.liveRegion.textContent = message;
    }
  }

  showToast(message, isError = false) {
    if (window.header && typeof window.header.showHeaderToast === 'function') {
      window.header.showHeaderToast(message, isError);
    }
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  const container = document.getElementById('global-board-container');
  if (!container) {
    return;
  }
  // Wait for the header's sign-in check, so a signed-out visitor is sent to
  // login before anything loads.
  if (window.authBootstrapPromise) {
    const canContinue = await window.authBootstrapPromise;
    if (!canContinue) {
      return;
    }
  }
  window.globalBoardPage = new GlobalBoardPage(container);
  window.globalBoardPage.init();
});
