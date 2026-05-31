// Boards page functionality
class BoardsManager {
  constructor() {
    this.container = document.getElementById('boards-container');
    this.boards = [];
    this.showArchivedBoards = false;
    this.pendingImportFile = null;
    this.activeModalState = null;
    this.previousBodyOverflow = '';
    this.boundModalKeydownHandler = (event) => this.handleModalKeydown(event);
    this.boundHeaderViewChangedHandler = (event) => this.handleHeaderViewChanged(event);
  }

  async init() {
    // Initialize Permission Manager (no board context for boards list)
    console.log('Initializing PermissionManager for boards page');
    const permissionInitSuccess = await PermissionManager.init();
    
    if (!permissionInitSuccess) {
      console.warn('Failed to initialize PermissionManager - some features may not be available');
    }
    
    // Check for default board setting and redirect if set
    const shouldRedirect = await this.checkDefaultBoard();
    if (shouldRedirect) {
      // Redirecting to default board, skip rendering
      return;
    }
    
    window.addEventListener('viewChanged', this.boundHeaderViewChangedHandler);

    this.render();
    this.configureHeaderViews();
    await this.loadBoards();
  }

  configureHeaderViews() {
    if (!window.header) {
      return;
    }

    const desktopTaskLabel = document.querySelector('.views-dropdown-item[data-view="task"] span');
    if (desktopTaskLabel) {
      desktopTaskLabel.textContent = 'Active Boards';
    }

    const desktopArchivedLabel = document.querySelector('.views-dropdown-item[data-view="archived"] span');
    if (desktopArchivedLabel) {
      desktopArchivedLabel.textContent = 'Archived Boards';
    }

    const mobileTaskItem = document.querySelector('.mobile-view-item[data-view="task"]');
    if (mobileTaskItem) {
      mobileTaskItem.textContent = 'Active Boards';
    }

    const mobileArchivedItem = document.querySelector('.mobile-view-item[data-view="archived"]');
    if (mobileArchivedItem) {
      mobileArchivedItem.textContent = 'Archived Boards';
    }

    const desktopScheduled = document.querySelector('.views-dropdown-item[data-view="scheduled"]');
    if (desktopScheduled) {
      desktopScheduled.style.display = 'none';
    }
    const mobileScheduled = document.querySelector('.mobile-view-item[data-view="scheduled"]');
    if (mobileScheduled) {
      mobileScheduled.style.display = 'none';
    }

    const desktopDone = document.querySelector('.views-dropdown-item[data-view="done"]');
    if (desktopDone) {
      desktopDone.style.display = 'none';
    }
    const mobileDone = document.querySelector('.mobile-view-item[data-view="done"]');
    if (mobileDone) {
      mobileDone.style.display = 'none';
    }

    window.header.showViewsDropdown(true);
    window.header.setView(this.showArchivedBoards ? 'archived' : 'task');
  }

  async handleHeaderViewChanged(event) {
    const requestedView = event?.detail?.view;
    if (requestedView !== 'task' && requestedView !== 'archived') {
      return;
    }

    const nextShowArchived = requestedView === 'archived';
    if (nextShowArchived === this.showArchivedBoards) {
      return;
    }

    this.showArchivedBoards = nextShowArchived;
    await this.loadBoards();
  }

