// Search across boards (#593), on the boards page. Board search in the board
// header stays scoped to one board and view; this panel searches every board
// the user can open, or a chosen set, through GET /api/search/cards. Results
// are grouped by board and then by view, and link to the card on its board.
// Everything from the server is rendered with DOM nodes and textContent.

const CARD_SEARCH_MIN_LENGTH = 2;
const CARD_SEARCH_MAX_LENGTH = 200;
const CARD_SEARCH_DEBOUNCE_MS = 500;
const CARD_SEARCH_TIMEOUT_MS = 5000;
const CARD_SEARCH_LOADING_DELAY_MS = 500;
const CARD_SEARCH_VIEW_LABELS = {
  task: 'Task view',
  done: 'Done view',
  archived: 'Archived view',
  scheduled: 'Scheduled view',
};

class CardSearchPanel {
  /**
   * @param {HTMLElement} mount Element the panel is added to.
   * @param {HTMLElement} boardsList The boards grid, hidden while results show.
   */
  constructor(mount, boardsList) {
    this.mount = mount;
    this.boardsList = boardsList;
    this.scope = 'all';
    this.includeArchivedBoards = false;
    this.selectedBoardIds = new Set();
    this.pickerBoards = null;
    this.pickerBoardsRequest = null;
    this.debounceTimer = null;
    this.loadingTimer = null;
    this.requestController = null;
    this.lastQuery = '';
  }

  render() {
    const panel = document.createElement('section');
    panel.className = 'card-search';
    panel.setAttribute('aria-label', 'Search cards on all boards');
    panel.innerHTML = `
      <form class="card-search-form" id="card-search-form" role="search">
        <label class="visually-hidden" for="card-search-input">Search cards on all boards</label>
        <div class="card-search-input-wrap">
          <svg class="card-search-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="11" cy="11" r="7"></circle>
            <line x1="16.65" y1="16.65" x2="21" y2="21"></line>
          </svg>
          <input
            type="text"
            id="card-search-input"
            class="card-search-input"
            placeholder="Search cards on all boards"
            maxlength="${CARD_SEARCH_MAX_LENGTH}"
            autocomplete="off"
            spellcheck="false"
            aria-describedby="card-search-hint"
          >
          <button type="button" class="card-search-clear-btn" id="card-search-clear-btn" aria-label="Clear search" title="Clear search" hidden>&times;</button>
        </div>
      </form>
      <p class="card-search-hint" id="card-search-hint">Spaces mean AND, commas mean OR, "quotes" match a phrase and #123 finds card 123. Done and archived cards are included.</p>
      <div class="card-search-options">
        <div class="card-search-scope" role="group" aria-label="Boards to search">
          <button type="button" class="card-search-scope-btn" data-scope="all" aria-pressed="true">All boards</button>
          <button type="button" class="card-search-scope-btn" data-scope="chosen" aria-pressed="false">Choose boards</button>
        </div>
        <label class="card-search-archived-option">
          <input type="checkbox" id="card-search-include-archived">
          Include archived boards
        </label>
      </div>
      <fieldset class="card-search-board-picker" id="card-search-board-picker" hidden>
        <legend>Boards to search</legend>
        <div class="card-search-board-options" id="card-search-board-options"></div>
      </fieldset>
      <p class="card-search-status" id="card-search-status" role="status" aria-live="polite"></p>
      <div class="card-search-results" id="card-search-results" hidden></div>
    `;
    this.mount.appendChild(panel);

    this.input = panel.querySelector('#card-search-input');
    this.clearButton = panel.querySelector('#card-search-clear-btn');
    this.archivedCheckbox = panel.querySelector('#card-search-include-archived');
    this.picker = panel.querySelector('#card-search-board-picker');
    this.pickerOptions = panel.querySelector('#card-search-board-options');
    this.status = panel.querySelector('#card-search-status');
    this.results = panel.querySelector('#card-search-results');
    this.scopeButtons = Array.from(panel.querySelectorAll('.card-search-scope-btn'));

    panel.querySelector('#card-search-form').addEventListener('submit', (event) => {
      event.preventDefault();
      this.runSearchNow();
    });
    this.input.addEventListener('input', () => this.handleInput());
    this.input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && this.input.value) {
        event.preventDefault();
        this.clear();
      }
    });
    this.clearButton.addEventListener('click', () => {
      this.clear();
      this.input.focus();
    });
    this.scopeButtons.forEach((button) => {
      button.addEventListener('click', () => this.setScope(button.dataset.scope));
    });
    this.archivedCheckbox.addEventListener('change', () => {
      this.includeArchivedBoards = this.archivedCheckbox.checked;
      if (!this.includeArchivedBoards && this.pickerBoards) {
        // Archived boards leave the picker, so they leave the selection too.
        this.pickerBoards
          .filter((board) => board.archived)
          .forEach((board) => this.selectedBoardIds.delete(board.id));
      }
      this.renderBoardPicker();
      this.runSearchNow();
    });
  }

  getQuery() {
    return (this.input.value || '').trim();
  }

  handleInput() {
    this.clearButton.hidden = !this.input.value;
    clearTimeout(this.debounceTimer);
    const query = this.getQuery();
    if (query.length < CARD_SEARCH_MIN_LENGTH) {
      this.cancelRequest();
      this.showResults(false);
      this.setStatus(query ? `Type at least ${CARD_SEARCH_MIN_LENGTH} characters to search.` : '');
      return;
    }
    this.debounceTimer = setTimeout(() => this.runSearch(), CARD_SEARCH_DEBOUNCE_MS);
  }

  runSearchNow() {
    clearTimeout(this.debounceTimer);
    if (this.getQuery().length >= CARD_SEARCH_MIN_LENGTH) {
      this.runSearch();
    }
  }

  clear() {
    clearTimeout(this.debounceTimer);
    this.cancelRequest();
    this.input.value = '';
    this.clearButton.hidden = true;
    this.lastQuery = '';
    this.setStatus('');
    this.showResults(false);
  }

  async setScope(scope) {
    if (scope !== 'all' && scope !== 'chosen') {
      return;
    }
    this.scope = scope;
    this.scopeButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.scope === scope));
    });
    this.picker.hidden = scope !== 'chosen';
    if (scope === 'chosen') {
      await this.loadPickerBoards();
    }
    this.runSearchNow();
  }

  async loadPickerBoards() {
    if (this.pickerBoards) {
      this.renderBoardPicker();
      return;
    }
    if (!this.pickerBoardsRequest) {
      this.pickerBoardsRequest = this.fetchPickerBoards();
    }
    this.pickerOptions.textContent = 'Loading boards...';
    await this.pickerBoardsRequest;
    this.pickerBoardsRequest = null;
    this.renderBoardPicker();
  }

  async fetchPickerBoards() {
    try {
      const response = await fetch('/api/boards?archived=both', {
        signal: AbortSignal.timeout(CARD_SEARCH_TIMEOUT_MS),
      });
      const data = response.ok ? await response.json() : null;
      if (data && data.success && Array.isArray(data.boards)) {
        this.pickerBoards = data.boards.map((board) => ({
          id: Number(board.id),
          name: String(board.name || ''),
          archived: !!board.archived,
        }));
      }
    } catch (err) {
      console.warn('Could not load boards for search:', err.message);
    }
  }

  renderBoardPicker() {
    if (!this.pickerOptions) {
      return;
    }
    this.pickerOptions.textContent = '';
    if (!this.pickerBoards) {
      this.pickerOptions.textContent = 'Could not load your boards. Try again later.';
      return;
    }

    const boards = this.pickerBoards.filter((board) => this.includeArchivedBoards || !board.archived);
    if (boards.length === 0) {
      this.pickerOptions.textContent = 'No boards to choose from.';
      return;
    }

    boards.forEach((board) => {
      const label = document.createElement('label');
      label.className = 'card-search-board-option';

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = String(board.id);
      checkbox.checked = this.selectedBoardIds.has(board.id);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) {
          this.selectedBoardIds.add(board.id);
        } else {
          this.selectedBoardIds.delete(board.id);
        }
        this.runSearchNow();
      });
      label.appendChild(checkbox);

      const name = document.createElement('span');
      name.textContent = board.name;
      label.appendChild(name);

      if (board.archived) {
        const badge = document.createElement('span');
        badge.className = 'card-search-archived-badge';
        badge.textContent = 'Archived';
        label.appendChild(badge);
      }
      this.pickerOptions.appendChild(label);
    });
  }

  cancelRequest() {
    if (this.requestController) {
      this.requestController.abort();
      this.requestController = null;
    }
    clearTimeout(this.loadingTimer);
    this.loadingTimer = null;
  }

  async runSearch() {
    const query = this.getQuery();
    if (query.length < CARD_SEARCH_MIN_LENGTH) {
      return;
    }

    const params = new URLSearchParams();
    params.set('q', query);
    if (this.scope === 'chosen') {
      if (this.selectedBoardIds.size === 0) {
        this.cancelRequest();
        this.showResults(false);
        this.setStatus('Choose at least one board to search.');
        return;
      }
      params.set('board_ids', Array.from(this.selectedBoardIds).join(','));
    } else if (this.includeArchivedBoards) {
      params.set('include_archived_boards', 'true');
    }

    this.cancelRequest();
    const controller = new AbortController();
    this.requestController = controller;
    const timeoutId = setTimeout(() => controller.abort(), CARD_SEARCH_TIMEOUT_MS);
    this.loadingTimer = setTimeout(() => this.setStatus('Searching...'), CARD_SEARCH_LOADING_DELAY_MS);

    try {
      const response = await fetch(`/api/search/cards?${params.toString()}`, {
        signal: controller.signal,
      });
      const data = await response.json().catch(() => null);
      if (this.requestController !== controller) {
        return;
      }
      if (!response.ok || !data || !data.success) {
        // 400 messages describe the query limits and are safe to show.
        const message = response.status === 400 && data && data.message
          ? data.message
          : 'Search failed. Try again.';
        this.showResults(false);
        this.setStatus(message);
        return;
      }
      this.lastQuery = query;
      this.renderResults(data);
    } catch (err) {
      if (this.requestController !== controller) {
        return;
      }
      this.showResults(false);
      this.setStatus(err.name === 'AbortError'
        ? 'Search took too long. Try a more specific search.'
        : 'Search failed. Check your connection and try again.');
    } finally {
      clearTimeout(timeoutId);
      if (this.requestController === controller) {
        this.requestController = null;
        clearTimeout(this.loadingTimer);
        this.loadingTimer = null;
      }
    }
  }

  setStatus(message) {
    this.status.textContent = message;
  }

  showResults(show) {
    this.results.hidden = !show;
    if (!show) {
      this.results.textContent = '';
    }
    if (this.boardsList) {
      // An inline style, because the grid's display rule beats [hidden].
      this.boardsList.style.display = show ? 'none' : '';
    }
  }

  static cardUrl(boardId, view, cardId) {
    const params = new URLSearchParams();
    params.set('id', String(boardId));
    if (view !== 'task') {
      params.set('view', view);
    }
    params.set('card', String(cardId));
    return `/board.html?${params.toString()}`;
  }

  renderResults(data) {
    const boards = Array.isArray(data.boards) ? data.boards : [];
    const total = Number(data.total) || 0;
    const returned = Number(data.returned) || 0;

    this.results.textContent = '';
    if (total === 0) {
      this.setStatus('No cards match your search.');
      this.showResults(false);
      return;
    }

    const cardWord = total === 1 ? 'card' : 'cards';
    const boardWord = boards.length === 1 ? 'board' : 'boards';
    if (data.truncated) {
      this.setStatus(
        `Showing the ${returned} most recently updated of ${total} matching cards. Refine your search to narrow them down.`
      );
    } else {
      this.setStatus(`${total} ${cardWord} on ${boards.length} ${boardWord}.`);
    }

    boards.forEach((board) => {
      const section = document.createElement('section');
      section.className = 'card-search-board';
      section.dataset.boardId = String(board.id);

      const heading = document.createElement('h4');
      heading.className = 'card-search-board-name';
      const boardLink = document.createElement('a');
      boardLink.href = `/board.html?id=${encodeURIComponent(board.id)}`;
      boardLink.textContent = String(board.name || '');
      heading.appendChild(boardLink);
      if (board.archived) {
        const badge = document.createElement('span');
        badge.className = 'card-search-archived-badge';
        badge.textContent = 'Archived board';
        heading.appendChild(badge);
      }
      section.appendChild(heading);

      (Array.isArray(board.views) ? board.views : []).forEach((viewGroup) => {
        const view = Object.prototype.hasOwnProperty.call(CARD_SEARCH_VIEW_LABELS, viewGroup.view)
          ? viewGroup.view
          : 'task';
        const cards = Array.isArray(viewGroup.cards) ? viewGroup.cards : [];

        const viewBlock = document.createElement('div');
        viewBlock.className = 'card-search-view';
        viewBlock.dataset.view = view;

        const viewHeading = document.createElement('h5');
        viewHeading.textContent = `${CARD_SEARCH_VIEW_LABELS[view]} (${cards.length})`;
        viewBlock.appendChild(viewHeading);

        const list = document.createElement('ul');
        list.className = 'card-search-card-list';
        cards.forEach((card) => {
          const item = document.createElement('li');
          const link = document.createElement('a');
          link.className = 'card-search-card';
          link.href = CardSearchPanel.cardUrl(board.id, view, card.id);
          link.dataset.cardId = String(card.id);

          const cardId = document.createElement('span');
          cardId.className = 'card-search-card-id';
          cardId.textContent = `#${card.id}`;
          link.appendChild(cardId);

          const title = document.createElement('span');
          title.className = 'card-search-card-title';
          title.textContent = String(card.title || '');
          link.appendChild(title);

          const column = document.createElement('span');
          column.className = 'card-search-card-column';
          column.textContent = String(card.column_name || '');
          link.appendChild(column);

          item.appendChild(link);
          list.appendChild(item);
        });
        viewBlock.appendChild(list);
        section.appendChild(viewBlock);
      });

      this.results.appendChild(section);
    });

    this.showResults(true);
  }
}

window.CardSearchPanel = CardSearchPanel;