  async checkDefaultBoard() {
    try {
      // Skip redirect if any URL parameters are present (e.g., ?show_boards=1)
      // This allows direct access to boards list when needed
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.toString()) {
        // URL has parameters, skip default board redirect
        return false;
      }
      
      const response = await fetch('/api/settings/default_board');
      
      if (response.ok) {
        const data = await response.json();
        
        if (data.success && data.value) {
          // Redirect to default board
          window.location.href = `/board.html?id=${data.value}`;
          return true; // Indicate redirect is happening
        }
      }
      // If no default board or error, continue to boards list
      return false;
    } catch (err) {
      // If error checking default board, continue to boards list
      console.error('Error checking default board:', err);
      return false;
    }
  }

  render() {
    this.container.innerHTML = `
      <div class="boards-header-panel">
        <div class="boards-header">
          <h3>My Boards</h3>
        </div>
      </div>
      <div id="boards-list" class="loading">
        Loading boards...
      </div>
      
      <!-- New Board Modal -->
      <div id="new-board-modal" class="modal" role="dialog" aria-modal="true" aria-labelledby="new-board-modal-title" aria-describedby="new-board-modal-description">
        <div class="modal-content">
          <div class="modal-header">
            <h3 id="new-board-modal-title">Create New Board</h3>
            <button class="modal-close" id="modal-close">&times;</button>
          </div>
          <p id="new-board-modal-description" class="visually-hidden">Create a new board by entering a name and optional description.</p>
          <form id="new-board-form">
            <div class="form-group">
              <label for="board-name">Board Name</label>
              <input type="text" id="board-name" name="name" required placeholder="Enter board name" autofocus>
            </div>
            <div class="form-group">
              <label for="board-description">Description (optional)</label>
              <textarea id="board-description" name="description" placeholder="Enter board description" rows="3"></textarea>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="cancel-btn">Cancel</button>
              <button type="submit" class="btn btn-primary">Create Board</button>
            </div>
          </form>
        </div>
      </div>
      
      <!-- Edit Board Modal -->
      <div id="edit-board-modal" class="modal" role="dialog" aria-modal="true" aria-labelledby="edit-board-modal-title" aria-describedby="edit-board-modal-description">
        <div class="modal-content">
          <div class="modal-header">
            <h3 id="edit-board-modal-title">Edit Board</h3>
            <button class="modal-close" id="edit-modal-close">&times;</button>
          </div>
          <p id="edit-board-modal-description" class="visually-hidden">Update the selected board name and description.</p>
          <form id="edit-board-form">
            <input type="hidden" id="edit-board-id">
            <div class="form-group">
              <label for="edit-board-name">Board Name</label>
              <input type="text" id="edit-board-name" name="name" required placeholder="Enter board name" autofocus>
            </div>
            <div class="form-group">
              <label for="edit-board-description">Description</label>
              <textarea id="edit-board-description" name="description" placeholder="Enter board description" rows="3"></textarea>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="edit-cancel-btn">Cancel</button>
              <button type="submit" class="btn btn-primary">Save Changes</button>
            </div>
          </form>
        </div>
      </div>

      <!-- Import Board Modal -->
      <div id="import-board-modal" class="modal" role="dialog" aria-modal="true" aria-labelledby="import-board-modal-title" aria-describedby="import-board-modal-description">
        <div class="modal-content">
          <div class="modal-header">
            <h3 id="import-board-modal-title">Import Board</h3>
            <button class="modal-close" id="import-modal-close">&times;</button>
          </div>
          <p id="import-board-modal-description" class="visually-hidden">Import a board from an AFT JSON file. This action validates file structure before importing.</p>
          <form id="import-board-form">
            <div class="form-group">
              <label for="import-board-file">Source File</label>
              <input type="file" id="import-board-file" name="file" accept=".json,application/json" required>
              <small class="form-hint">Only AFT formatted JSON exports are supported.</small>
            </div>
            <div class="import-security-note">
              Import checks file structure, relationship integrity, and security constraints before data is written. User assignees are not mapped yet and imported cards will be unassigned.
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="import-cancel-btn">Cancel</button>
              <button type="submit" class="btn btn-primary" id="import-submit-btn">Import Board</button>
            </div>
          </form>
        </div>
      </div>

      <!-- Import Name Conflict Modal -->
      <div id="import-conflict-modal" class="modal" role="dialog" aria-modal="true" aria-labelledby="import-conflict-modal-title" aria-describedby="import-conflict-message">
        <div class="modal-content">
          <div class="modal-header">
            <h3 id="import-conflict-modal-title">Board Name Already Exists</h3>
            <button class="modal-close" id="import-conflict-close">&times;</button>
          </div>
          <p id="import-conflict-message">A board with this name already exists.</p>
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary" id="import-conflict-cancel-btn">Cancel Import</button>
            <button type="button" class="btn btn-primary" id="import-conflict-append-btn">Import With Suffix</button>
          </div>
        </div>
      </div>
    `;

    // Attach event listeners for new board modal
    document.getElementById('modal-close').addEventListener('click', () => this.closeModal());
    document.getElementById('cancel-btn').addEventListener('click', () => this.closeModal());
    document.getElementById('new-board-form').addEventListener('submit', (e) => this.handleCreateBoard(e));
    
    // Attach event listeners for edit board modal
    document.getElementById('edit-modal-close').addEventListener('click', () => this.closeEditModal());
    document.getElementById('edit-cancel-btn').addEventListener('click', () => this.closeEditModal());
    document.getElementById('edit-board-form').addEventListener('submit', (e) => this.handleEditBoard(e));

    // Import board modal handlers
    document.getElementById('import-modal-close').addEventListener('click', () => this.closeImportModal());
    document.getElementById('import-cancel-btn').addEventListener('click', () => this.closeImportModal());
    document.getElementById('import-board-form').addEventListener('submit', (e) => this.handleImportBoard(e));

    // Import conflict modal handlers
    document.getElementById('import-conflict-close').addEventListener('click', () => this.closeImportConflictModal());
    document.getElementById('import-conflict-cancel-btn').addEventListener('click', () => this.closeImportConflictModal());
    document.getElementById('import-conflict-append-btn').addEventListener('click', async () => {
      await this.retryImportWithSuffix();
    });
    
    // Close modals on backdrop click
    document.getElementById('new-board-modal').addEventListener('click', (e) => {
      if (e.target.id === 'new-board-modal') {
        this.closeModal();
      }
    });
    
    document.getElementById('edit-board-modal').addEventListener('click', (e) => {
      if (e.target.id === 'edit-board-modal') {
        this.closeEditModal();
      }
    });

    document.getElementById('import-board-modal').addEventListener('click', (e) => {
      if (e.target.id === 'import-board-modal') {
        this.closeImportModal();
      }
    });

    document.getElementById('import-conflict-modal').addEventListener('click', (e) => {
      if (e.target.id === 'import-conflict-modal') {
        this.closeImportConflictModal();
      }
    });
  }

  async loadBoards() {
    try {
      this.configureHeaderViews();
      const archivedParam = this.showArchivedBoards ? 'true' : 'false';
      const response = await fetch(`/api/boards?archived=${archivedParam}`);
      let data = null;

      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        data = await response.json();
      }
      
      // Check for authentication errors
      if (response.status === 401) {
        this.showError('Authentication required. Please log in to view your boards.');
        return;
      }
      
      // Check for other HTTP errors
      if (!response.ok) {
        if (response.status === 403) {
          const fallbackMessage = 'You do not have access to any existing boards and you do not have permission to create new boards. Ask an administrator to grant board.view access or the board_creator role.';
          const permissionMessage = data?.message || fallbackMessage;
          this.showError(this.escapeHtml(permissionMessage));
          return;
        }

        const serverMessage = data?.message
          ? `Failed to load boards: ${this.escapeHtml(data.message)}`
          : `Failed to load boards: HTTP ${response.status}`;
        this.showError(serverMessage);
        return;
      }

      if (!data) {
        data = await response.json();
      }
      
      if (data.success) {
        this.boards = data.boards;
        this.renderBoardsList();
      } else {
        this.showError('Failed to load boards: ' + this.escapeHtml(data.message || 'Unknown error'));
      }
    } catch (err) {
      this.showError('Error loading boards: ' + this.escapeHtml(err.message || 'Unknown error'));
    }
  }

  renderBoardsList() {
    const listContainer = document.getElementById('boards-list');
    
    if (this.boards.length === 0) {
      listContainer.className = ''; // Remove grid class
      const emptyTitle = this.showArchivedBoards ? 'No archived boards' : 'No boards yet';
      const emptyMessage = this.showArchivedBoards
        ? 'Archived boards will appear here.'
        : 'Create your first board to get started!';
      listContainer.innerHTML = `
        <div class="empty-state-panel">
          <div class="empty-state">
            <div class="empty-state-icon">📋</div>
            <h3>${emptyTitle}</h3>
            <p>${emptyMessage}</p>
            <div class="empty-state-actions">
              <button class="btn btn-primary" id="empty-state-new-board-btn">+ New Board</button>
              <button class="btn btn-secondary" id="empty-state-import-board-btn">Import Board</button>
            </div>
          </div>
        </div>
      `;
      
      // Add event listener for the empty state button
      const emptyStateNewBoardBtn = document.getElementById('empty-state-new-board-btn');
      if (emptyStateNewBoardBtn) {
        emptyStateNewBoardBtn.addEventListener('click', () => this.openModal());
      }

      const emptyStateImportBoardBtn = document.getElementById('empty-state-import-board-btn');
      if (emptyStateImportBoardBtn) {
        emptyStateImportBoardBtn.addEventListener('click', () => this.openImportModal());
      }
    } else {
      listContainer.className = 'boards-grid';

      // Render board cards using explicit DOM APIs to avoid HTML injection risks.
      listContainer.innerHTML = '';
      this.boards.forEach(board => {
        const card = document.createElement('div');
        card.className = 'board-card';
        card.dataset.boardId = String(board.id);
        card.dataset.canEdit = String(!!board.can_edit);
        card.dataset.canDelete = String(!!board.can_delete);
        card.dataset.canExport = String(!!board.can_export);

        const exportBtn = document.createElement('button');
        exportBtn.className = 'board-export-btn';
        exportBtn.dataset.boardId = String(board.id);
        exportBtn.dataset.boardName = String(board.name || '');
        exportBtn.title = 'Export board';
        exportBtn.setAttribute('aria-label', 'Export board');
        exportBtn.textContent = '⭳';
        card.appendChild(exportBtn);

        const editBtn = document.createElement('button');
        editBtn.className = 'board-edit-btn';
        editBtn.dataset.boardId = String(board.id);
        editBtn.dataset.boardName = String(board.name || '');
        editBtn.dataset.boardDescription = String(board.description || '');
        editBtn.title = 'Edit board';
        editBtn.setAttribute('aria-label', 'Edit board');
        editBtn.textContent = '✎';
        card.appendChild(editBtn);

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'board-delete-btn';
        deleteBtn.dataset.boardId = String(board.id);
        deleteBtn.title = 'Delete board';
        deleteBtn.setAttribute('aria-label', 'Delete board');
        deleteBtn.textContent = '×';
        card.appendChild(deleteBtn);

        const archiveBtn = document.createElement('button');
        archiveBtn.className = board.archived ? 'board-unarchive-btn' : 'board-archive-btn';
        archiveBtn.dataset.boardId = String(board.id);
        archiveBtn.dataset.boardName = String(board.name || '');
        archiveBtn.title = board.archived ? 'Unarchive board' : 'Archive board';
        archiveBtn.setAttribute('aria-label', board.archived ? 'Unarchive board' : 'Archive board');
        archiveBtn.innerHTML = board.archived
          ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <rect x="3" y="4" width="18" height="16" rx="2"></rect>
              <line x1="3" y1="10" x2="21" y2="10"></line>
              <path d="M12 14v-2"></path>
              <path d="M9 14l3 2 3-2"></path>
            </svg>`
          : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <rect x="3" y="4" width="18" height="16" rx="2"></rect>
              <line x1="3" y1="10" x2="21" y2="10"></line>
              <path d="M12 14v2"></path>
              <path d="M9 16l3-2 3 2"></path>
            </svg>`;
        card.appendChild(archiveBtn);

        const title = document.createElement('h4');
        title.textContent = String(board.name || 'Untitled Board');
        card.appendChild(title);

        if (board.description) {
          const description = document.createElement('p');
          description.className = 'board-description';
          description.textContent = String(board.description);
          card.appendChild(description);
        }

        listContainer.appendChild(card);
      });

      const addBoardPlaceholder = document.createElement('div');
      addBoardPlaceholder.className = 'add-board-placeholder';
      const addBoardBtn = document.createElement('button');
      addBoardBtn.className = 'btn btn-primary';
      addBoardBtn.id = 'add-board-inline-btn';
      addBoardBtn.textContent = '+ New Board';
      addBoardPlaceholder.appendChild(addBoardBtn);
      listContainer.appendChild(addBoardPlaceholder);

      const importBoardPlaceholder = document.createElement('div');
      importBoardPlaceholder.className = 'add-board-placeholder import-board-placeholder';
      const importBoardBtn = document.createElement('button');
      importBoardBtn.className = 'btn btn-secondary';
      importBoardBtn.id = 'add-board-import-btn';
      importBoardBtn.textContent = '⇪ Import Board';
      importBoardPlaceholder.appendChild(importBoardBtn);
      listContainer.appendChild(importBoardPlaceholder);
      
      // Apply permission-based rendering to board action buttons
      this.applyPermissionBasedRendering();
      
      // Add event listener for inline add board button
      const addBoardInlineBtn = document.getElementById('add-board-inline-btn');
      if (addBoardInlineBtn) {
        addBoardInlineBtn.addEventListener('click', () => this.openModal());
      }

      const addBoardImportBtn = document.getElementById('add-board-import-btn');
      if (addBoardImportBtn) {
        addBoardImportBtn.addEventListener('click', () => this.openImportModal());
      }

      // Add event listeners for export buttons
      listContainer.querySelectorAll('.board-export-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const boardId = parseInt(e.target.dataset.boardId, 10);
          const boardName = e.target.dataset.boardName || 'board';
          await this.handleBoardExport(boardId, boardName);
        });
      });
      
      // Add event listeners for edit buttons
      listContainer.querySelectorAll('.board-edit-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation(); // Prevent card click
          const boardId = parseInt(e.target.dataset.boardId);
          const boardName = e.target.dataset.boardName;
          const boardDescription = e.target.dataset.boardDescription;
          this.openEditModal(boardId, boardName, boardDescription);
        });
      });
      
      // Add event listeners for delete buttons
      listContainer.querySelectorAll('.board-delete-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation(); // Prevent card click
          this.handleDeleteBoard(parseInt(e.target.dataset.boardId));
        });
      });

      listContainer.querySelectorAll('.board-archive-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation(); // Prevent card click
          const boardId = parseInt(e.currentTarget.dataset.boardId, 10);
          const boardName = e.currentTarget.dataset.boardName || 'this board';
          await this.handleArchiveBoard(boardId, boardName);
        });
      });

      listContainer.querySelectorAll('.board-unarchive-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation(); // Prevent card click
          const boardId = parseInt(e.currentTarget.dataset.boardId, 10);
          const boardName = e.currentTarget.dataset.boardName || 'this board';
          await this.handleUnarchiveBoard(boardId, boardName);
        });
      });
      
      // Add event listeners for board cards
      listContainer.querySelectorAll('.board-card').forEach(card => {
        card.addEventListener('click', (e) => {
          const boardId = e.currentTarget.dataset.boardId;
          window.location.href = `/board.html?id=${boardId}`;
        });
      });
    }
  }

  /**
   * Apply permission-based rendering to board action buttons
   * Removes edit/delete buttons based on backend permission flags and user permissions
   */
  applyPermissionBasedRendering() {
    if (!window.PermissionManager || !PermissionManager.initialized) {
      console.log('PermissionManager not available - using backend permission flags only');
      // Fallback: just use backend flags
      this.applyBackendPermissionFlags();
      return;
    }
    
    console.log('Applying permission-based rendering to board cards...');
    
    // For each board card, check permissions
    document.querySelectorAll('.board-card').forEach(card => {
      const canEdit = card.getAttribute('data-can-edit') === 'true';
      const canDelete = card.getAttribute('data-can-delete') === 'true';
      const canExport = card.getAttribute('data-can-export') === 'true';
      
      const editBtn = card.querySelector('.board-edit-btn');
      const deleteBtn = card.querySelector('.board-delete-btn');
      const exportBtn = card.querySelector('.board-export-btn');
      const archiveBtn = card.querySelector('.board-archive-btn');
      const unarchiveBtn = card.querySelector('.board-unarchive-btn');
      
      // Remove edit button if user doesn't have permission
      // Backend has already calculated board-specific permissions (ownership + roles)
      if (!canEdit) {
        editBtn?.remove();
      }
      
      // Remove delete button if user doesn't have permission
      if (!canDelete) {
        deleteBtn?.remove();
      }

      if (!canExport || !PermissionManager.canCallEndpoint('GET', '/api/boards/:id/export')) {
        exportBtn?.remove();
      }

      const canArchiveBoard = PermissionManager.canCallEndpoint('PATCH', '/api/boards/:id/archive');
      const canUnarchiveBoard = PermissionManager.canCallEndpoint('PATCH', '/api/boards/:id/unarchive');
      if (!canEdit || !canArchiveBoard) {
        archiveBtn?.remove();
      }
      if (!canEdit || !canUnarchiveBoard) {
        unarchiveBtn?.remove();
      }
    });
    
    // Check if user can create boards - if not, remove "New Board" button
    if (!PermissionManager.hasPermission('board.create')) {
      document.getElementById('add-board-inline-btn')?.remove();
      document.getElementById('empty-state-new-board-btn')?.remove();
    }

    if (!PermissionManager.canCallEndpoint('POST', '/api/boards/import')) {
      document.getElementById('add-board-import-btn')?.remove();
      document.getElementById('empty-state-import-board-btn')?.remove();
    }
    
    console.log('Permission-based rendering complete');
  }

  /**
   * Fallback method when PermissionManager is not available
   * Uses backend permission flags only
   */
  applyBackendPermissionFlags() {
    document.querySelectorAll('.board-card').forEach(card => {
      const canEdit = card.getAttribute('data-can-edit') === 'true';
      const canDelete = card.getAttribute('data-can-delete') === 'true';
      const canExport = card.getAttribute('data-can-export') === 'true';
      
      const editBtn = card.querySelector('.board-edit-btn');
      const deleteBtn = card.querySelector('.board-delete-btn');
      const exportBtn = card.querySelector('.board-export-btn');
      const archiveBtn = card.querySelector('.board-archive-btn');
      const unarchiveBtn = card.querySelector('.board-unarchive-btn');
      
      if (!canEdit) {
        editBtn?.remove();
      }
      
      if (!canDelete) {
        deleteBtn?.remove();
      }

      if (!canExport) {
        exportBtn?.remove();
      }

      if (!canEdit) {
        archiveBtn?.remove();
        unarchiveBtn?.remove();
      }
    });
  }

  openModal() {
    this.openModalDialog('new-board-modal', 'board-name');
  }

  closeModal() {
    this.closeModalDialog('new-board-modal');
    document.getElementById('new-board-form').reset();
  }

  async handleCreateBoard(e) {
    e.preventDefault();
    
    const formData = new FormData(e.target);
    const boardName = formData.get('name').trim();
    const boardDescription = formData.get('description')?.trim() || null;
    
    if (!boardName) {
      this.showErrorToast('Please enter a board name');
      return;
    }

    try {
      const response = await fetch('/api/boards', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name: boardName, description: boardDescription })
      });

      const data = await response.json();

      if (data.success) {
        this.closeModal();
        await this.loadBoards();
        
        // Update header status and boards dropdown if available
        if (window.header) {
          window.header.checkDatabaseStatus();
          window.header.loadBoardsDropdown();
        }
      } else {
        this.showErrorToast('Failed to create board: ' + data.message);
      }
    } catch (err) {
      this.showErrorToast('Error creating board: ' + err.message);
    }
  }

  async handleDeleteBoard(boardId) {
    if (!await showConfirm('Are you sure you want to delete this board?', 'Confirm Deletion')) {
      return;
    }

    try {
      const response = await fetch(`/api/boards/${boardId}`, {
        method: 'DELETE'
      });

      const data = await response.json();

      if (data.success) {
        await this.loadBoards();
        
        // Update header status and boards dropdown if available
        if (window.header) {
          window.header.checkDatabaseStatus();
          window.header.loadBoardsDropdown();
        }
      } else {
        this.showErrorToast('Failed to delete board: ' + data.message);
      }
    } catch (err) {
      this.showErrorToast('Error deleting board: ' + err.message);
    }
  }

  async handleArchiveBoard(boardId, boardName) {
    if (!await showConfirm(`Archive ${boardName}?`, 'Confirm Archive')) {
      return;
    }

    try {
      const response = await fetch(`/api/boards/${boardId}/archive`, {
        method: 'PATCH'
      });

      const data = await response.json();

      if (data.success) {
        await this.loadBoards();
        if (window.header) {
          window.header.loadBoardsDropdown();
        }
      } else {
        this.showErrorToast('Failed to archive board: ' + (data.message || 'Unknown error'));
      }
    } catch (err) {
      this.showErrorToast('Error archiving board: ' + err.message);
    }
  }

  async handleUnarchiveBoard(boardId, boardName) {
    if (!await showConfirm(`Unarchive ${boardName}?`, 'Confirm Unarchive')) {
      return;
    }

    try {
      const response = await fetch(`/api/boards/${boardId}/unarchive`, {
        method: 'PATCH'
      });

      const data = await response.json();

      if (data.success) {
        await this.loadBoards();
        if (window.header) {
          window.header.loadBoardsDropdown();
        }
      } else {
        this.showErrorToast('Failed to unarchive board: ' + (data.message || 'Unknown error'));
      }
    } catch (err) {
      this.showErrorToast('Error unarchiving board: ' + err.message);
    }
  }

  openEditModal(boardId, boardName, boardDescription) {
    document.getElementById('edit-board-id').value = boardId;
    document.getElementById('edit-board-name').value = boardName;
    document.getElementById('edit-board-description').value = boardDescription || '';
    this.openModalDialog('edit-board-modal', 'edit-board-name');
  }

  closeEditModal() {
    this.closeModalDialog('edit-board-modal');
    document.getElementById('edit-board-form').reset();
  }

  openImportModal() {
    this.openModalDialog('import-board-modal', 'import-board-file');
  }

  closeImportModal() {
    this.closeModalDialog('import-board-modal');
    this.pendingImportFile = null;
    document.getElementById('import-board-form').reset();
    const submitBtn = document.getElementById('import-submit-btn');
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Import Board';
    }
  }

  openImportConflictModal(message) {
    const messageElement = document.getElementById('import-conflict-message');
    if (messageElement) {
      messageElement.textContent = message;
    }
    this.openModalDialog('import-conflict-modal', 'import-conflict-cancel-btn');
  }

  closeImportConflictModal() {
    this.closeModalDialog('import-conflict-modal');
    this.pendingImportFile = null;
  }

  openModalDialog(modalId, initialFocusElementId) {
    const modal = document.getElementById(modalId);
    if (!modal) {
      return;
    }

    const triggerElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    this.activeModalState = {
      id: modalId,
      triggerElement,
    };

    if (!this.previousBodyOverflow) {
      this.previousBodyOverflow = document.body.style.overflow || '';
    }

    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', this.boundModalKeydownHandler);

    const initialElement = initialFocusElementId
      ? document.getElementById(initialFocusElementId)
      : null;
    if (initialElement && typeof initialElement.focus === 'function') {
      initialElement.focus();
    }
  }

  closeModalDialog(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) {
      return;
    }

    modal.classList.remove('active');

    if (this.activeModalState && this.activeModalState.id === modalId) {
      const { triggerElement } = this.activeModalState;
      this.activeModalState = null;
      document.removeEventListener('keydown', this.boundModalKeydownHandler);
      document.body.style.overflow = this.previousBodyOverflow;
      this.previousBodyOverflow = '';

      if (triggerElement && document.body.contains(triggerElement) && typeof triggerElement.focus === 'function') {
        triggerElement.focus();
      }
    }
  }

  handleModalKeydown(event) {
    if (!this.activeModalState) {
      return;
    }

    const modal = document.getElementById(this.activeModalState.id);
    if (!modal || !modal.classList.contains('active')) {
      return;
    }

    if (event.key === 'Escape') {
      event.preventDefault();
      if (this.activeModalState.id === 'new-board-modal') {
        this.closeModal();
      } else if (this.activeModalState.id === 'edit-board-modal') {
        this.closeEditModal();
      } else if (this.activeModalState.id === 'import-board-modal') {
        this.closeImportModal();
      } else if (this.activeModalState.id === 'import-conflict-modal') {
        this.closeImportConflictModal();
      }
      return;
    }

    if (event.key === 'Tab') {
      this.trapModalFocus(event, modal);
    }
  }

  trapModalFocus(event, modal) {
    const focusableSelectors = [
      'a[href]',
      'button:not([disabled])',
      'textarea:not([disabled])',
      'input:not([disabled])',
      'select:not([disabled])',
      '[tabindex]:not([tabindex="-1"])'
    ];
    const focusableElements = Array.from(
      modal.querySelectorAll(focusableSelectors.join(','))
    ).filter((element) => element.offsetParent !== null);

    if (focusableElements.length === 0) {
      return;
    }

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];

    if (event.shiftKey && document.activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
      return;
    }

    if (!event.shiftKey && document.activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  }

  validateAftImportStructure(payload) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      return 'Import file must contain a JSON object';
    }

    const requiredKeys = [
      'export',
      'board',
      'board_settings',
      'columns',
      'cards',
      'card_secondary_assignees',
      'checklists',
      'comments',
      'scheduled_cards'
    ];

    for (const key of requiredKeys) {
      if (!(key in payload)) {
        return `Missing required key: ${key}`;
      }
    }

    if (!payload.export || payload.export.format !== 'aft-board') {
      return 'Only AFT formatted JSON exports are supported';
    }

    if (!payload.board || typeof payload.board.name !== 'string' || !payload.board.name.trim()) {
      return 'Board name is required in import payload';
    }

    return null;
  }

  async handleImportBoard(e) {
    e.preventDefault();

    const fileInput = document.getElementById('import-board-file');
    const submitBtn = document.getElementById('import-submit-btn');
    const file = fileInput?.files?.[0];

    if (!file) {
      this.showErrorToast('Please choose a JSON export file to import');
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Validating...';

    try {
      const fileText = await file.text();
      let parsedPayload = null;
      try {
        parsedPayload = JSON.parse(fileText);
      } catch (error) {
        this.showErrorToast('Import file is not valid JSON');
        return;
      }

      const integrityError = this.validateAftImportStructure(parsedPayload);
      if (integrityError) {
        this.showErrorToast(`Import integrity check failed: ${integrityError}`);
        return;
      }

      submitBtn.textContent = 'Importing...';
      await this.submitImportFile(file, 'cancel');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Import Board';
    }
  }

  async submitImportFile(file, duplicateStrategy) {
    const formData = new FormData();
    formData.append('file', file, file.name);
    formData.append('duplicate_strategy', duplicateStrategy);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    let response = null;
    let data = null;

    try {
      response = await fetch('/api/boards/import', {
        method: 'POST',
        body: formData,
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      data = await this.parseJsonResponse(response);
    } catch (error) {
      clearTimeout(timeoutId);
      if (error.name === 'AbortError') {
        this.showErrorToast('Import timed out after 5 seconds. Please try again.');
        return;
      }
      throw error;
    }

    if (response.status === 409 && data?.requires_confirmation) {
      this.pendingImportFile = file;
      const conflictMessage = data.message || 'A board with this name already exists.';
      this.closeModalDialog('import-board-modal');
      this.openImportConflictModal(conflictMessage);
      return;
    }

    if (!response.ok || !data?.success) {
      const message = data?.message || `Import failed with status ${response.status}`;
      this.showErrorToast(message);
      return;
    }

    this.closeImportModal();
    this.closeImportConflictModal();
    await this.loadBoards();

    if (window.header) {
      window.header.checkDatabaseStatus();
      window.header.loadBoardsDropdown();
    }

    this.showSuccessToast(`Board imported successfully: ${data.board?.name || 'Imported board'}`, 4000);
  }

  async parseJsonResponse(response) {
    try {
      return await response.json();
    } catch (error) {
      return { success: false, message: 'Unexpected server response' };
    }
  }

  async retryImportWithSuffix() {
    if (!this.pendingImportFile) {
      this.showErrorToast('No pending import found. Please select a file again.');
      this.closeImportConflictModal();
      return;
    }

    await this.submitImportFile(this.pendingImportFile, 'append_suffix');
  }

  async handleBoardExport(boardId, boardName) {
    try {
      // Use direct browser navigation so Content-Disposition download handling
      // is performed by the browser without injecting untrusted data into the DOM.
      window.location.assign(`/api/boards/${boardId}/export`);
    } catch (error) {
      console.error('Error exporting board:', error, boardName);
      this.showErrorToast('Error exporting board');
    }
  }

  async handleEditBoard(e) {
    e.preventDefault();
    
    const boardId = document.getElementById('edit-board-id').value;
    const formData = new FormData(e.target);
    const boardName = formData.get('name').trim();
    const boardDescription = formData.get('description')?.trim() || '';
    
    if (!boardName) {
      this.showErrorToast('Please enter a board name');
      return;
    }

    try {
      const response = await fetch(`/api/boards/${boardId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name: boardName, description: boardDescription })
      });

      const data = await response.json();

      if (data.success) {
        this.closeEditModal();
        await this.loadBoards();
        
        // Update header status and boards dropdown if available
        if (window.header) {
          window.header.checkDatabaseStatus();
          window.header.loadBoardsDropdown();
        }
      } else {
        this.showErrorToast('Failed to update board: ' + data.message);
      }
    } catch (err) {
      this.showErrorToast('Error updating board: ' + err.message);
    }
  }

  showError(message) {
    const listContainer = document.getElementById('boards-list');
    console.error('Boards page error:', message);
    listContainer.innerHTML = '';

    const wrapper = document.createElement('div');
    wrapper.className = 'empty-state';

    const icon = document.createElement('div');
    icon.className = 'empty-state-icon';
    icon.textContent = '⚠️';

    const title = document.createElement('h3');
    title.textContent = 'Error';

    const paragraph = document.createElement('p');
    paragraph.textContent = 'Unable to load boards right now.';

    wrapper.appendChild(icon);
    wrapper.appendChild(title);
    wrapper.appendChild(paragraph);
    listContainer.appendChild(wrapper);
  }

  /**
   * Show a non-blocking error toast notification.
   * @param {string} message - Error message to display
   * @param {number} duration - How long to show the toast in milliseconds (default 3000)
   */
  showErrorToast(message, duration = 3000) {
    if (message) {
      console.error(message);
    }

    const toast = document.createElement('div');
    toast.className = 'error-toast';
    const fallbackMessage = 'Operation failed. Please try again.';
    const safeMessage =
      typeof message === 'string' && message.trim().length > 0
        ? this.sanitizePlainText(message)
        : fallbackMessage;
    toast.textContent = safeMessage;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.style.cssText = `
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: #e74c3c;
      color: white;
      padding: 12px 20px;
      border-radius: 5px;
      box-shadow: 0 4px 8px rgba(0,0,0,0.3);
      z-index: 10000;
      animation: slideIn 0.3s ease-out;
      max-width: 400px;
      word-wrap: break-word;
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
      toast.style.animation = 'slideOut 0.3s ease-in';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  showSuccessToast(message, duration = 3000) {
    if (message) {
      console.log(message);
    }

    const toast = document.createElement('div');
    toast.className = 'success-toast';
    const safeMessage = message
      ? this.sanitizePlainText(message)
      : 'Operation completed successfully.';
    toast.textContent = safeMessage;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.style.cssText = `
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: #27ae60;
      color: white;
      padding: 12px 20px;
      border-radius: 5px;
      box-shadow: 0 4px 8px rgba(0,0,0,0.3);
      z-index: 10000;
      animation: slideIn 0.3s ease-out;
      max-width: 400px;
      word-wrap: break-word;
    `;

    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.animation = 'slideOut 0.3s ease-in';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  sanitizePlainText(text) {
    const raw = typeof text === 'string' ? text : String(text ?? '');
    return raw.replace(/[\u0000-\u001F\u007F]/g, '').slice(0, 2000);
  }
}

// Initialize boards manager when DOM is ready
document.addEventListener('DOMContentLoaded', async () => {
  if (window.authBootstrapPromise) {
    const canContinue = await window.authBootstrapPromise;
    if (!canContinue) {
      return;
    }
  }

  const boardsManager = new BoardsManager();
  boardsManager.init();
});
