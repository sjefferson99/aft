// Board detail page functionality

const COLUMN_AUTO_SCROLL_EDGE_THRESHOLD_PX = 56;
const COLUMN_AUTO_SCROLL_HOVER_DELAY_MS = 500;
const COLUMN_AUTO_SCROLL_BASE_STEP_PX = 6;
const COLUMN_AUTO_SCROLL_MAX_EXTRA_STEP_PX = 12;
const COLUMN_AUTO_SCROLL_MIN_STEP_PX = 4;
const MOBILE_BOARD_TOUCH_SCROLL_BREAKPOINT_PX = 900;
const MOBILE_BOARD_TOUCH_SCROLL_LOCK_THRESHOLD_PX = 8;
const MOBILE_CARD_LONG_PRESS_DELAY_MS = 500;
const MOBILE_CARD_LONG_PRESS_MOVE_TOLERANCE_PX = 10;
const BOARD_LOADING_OVERLAY_DELAY_MS = 500;
const INITIAL_BOARD_LOAD_TIMEOUT_MS = 15000;
const SUBSEQUENT_BOARD_LOAD_TIMEOUT_MS = 10000;
const MAX_INITIAL_BOARD_LOAD_ATTEMPTS = 2;
const BOARD_SEARCH_TOOLTIP_FALLBACK_TEXT = 'Search cards using spaces (AND), commas (OR), and quoted phrases for exact matches.';

/**
 * Calculate the percentage of checked items in a checklist
 * @param {Array} items - Array of checklist items with 'checked' property
 * @returns {number} Percentage (0-100) of checked items
 */
function calculateChecklistPercentage(items) {
  if (!items || items.length === 0) return 0;
  const checkedCount = items.filter(i => i.checked).length;
  return Math.round((checkedCount / items.length) * 100);
}

/**
 * Setup modal background click handler that ignores text selection drags
 * Prevents modal from closing when user drags to select text and releases outside modal
 * @param {HTMLElement} modal - The modal element
 * @param {Function} closeHandler - Function to call when modal should close (e.g., handleCancel or modal.remove)
 *                                  Can be async - promise rejections are handled gracefully
 */
function setupModalBackgroundClose(modal, closeHandler) {
  let mouseDownOnBackground = false;
  
  modal.addEventListener('mousedown', (e) => {
    // Track if mousedown was on the background (not on modal content)
    mouseDownOnBackground = e.target === modal;
  });
  
  modal.addEventListener('click', async (e) => {
    // Only close if:
    // 1. Click target is the background
    // 2. Mousedown also started on the background (not a drag from inside)
    if (e.target === modal && mouseDownOnBackground) {
      try {
        // Handle both sync and async closeHandler functions
        await closeHandler();
      } catch (error) {
        console.error('Error in modal close handler:', error);
        // Don't close modal if there was an error
      }
    }
    mouseDownOnBackground = false;
  });
}

/**
 * Convert URLs in text to clickable hyperlinks
 * @param {string} text - Text that may contain URLs
 * @returns {string} HTML with URLs converted to links
 */
function linkifyUrls(text) {
  if (!text) return '';
  
  // More robust URL regex that handles parentheses and various URL formats
  // Matches: protocol, domain, path with balanced parentheses, query strings, fragments
  const urlRegex = /https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b[-a-zA-Z0-9()@:%_\+.~#?&\/=]*/gi;
  
  return text.replace(urlRegex, (url) => {
    // Clean up trailing punctuation, but preserve closing parentheses if there's a matching opening one
    let cleanUrl = url;
    
    // Count parentheses in the URL
    const openParens = (cleanUrl.match(/\(/g) || []).length;
    const closeParens = (cleanUrl.match(/\)/g) || []).length;
    
    // If unbalanced closing parens at the end, remove them
    while (cleanUrl.endsWith(')') && (cleanUrl.match(/\)/g) || []).length > (cleanUrl.match(/\(/g) || []).length) {
      cleanUrl = cleanUrl.slice(0, -1);
    }
    
    // Remove other trailing punctuation
    cleanUrl = cleanUrl.replace(/[.,;!?]+$/, '');
    
    // Escape the URL for use in HTML attribute to prevent XSS
    const escapedUrl = cleanUrl.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    // Escape the display text for HTML context
    const displayUrl = cleanUrl.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return `<a href="${escapedUrl}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">${displayUrl}</a>`;
  });
}

function appendLinkifiedText(container, text) {
  if (!container) return;

  const rawText = typeof text === 'string' ? text : String(text ?? '');
  container.textContent = '';

  if (!rawText) {
    return;
  }

  const urlRegex = /https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b[-a-zA-Z0-9()@:%_\+.~#?&\/=]*/gi;

  const normalizeUrl = (url) => {
    let cleanUrl = url;

    while (cleanUrl.endsWith(')') && (cleanUrl.match(/\)/g) || []).length > (cleanUrl.match(/\(/g) || []).length) {
      cleanUrl = cleanUrl.slice(0, -1);
    }

    cleanUrl = cleanUrl.replace(/[.,;!?]+$/, '');
    return cleanUrl;
  };

  let lastIndex = 0;
  let match;

  while ((match = urlRegex.exec(rawText)) !== null) {
    const matchedUrl = match[0];
    const cleanUrl = normalizeUrl(matchedUrl);
    const startIndex = match.index;
    const cleanUrlEndIndex = startIndex + cleanUrl.length;
    const originalMatchEndIndex = startIndex + matchedUrl.length;

    if (startIndex > lastIndex) {
      container.appendChild(document.createTextNode(rawText.slice(lastIndex, startIndex)));
    }

    const link = document.createElement('a');
    link.href = cleanUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = cleanUrl;
    link.addEventListener('click', (event) => event.stopPropagation());
    container.appendChild(link);

    if (cleanUrlEndIndex < originalMatchEndIndex) {
      container.appendChild(document.createTextNode(rawText.slice(cleanUrlEndIndex, originalMatchEndIndex)));
    }

    lastIndex = originalMatchEndIndex;
  }

  if (lastIndex < rawText.length) {
    container.appendChild(document.createTextNode(rawText.slice(lastIndex)));
  }
}

// Shared checklist management helper
class ChecklistManager {
  constructor(container, pendingItems, options = {}) {
    this.container = container;
    this.pendingItems = pendingItems;
    this.updateSummary = options.updateSummary || (() => {});
    this.onItemCommitted = options.onItemCommitted || (() => {});
    this.onItemAdded = options.onItemAdded || (() => {});
    this.onItemChanged = options.onItemChanged || (() => {});
    this.deleteButtonClass = options.deleteButtonClass || 'checklist-delete-btn-temp';
    
    // Set up event delegation
    this.setupEventDelegation();
  }

  setupEventDelegation() {
    // Single event listener on container for all checkboxes
    this.container.addEventListener('change', (e) => {
      if (e.target.classList.contains('checklist-checkbox')) {
        const tempId = Number(e.target.getAttribute('data-temp-id'));
        const item = this.pendingItems.find(i => i.tempId === tempId);
        if (item) {
          item.checked = e.target.checked;
          this.onItemChanged();
          this.updateSummary();
        }
      }
    });

    // Single event listener for delete buttons
    this.container.addEventListener('click', (e) => {
      if (e.target.matches(`.${this.deleteButtonClass}`)) {
        const tempId = Number(e.target.getAttribute('data-temp-id'));
        const index = this.pendingItems.findIndex(i => i.tempId === tempId);
        if (index > -1) {
          this.pendingItems.splice(index, 1);
        }
        e.target.closest('.checklist-item').remove();
        this.onItemChanged();
        this.updateSummary();
      }
    });

    // Single event listener for edit buttons
    this.container.addEventListener('click', (e) => {
      if (e.target.matches('.checklist-edit-btn')) {
        const tempId = Number(e.target.getAttribute('data-temp-id'));
        const itemElement = e.target.closest('.checklist-item');
        const nameSpan = itemElement.querySelector('.checklist-item-name');
        
        // If there's no name span yet, the item is still in edit mode
        if (!nameSpan) {
          return;
        }
        
        const currentName = nameSpan.textContent;
        
        // Replace span with input for inline editing
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'checklist-item-input';
        input.value = currentName;
        input.setAttribute('data-temp-id', tempId);
        input.setAttribute('data-editing', 'true'); // Flag to indicate edit mode
        nameSpan.replaceWith(input);
        input.focus();
        input.select();
        
        // Disable dragging while editing
        itemElement.draggable = false;
      }
    });

    // Single event listener for blur on inputs
    this.container.addEventListener('blur', (e) => {
      if (e.target.classList.contains('checklist-item-input')) {
        const isEditing = e.target.getAttribute('data-editing') === 'true';
        
        if (isEditing) {
          // This is an edited item - save changes
          const tempId = Number(e.target.getAttribute('data-temp-id'));
          const itemElement = e.target.closest('.checklist-item');
          const newName = e.target.value.trim();
          const currentName = e.target.value; // original value
          
          // Get the original name before editing
          const item = this.pendingItems.find(i => i.tempId === tempId);
          const originalName = item ? item.name : '';
          
          if (newName && newName !== originalName) {
            // Update the item in the array
            if (item) {
              item.name = newName;
            }
            this.onItemChanged();
          }
          
          // Replace input with name span
          const nameToDisplay = newName || originalName;
          const newNameSpan = this.createNameSpan(nameToDisplay);
          e.target.replaceWith(newNameSpan);
          
          // Re-enable dragging
          if (itemElement) {
            itemElement.draggable = true;
          }
        } else {
          // This is a new item being committed - use the existing logic
          // Defer to next event loop cycle to allow other events (like delete button clicks) to process first
          setTimeout(() => this.commitInput(e.target), 0);
        }
      }
    }, true); // Use capture to catch blur

    // Listen for commit complete event to trigger adding new item
    this.container.addEventListener('checklistItemCommitted', (e) => {
      if (e.detail.addItemAfter) {
        this.addItemAfter(e.detail.addItemAfter);
      }
    });

    // Single event listener for Enter key on inputs
    this.container.addEventListener('keydown', (e) => {
      if (e.target.classList.contains('checklist-item-input')) {
        const isEditing = e.target.getAttribute('data-editing') === 'true';
        
        if (e.key === 'Enter') {
          e.preventDefault();
          
          if (isEditing) {
            // For edited items, keep edit mode so blur uses update path.
            e.target.blur();
          } else {
            // For new items, use existing logic
            const inputValue = e.target.value.trim();
            const tempId = Number(e.target.getAttribute('data-temp-id'));
            
            // Mark that we want to add an item after this one commits
            if (inputValue) {
              e.target.dataset.addItemAfterCommit = 'true';
            }
            
            // Trigger commit
            e.target.blur();
          }
        } else if (e.key === 'Escape' && isEditing) {
          // Cancel edit by removing the input and restoring name span
          e.preventDefault();
          e.stopPropagation();
          
          const itemElement = e.target.closest('.checklist-item');
          const tempId = Number(e.target.getAttribute('data-temp-id'));
          const item = this.pendingItems.find(i => i.tempId === tempId);
          const originalName = item ? item.name : '';
          
          // Replace input with name span (restore original)
          const newNameSpan = this.createNameSpan(originalName);
          e.target.replaceWith(newNameSpan);
          
          // Re-enable dragging
          if (itemElement) {
            itemElement.draggable = true;
          }
        }
      }
    });

  }

  createNameSpan(text) {
    const span = document.createElement('span');
    span.className = 'checklist-item-name';
    span.textContent = text;
    return span;
  }

  addEditButtonToItem(itemElement, tempId) {
    const actionsContainer = itemElement.querySelector('.checklist-item-actions');
    if (actionsContainer) {
      // Prevent duplicate edit buttons when an item is edited repeatedly.
      const existingEditBtn = actionsContainer.querySelector(`.checklist-edit-btn[data-temp-id="${tempId}"]`);
      if (existingEditBtn) {
        return;
      }

      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'checklist-edit-btn';
      editBtn.setAttribute('data-temp-id', tempId);
      editBtn.title = 'Edit';
      editBtn.textContent = '✎';
      // Insert edit button before delete button
      actionsContainer.insertBefore(editBtn, actionsContainer.firstChild);
    }
  }

  commitInput(inputElement) {
    if (!inputElement || !inputElement.classList.contains('checklist-item-input')) return;
    
    const name = inputElement.value.trim();
    const tempId = Number(inputElement.getAttribute('data-temp-id'));
    const shouldAddItemAfter = inputElement.dataset.addItemAfterCommit === 'true';
    
    if (name) {
      const item = this.pendingItems.find(i => i.tempId === tempId);
      if (item) {
        item.name = name;
        
        // Replace input with display span
        const itemElement = inputElement.closest('.checklist-item');
        const nameSpan = this.createNameSpan(name);
        inputElement.replaceWith(nameSpan);
        
        // Add edit button now that item has a name
        this.addEditButtonToItem(itemElement, tempId);
        
        // Re-enable dragging
        itemElement.draggable = true;
        
        this.updateSummary();
        this.onItemCommitted(tempId);
        
        // Dispatch event to signal commit is complete
        if (shouldAddItemAfter) {
          this.container.dispatchEvent(new CustomEvent('checklistItemCommitted', {
            detail: { tempId, addItemAfter: true }
          }));
        }
      }
    } else {
      // Remove empty item
      const index = this.pendingItems.findIndex(i => i.tempId === tempId);
      if (index > -1) {
        this.pendingItems.splice(index, 1);
      }
      inputElement.closest('.checklist-item').remove();
      this.updateSummary();
    }
  }

  createItemElement(tempId) {
    const item = {
      name: '',
      checked: false,
      tempId: tempId
    };

    const itemHtml = `
      <div class="checklist-item" data-temp-id="${tempId}" draggable="false">
        <span class="drag-handle" title="Drag to reorder">&#9776;</span>
        <input type="checkbox" class="checklist-checkbox" data-temp-id="${tempId}">
        <input type="text" class="checklist-item-input" data-temp-id="${tempId}" placeholder="Enter item name...">
        <div class="checklist-item-actions">
          <button type="button" class="${this.deleteButtonClass}" data-temp-id="${tempId}" title="Delete">🗑</button>
        </div>
      </div>
    `;

    return { item, itemHtml };
  }

  focusNewItem(tempId) {
    const newInput = this.container.querySelector(`input.checklist-item-input[data-temp-id="${tempId}"]`);
    if (newInput) {
      newInput.focus();
    }
  }

  addItem(insertAtTop = false) {
    const tempId = Date.now() + Math.random();
    const { item, itemHtml } = this.createItemElement(tempId);

    if (insertAtTop) {
      this.pendingItems.unshift(item);
      this.container.insertAdjacentHTML('afterbegin', itemHtml);
    } else {
      this.pendingItems.push(item);
      this.container.insertAdjacentHTML('beforeend', itemHtml);
    }

    this.focusNewItem(tempId);
    this.onItemAdded();
    this.updateSummary();
  }

  addItemAfter(afterTempId) {
    const tempId = Date.now() + Math.random();
    const { item, itemHtml } = this.createItemElement(tempId);

    // Find the index of the item to insert after
    const afterIndex = this.pendingItems.findIndex(i => i.tempId === afterTempId);
    if (afterIndex !== -1) {
      this.pendingItems.splice(afterIndex + 1, 0, item);
    } else {
      this.pendingItems.push(item);
    }

    // Find the DOM element to insert after
    const afterElement = this.container.querySelector(`.checklist-item[data-temp-id="${afterTempId}"]`);
    if (afterElement) {
      afterElement.insertAdjacentHTML('afterend', itemHtml);
    } else {
      this.container.insertAdjacentHTML('beforeend', itemHtml);
    }

    this.focusNewItem(tempId);
    this.onItemAdded();
    this.updateSummary();
  }
}

/**
 * WebSocket Manager for Real-Time Board Updates
 * 
 * Manages Socket.IO connections for real-time board synchronization across clients.
 * Handles reconnection logic, event emission, and incoming event handlers.
 */
class WebSocketManager {
  /**
   * Initialize WebSocket manager
   * 
   * Args:
   *   boardId: The board ID to connect to
   *   boardManager: Reference to the BoardManager instance
   */
  constructor(boardId, boardManager) {
    this.boardId = boardId;
    this.boardManager = boardManager;
    this.socket = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = Infinity; // Infinite retries - Socket.IO handles exponential backoff internally
    this.reconnectDelay = 1000; // Socket.IO manages reconnection delays
    
    this.initializeConnection();
  }

  /**
   * Initialize WebSocket connection with auto-reconnection.
   * 
   * Sets up Socket.IO client with reconnection strategy and event listeners.
   */
  initializeConnection() {
    // Check if Socket.IO library is loaded
    if (typeof io === 'undefined') {
      console.error('❌ Socket.IO library not loaded! Make sure socket.io.js script is included.');
      return;
    }
    
    // Connect to the current server (socket.io client auto-detects the URL)
    // Don't pass a URL - let socket.io auto-detect it
    this.socket = io({
      reconnection: true,
      reconnectionDelay: this.reconnectDelay,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: this.maxReconnectAttempts,
      transports: ['websocket', 'polling']
    });

    // Notify any listeners that socket was created (e.g., header.js for immediate event updates)
    // This callback is optional - listeners should check if it exists before setting it
    if (typeof this.onSocketCreated === 'function') {
      try {
        this.onSocketCreated(this.socket);
      } catch (error) {
        console.error('Error in onSocketCreated callback:', error);
      }
    }

    this.setupEventListeners();
  }

  setupEventListeners() {
    // Connection events
    this.socket.on('connect', () => {
      this.reconnectAttempts = 0;
      this.joinBoard();
      this.joinThemeRoom();
      // Update header status immediately when WebSocket connects
      if (window.header) {
        window.header.updateWebSocketStatus();
        window.header.checkDatabaseStatus();
      }
    });

    this.socket.on('disconnect', () => {
      // Update header status immediately when WebSocket disconnects
      if (window.header) {
        window.header.updateWebSocketStatus();
      }
    });

    this.socket.on('connect_error', (error) => {
      // Connection error occurred
    });

    // Board room events
    this.socket.on('room_joined', (data) => {
      // Joined board room
    });
    this.socket.on('card_created', (data) => {
      this.handleCardCreated(data);
    });
    this.socket.on('card_updated', (data) => {
      this.handleCardUpdated(data);
    });
    this.socket.on('card_deleted', (data) => {
      this.handleCardDeleted(data);
    });
    this.socket.on('card_moved', (data) => {
      this.handleCardMoved(data);
    });
    this.socket.on('cards_moved', (data) => {
      this.handleCardsMoved(data);
    });
    this.socket.on('column_reordered', (data) => {
      this.handleColumnReordered(data);
    });
    this.socket.on('column_created', (data) => {
      this.handleColumnCreated(data);
    });
    this.socket.on('column_deleted', (data) => {
      this.handleColumnDeleted(data);
    });
    this.socket.on('checklist_item_added', (data) => {
      this.handleChecklistItemAdded(data);
    });
    this.socket.on('checklist_item_updated', (data) => {
      this.handleChecklistItemUpdated(data);
    });
    this.socket.on('checklist_item_deleted', (data) => {
      this.handleChecklistItemDeleted(data);
    });
    this.socket.on('column_updated', (data) => {
      this.handleColumnUpdated(data);
    });
    this.socket.on('card_archived', (data) => {
      this.handleCardArchived(data);
    });
    this.socket.on('card_unarchived', (data) => {
      this.handleCardUnarchived(data);
    });
    
    // Theme room events
    this.socket.on('theme_changed', (data) => {
      this.handleThemeChanged(data);
    });
    this.socket.on('theme_updated', (data) => {
      this.handleThemeChanged(data);
    });
  }

  /**
   * Join the board room for real-time board updates.
   */
  joinBoard() {
    if (this.socket && this.socket.connected) {
      this.socket.emit('join_board', { board_id: this.boardId });
    }
  }

  /**
   * Join the theme room to receive theme update notifications.
   */
  joinThemeRoom() {
    if (this.socket && this.socket.connected) {
      this.socket.emit('join_theme');
    } else {
      console.warn('Cannot join theme room - socket not connected');
    }
  }

  /**
   * Leave the board room.
   */
  leaveBoard() {
    if (this.socket && this.socket.connected) {
      this.socket.emit('leave_board', { board_id: this.boardId });
    }
  }

  // Event emission methods for local changes
  emitCardCreated(columnId, cardId, cardData) {
    this.socket.emit('card_created', {
      board_id: this.boardId,
      column_id: columnId,
      card_id: cardId,
      card_data: cardData
    });
  }

  emitCardUpdated(cardId, columnId, cardData) {
    this.socket.emit('card_updated', {
      board_id: this.boardId,
      card_id: cardId,
      column_id: columnId,
      card_data: cardData
    });
  }

  emitCardDeleted(cardId, columnId) {
    this.socket.emit('card_deleted', {
      board_id: this.boardId,
      card_id: cardId,
      column_id: columnId
    });
  }

  emitCardMoved(cardId, fromColumnId, toColumnId, fromIndex, toIndex) {
    this.socket.emit('card_moved', {
      board_id: this.boardId,
      card_id: cardId,
      from_column_id: fromColumnId,
      to_column_id: toColumnId,
      from_index: fromIndex,
      to_index: toIndex
    });
  }

  emitColumnReordered(columnOrder) {
    this.socket.emit('column_reordered', {
      board_id: this.boardId,
      column_order: columnOrder
    });
  }

  emitChecklistItemAdded(cardId, itemId, itemData) {
    this.socket.emit('checklist_item_added', {
      board_id: this.boardId,
      card_id: cardId,
      item_id: itemId,
      item_data: itemData
    });
  }

  emitChecklistItemUpdated(cardId, itemId, updatedFields) {
    this.socket.emit('checklist_item_updated', {
      board_id: this.boardId,
      card_id: cardId,
      item_id: itemId,
      updated_fields: updatedFields
    });
  }

  emitChecklistItemDeleted(cardId, itemId) {
    this.socket.emit('checklist_item_deleted', {
      board_id: this.boardId,
      card_id: cardId,
      item_id: itemId
    });
  }

  // Handle incoming events from other clients
  handleCardCreated(data) {
    // A new card was created on another client
    if (this.boardManager) {
      // Request the board manager to refresh the card or column
      this.boardManager.loadBoard();
      this.boardManager.refreshPlannerIfVisible();
    }
  }

  handleCardUpdated(data) {
    // A card was updated on another client
    // Always reload the board to ensure consistency
    // Even if only the title changed, reloading guarantees the UI matches the server state
    this.boardManager.loadBoard();
    this.boardManager.refreshPlannerIfVisible();
  }

  handleCardDeleted(data) {
    // A card was deleted on another client
    const cardElement = document.querySelector(`[data-card-id="${data.card_id}"]`);
    if (cardElement) {
      cardElement.remove();
    }
    this.boardManager.refreshPlannerIfVisible();
  }

  handleCardMoved(data) {
    // A card was moved on another client
    // Refresh the entire board to ensure correct state
    this.boardManager.loadBoard();
    this.boardManager.refreshPlannerIfVisible();
  }

  handleCardsMoved(data) {
    // Multiple cards were moved on another client
    // Refresh the entire board to ensure correct state
    this.boardManager.loadBoard();
    this.boardManager.refreshPlannerIfVisible();
  }

  handleColumnReordered(data) {
    // Columns were reordered on another client
    // Refresh the board to reflect new column order
    this.boardManager.loadBoard();
  }

  handleColumnCreated(data) {
    // A column was created on another client
    // Reload board so the new column appears immediately
    this.boardManager.loadBoard();
  }

  handleColumnDeleted(data) {
    // A column was deleted on another client
    // Reload board so removed columns disappear immediately
    this.boardManager.loadBoard();
  }

  handleChecklistItemAdded(data) {
    // A checklist item was added on another client
    // Reload board to reflect checklist changes
    this.boardManager.loadBoard();
  }

  handleChecklistItemUpdated(data) {
    // A checklist item was updated on another client
    // Reload board to reflect checklist changes in the card detail modal
    this.boardManager.loadBoard();
  }

  handleChecklistItemDeleted(data) {
    // A checklist item was deleted on another client
    // Reload board to reflect checklist changes
    this.boardManager.loadBoard();
  }

  handleColumnUpdated(data) {
    // A column was updated on another client
    // Reload board to reflect column name changes and order changes
    this.boardManager.loadBoard();
  }

  handleCardArchived(data) {
    // A card was archived on another client
    // Remove the card from the DOM if it's displayed
    const cardElement = document.querySelector(`[data-card-id="${data.card_id}"]`);
    if (cardElement) {
      cardElement.remove();
    }
    // Reload to update card count and ensure consistency
    this.boardManager.loadBoard();
    this.boardManager.refreshPlannerIfVisible();
  }

  handleCardUnarchived(data) {
    // A card was unarchived on another client
    // Reload board to show the restored card
    this.boardManager.loadBoard();
    this.boardManager.refreshPlannerIfVisible();
  }

  handleThemeChanged(data) {
    // Theme was changed by another client
    // Fetch the new theme and apply it without reloading
    
    // Try to use themeBuilder if available (on theme-builder page)
    const themeBuilder = window.AFT?.themeBuilder || window.themeBuilder;
    if (themeBuilder && typeof themeBuilder.loadAndApplyTheme === 'function') {
      themeBuilder.loadAndApplyTheme().catch(error => {
        console.error('✗ Error applying theme from WebSocket event:', error);
      });
    } else if (typeof loadAndApplyThemeGlobal === 'function') {
      // Use global function (available on all pages that include utils.js)
      loadAndApplyThemeGlobal().catch(error => {
        console.error('✗ Error applying theme from WebSocket event:', error);
      });
    } else {
      console.warn('⚠ Theme update received but no theme handler available');
    }
  }

  disconnect() {
    this.leaveBoard();
    if (this.socket) {
      this.socket.disconnect();
    }
  }
}

class BoardManager {
  constructor() {
    this.container = document.getElementById('board-container');
    this.boardId = null;
    this.publicSlug = null;
    this.isBoardPublic = false;
    this.isPublicMode = (window.location.pathname || '').includes('/public-board.html');
    this.publicBoardShareUrl = null;
    this.boardName = '';
    this.columns = [];
    this.originalColumns = []; // Store original unfiltered columns for accurate card counting
    this.hoveredColumnId = null;
    this.lastUsedColumnId = null;
    this.showArchived = false; // Track whether to show archived or active cards
    this.showDone = false; // Track whether to show done cards (for agile style)
    this.currentView = 'task'; // Track current view: 'task', 'scheduled', or 'archived'
    this._pendingPlannerRender = null; // What to render once the 'viewChanged' switch to planner lands
    this.workingStyle = 'kanban'; // Track working style: 'kanban' or 'agile'
    this.canEdit = true; // Track if user has edit permissions for this board
    this.keyboardHandler = this.handleKeydown.bind(this);
    this.closeDropdownHandler = this.handleCloseDropdown.bind(this);
    this.beforeUnloadHandler = this.handleBeforeUnload.bind(this);
    this.viewportMetricsHandler = this.queueMobileViewportMetricsUpdate.bind(this);
    this.boardTouchStartHandler = this.handleBoardTouchStart.bind(this);
    this.boardTouchMoveHandler = this.handleBoardTouchMove.bind(this);
    this.boardTouchEndHandler = this.handleBoardTouchEnd.bind(this);
    this.boardContextMenuHandler = this.handleBoardContextMenu.bind(this);
    this.viewportMetricsRafId = null;
    this.currentLoadController = null; // Track in-flight board load requests
    this.currentViewState = null; // Track the view state for the current load
    this.hasLoadedBoardData = false; // Prevent empty-board render before initial cards load completes
    this.isBootstrappingBoard = false; // True while first board load pipeline is running
    this.boardLoadingDelayTimeoutId = null;
    this.columnScrollPositions = {};
    this.persistScrollTimeoutId = null;
    this.boardHorizontalScrollLeft = 0;
    this.persistBoardHorizontalScrollTimeoutId = null;
    this.expandedCardIds = new Set();
    this.autoScrollHoverTimeoutId = null;
    this.autoScrollRafId = null;
    this.autoScrollContainer = null;
    this.autoScrollDirection = 0;
    this.autoScrollPointerY = 0;
    this.autoScrollPendingContainer = null;
    this.autoScrollPendingDirection = 0;
    this.boardTouchScrollState = null;
    this.boardTouchScrollingSetup = false;
    this.mobileCardLongPressArmedCardId = null;
    this.mobileTouchDragSuppressClickUntil = 0;
    this.assigneeFilterUsers = [];
    this.assigneeFilterVisible = false;
    this.assigneeFilterSelectedUserIds = new Set();
    this.assigneeFilterIncludeUnassigned = false;
    this.assigneeFilterIncludeSecondaryAssignees = false;
    this.searchQueryRaw = '';
    this.searchQueryDebounced = '';
    this.searchDebounceTimer = null;
    this.searchDebounceDelayMs = 500;
    this.searchInputWatcherId = null;
    this.searchFocusRestoreTargetId = null;
    this.searchFocusRestoreEnabled = false;
    this.searchTooltipText = null;
    this.mobileHeaderBreakpoint = 900;
    this.headerSearchCollapsed = true;
    this.boardFiltersToggleRequestHandler = this.handleBoardFiltersToggleRequest.bind(this);
    this.boardFiltersStateRequestHandler = this.handleBoardFiltersStateRequest.bind(this);
    this.boardFiltersClearRequestHandler = this.handleBoardFiltersClearRequest.bind(this);
    this.boardWorkingStyleChangedHandler = this.handleBoardWorkingStyleChanged.bind(this);
    this.assigneeFilterVisibilityLoadedForUserId = null;
    this.assigneeFilterVisibilityWatcherId = null;
  }

  isValidPublicSlug(slug) {
    return /^[a-z0-9]{6,64}$/.test(slug);
  }

  getPublicBoardShareUrl(slug) {
    if (!slug) {
      return null;
    }

    return `${window.location.origin}/public-board.html?slug=${encodeURIComponent(slug)}`;
  }

  getColumnScrollStorageKey() {
    return this.boardId ? `aft:board:${this.boardId}:column-scroll` : null;
  }

  getBoardHorizontalScrollStorageKey() {
    return this.boardId ? `aft:board:${this.boardId}:horizontal-scroll` : null;
  }

  getExpandedCardsStorageKey() {
    return this.boardId ? `aft:board:${this.boardId}:expanded-cards` : null;
  }

  getAssigneeFilterVisibilityStorageKey() {
    if (!this.boardId) {
      return null;
    }

    const userId = this.getCurrentUserIdForFilterStorage();
    if (!userId) {
      return null;
    }

    return `aft:board:${this.boardId}:assignee-filter-visible:user:${userId}`;
  }

  getCurrentUserIdForFilterStorage() {
    if (window.currentUser && window.currentUser.id) {
      return String(window.currentUser.id);
    }

    try {
      const cached = sessionStorage.getItem('currentUser');
      if (cached) {
        const parsed = JSON.parse(cached);
        if (parsed && parsed.id) {
          return String(parsed.id);
        }
      }
    } catch (error) {
      return null;
    }

    return null;
  }

  loadPersistedAssigneeFilterVisibility() {
    const userId = this.getCurrentUserIdForFilterStorage();
    if (!userId) {
      return false;
    }

    if (this.assigneeFilterVisibilityLoadedForUserId === userId) {
      return true;
    }

    const storageKey = this.getAssigneeFilterVisibilityStorageKey();
    if (!storageKey) {
      return false;
    }

    try {
      this.assigneeFilterVisible = sessionStorage.getItem(storageKey) === 'true';
      this.assigneeFilterVisibilityLoadedForUserId = userId;
      return true;
    } catch (error) {
      this.assigneeFilterVisible = false;
      this.assigneeFilterVisibilityLoadedForUserId = userId;
      return false;
    }
  }

  persistAssigneeFilterVisibility() {
    const userId = this.getCurrentUserIdForFilterStorage();
    if (!userId) {
      return;
    }

    const storageKey = this.getAssigneeFilterVisibilityStorageKey();
    if (!storageKey) {
      return;
    }

    try {
      sessionStorage.setItem(storageKey, this.assigneeFilterVisible ? 'true' : 'false');
      this.assigneeFilterVisibilityLoadedForUserId = userId;
    } catch (error) {
      // Ignore storage errors (private mode/quota exceeded).
    }
  }

  watchForAssigneeFilterVisibilityUser() {
    if (this.assigneeFilterVisibilityWatcherId) {
      clearInterval(this.assigneeFilterVisibilityWatcherId);
      this.assigneeFilterVisibilityWatcherId = null;
    }

    let attempts = 0;
    const maxAttempts = 50;
    this.assigneeFilterVisibilityWatcherId = setInterval(() => {
      attempts += 1;
      const loaded = this.loadPersistedAssigneeFilterVisibility();
      if (loaded) {
        this.notifyBoardFilterVisibilityChanged();
        if (this.hasLoadedBoardData) {
          this.renderBoard();
        }
        clearInterval(this.assigneeFilterVisibilityWatcherId);
        this.assigneeFilterVisibilityWatcherId = null;
        return;
      }

      if (attempts >= maxAttempts) {
        clearInterval(this.assigneeFilterVisibilityWatcherId);
        this.assigneeFilterVisibilityWatcherId = null;
      }
    }, 100);
  }

  notifyBoardFilterVisibilityChanged() {
    window.dispatchEvent(new CustomEvent('boardFiltersVisibilityChanged', {
      detail: { visible: this.assigneeFilterVisible }
    }));
  }

  notifyBoardFilterActiveStateChanged() {
    window.dispatchEvent(new CustomEvent('boardFiltersActiveStateChanged', {
      detail: { active: this.hasActiveFilters() }
    }));
  }

  buildAssigneeFilterQueryParams() {
    const params = new URLSearchParams();

    if (this.assigneeFilterSelectedUserIds.size > 0) {
      params.set('assignee_ids', Array.from(this.assigneeFilterSelectedUserIds).join(','));
    }

    if (this.assigneeFilterIncludeUnassigned) {
      params.set('include_unassigned', 'true');
    }

    if (this.assigneeFilterIncludeSecondaryAssignees) {
      params.set('include_secondary_assignees', 'true');
    }

    if (this.searchQueryDebounced) {
      params.set('q', this.searchQueryDebounced);
    }

    return params;
  }

  getSearchTooltipText() {
    if (this.searchTooltipText) {
      return this.searchTooltipText;
    }

    const headerTooltip = document.getElementById('board-header-search-tooltip');
    const tooltipText = headerTooltip ? headerTooltip.textContent.trim() : '';
    this.searchTooltipText = tooltipText || BOARD_SEARCH_TOOLTIP_FALLBACK_TEXT;
    return this.searchTooltipText;
  }

  normalizeSearchQuery(rawValue) {
    return typeof rawValue === 'string' ? rawValue.trim() : '';
  }

  isSearchQueryEligible(rawValue) {
    return this.normalizeSearchQuery(rawValue).length >= 2;
  }

  prepareSearchFocusRestore(targetInputId) {
    if (!targetInputId) {
      return;
    }

    const activeElement = document.activeElement;
    if (!activeElement || activeElement.id !== targetInputId) {
      return;
    }

    this.searchFocusRestoreEnabled = true;
    this.searchFocusRestoreTargetId = targetInputId;
  }

  restoreSearchInputFocusIfNeeded() {
    if (!this.searchFocusRestoreEnabled || !this.searchFocusRestoreTargetId) {
      return;
    }

    const targetInput = document.getElementById(this.searchFocusRestoreTargetId);
    if (!targetInput) {
      return;
    }

    if (document.activeElement !== targetInput) {
      targetInput.focus({ preventScroll: true });
    }

    const cursorPosition = targetInput.value.length;
    if (typeof targetInput.setSelectionRange === 'function') {
      targetInput.setSelectionRange(cursorPosition, cursorPosition);
    }
  }

  isCollapsibleHeaderSearchViewport() {
    return document.body.classList.contains('board-page') &&
      !document.body.classList.contains('public-board-page') &&
      window.innerWidth <= this.mobileHeaderBreakpoint;
  }

  applyHeaderSearchCollapsedState(options = {}) {
    const { focusInput = false } = options;
    const headerSearchControl = document.getElementById('board-header-search-control');
    const headerSearchInput = document.getElementById('board-header-search-input');
    const headerSearchToggle = document.getElementById('board-header-search-toggle-btn');
    if (!headerSearchControl) {
      return;
    }

    const shouldCollapse = this.isCollapsibleHeaderSearchViewport() &&
      this.headerSearchCollapsed &&
      this.searchQueryRaw.length === 0;

    headerSearchControl.classList.toggle('is-collapsed', shouldCollapse);

    if (headerSearchToggle) {
      headerSearchToggle.setAttribute('aria-expanded', shouldCollapse ? 'false' : 'true');
      headerSearchToggle.setAttribute('aria-label', shouldCollapse ? 'Expand board search' : 'Board search expanded');
      headerSearchToggle.setAttribute('title', shouldCollapse ? 'Search' : 'Search expanded');
    }

    if (!shouldCollapse && focusInput && headerSearchInput && document.activeElement !== headerSearchInput) {
      headerSearchInput.focus({ preventScroll: true });
    }
  }

  updateSearchControlState() {
    const selectors = [
      '#board-header-search-input',
      '#board-filter-search-input'
    ];
    selectors.forEach((selector) => {
      const input = document.querySelector(selector);
      if (!input) {
        return;
      }

      if (input.value !== this.searchQueryRaw) {
        input.value = this.searchQueryRaw;
      }

      const tooltipText = this.getSearchTooltipText();
      input.removeAttribute('title');
      input.setAttribute('aria-label', `Search board cards. ${tooltipText}`);
      input.setAttribute('maxlength', '200');
    });

    const clearButtons = [
      '#board-header-search-clear-btn',
      '#board-filter-search-clear-btn'
    ];
    const showClearButton = this.searchQueryRaw.length > 0;
    clearButtons.forEach((selector) => {
      const button = document.querySelector(selector);
      if (!button) {
        return;
      }

      button.style.display = showClearButton ? 'inline-flex' : 'none';
      button.setAttribute('aria-hidden', showClearButton ? 'false' : 'true');
    });

    if (this.searchQueryRaw.length > 0) {
      this.headerSearchCollapsed = false;
    }

    this.applyHeaderSearchCollapsedState();
  }

  setSearchQueryFromInput(rawValue, sourceInputId = null) {
    this.searchQueryRaw = String(rawValue || '');
    this.updateSearchControlState();

    if (this.searchDebounceTimer) {
      clearTimeout(this.searchDebounceTimer);
      this.searchDebounceTimer = null;
    }

    if (!this.isSearchQueryEligible(this.searchQueryRaw)) {
      if (this.searchQueryDebounced) {
        this.prepareSearchFocusRestore(sourceInputId);
        this.searchQueryDebounced = '';
        this.notifyBoardFilterActiveStateChanged();
        this.loadBoard();
      } else {
        this.notifyBoardFilterActiveStateChanged();
      }
      return;
    }

    this.searchDebounceTimer = setTimeout(() => {
      this.searchDebounceTimer = null;
      const normalized = this.normalizeSearchQuery(this.searchQueryRaw);
      if (!this.isSearchQueryEligible(normalized)) {
        if (this.searchQueryDebounced) {
          this.prepareSearchFocusRestore(sourceInputId);
          this.searchQueryDebounced = '';
          this.notifyBoardFilterActiveStateChanged();
          this.loadBoard();
        }
        return;
      }

      if (normalized !== this.searchQueryDebounced) {
        this.prepareSearchFocusRestore(sourceInputId);
        this.searchQueryDebounced = normalized;
        this.notifyBoardFilterActiveStateChanged();
        this.loadBoard();
      }
    }, this.searchDebounceDelayMs);
  }

  async clearSearchQuery() {
    if (this.searchDebounceTimer) {
      clearTimeout(this.searchDebounceTimer);
      this.searchDebounceTimer = null;
    }

    const hadActiveSearch = !!this.searchQueryDebounced;
    this.searchQueryRaw = '';
    this.searchQueryDebounced = '';
    this.headerSearchCollapsed = true;
    this.updateSearchControlState();
    this.notifyBoardFilterActiveStateChanged();

    if (hadActiveSearch) {
      await this.loadBoard();
    }
  }

  bindSearchInputEvents() {
    const inputSelectorMap = [
      '#board-header-search-input',
      '#board-filter-search-input'
    ];
    inputSelectorMap.forEach((selector) => {
      const input = document.querySelector(selector);
      if (!input || input.dataset.boundSearchInput === 'true') {
        return;
      }

      input.addEventListener('input', (event) => {
        this.setSearchQueryFromInput(event.target.value, event.target.id);
      });
      input.addEventListener('focus', () => {
        this.searchFocusRestoreEnabled = true;
        this.searchFocusRestoreTargetId = input.id;

        if (input.id === 'board-header-search-input') {
          this.headerSearchCollapsed = false;
          this.applyHeaderSearchCollapsedState();
        }
      });
      input.addEventListener('blur', () => {
        window.setTimeout(() => {
          const activeId = document.activeElement ? document.activeElement.id : null;
          const isSearchInputStillFocused = activeId === 'board-header-search-input' ||
            activeId === 'board-filter-search-input';

          if (isSearchInputStillFocused) {
            this.searchFocusRestoreEnabled = true;
            this.searchFocusRestoreTargetId = activeId;
            return;
          }

          this.searchFocusRestoreEnabled = false;
          this.searchFocusRestoreTargetId = null;

          if (input.id === 'board-header-search-input' && this.searchQueryRaw.length === 0) {
            this.headerSearchCollapsed = true;
            this.applyHeaderSearchCollapsedState();
          }
        }, 0);
      });
      input.dataset.boundSearchInput = 'true';
    });

    const clearButtonSelectorMap = [
      '#board-header-search-clear-btn',
      '#board-filter-search-clear-btn'
    ];
    clearButtonSelectorMap.forEach((selector) => {
      const button = document.querySelector(selector);
      if (!button || button.dataset.boundSearchClear === 'true') {
        return;
      }

      button.addEventListener('click', async () => {
        this.headerSearchCollapsed = true;
        await this.clearSearchQuery();
      });
      button.dataset.boundSearchClear = 'true';
    });

    const headerSearchToggle = document.getElementById('board-header-search-toggle-btn');
    if (headerSearchToggle && headerSearchToggle.dataset.boundSearchToggle !== 'true') {
      headerSearchToggle.addEventListener('click', () => {
        this.headerSearchCollapsed = false;
        this.applyHeaderSearchCollapsedState({ focusInput: true });
      });
      headerSearchToggle.dataset.boundSearchToggle = 'true';
    }

    const openFiltersButton = document.getElementById('board-header-search-filters-btn');
    if (openFiltersButton && openFiltersButton.dataset.boundSearchFilters !== 'true') {
      openFiltersButton.addEventListener('click', () => {
        window.dispatchEvent(new CustomEvent('boardFiltersToggleRequested'));
      });
      openFiltersButton.dataset.boundSearchFilters = 'true';
    }

    this.updateSearchControlState();
  }

  watchForHeaderSearchControl() {
    if (this.searchInputWatcherId) {
      clearInterval(this.searchInputWatcherId);
      this.searchInputWatcherId = null;
    }

    let attempts = 0;
    const maxAttempts = 50;
    this.searchInputWatcherId = setInterval(() => {
      attempts += 1;
      this.bindSearchInputEvents();

      const headerSearchInput = document.getElementById('board-header-search-input');
      if (headerSearchInput || attempts >= maxAttempts) {
        clearInterval(this.searchInputWatcherId);
        this.searchInputWatcherId = null;
      }
    }, 100);
  }

  /**
   * Check if any assignee filters are currently active
   * @returns {boolean} True if specific assignees are selected or unassigned filter is active
   */
  hasActiveFilters() {
    return this.assigneeFilterSelectedUserIds.size > 0 ||
      this.assigneeFilterIncludeUnassigned ||
      !!this.searchQueryDebounced;
  }

  /**
   * Clear all active filters and reload the board
   * Resets selected assignees, unassigned toggle, and secondary assignees toggle
   */
  clearFilters() {
    if (this.searchDebounceTimer) {
      clearTimeout(this.searchDebounceTimer);
      this.searchDebounceTimer = null;
    }

    this.assigneeFilterSelectedUserIds.clear();
    this.assigneeFilterIncludeUnassigned = false;
    this.assigneeFilterIncludeSecondaryAssignees = false;
    this.searchQueryRaw = '';
    this.searchQueryDebounced = '';
    this.headerSearchCollapsed = true;
    this.updateSearchControlState();
    this.notifyBoardFilterActiveStateChanged();
    this.loadBoard();
  }

  handleBoardFiltersToggleRequest() {
    this.assigneeFilterVisible = !this.assigneeFilterVisible;
    this.persistAssigneeFilterVisibility();
    this.notifyBoardFilterVisibilityChanged();
    this.renderBoard();
    this.queueMobileViewportMetricsUpdate();
  }

  handleBoardFiltersStateRequest() {
    this.notifyBoardFilterVisibilityChanged();
    this.notifyBoardFilterActiveStateChanged();
  }

  handleBoardFiltersClearRequest() {
    this.clearFilters();
  }

  sanitizeColumnScrollPositions(value) {
    const sanitized = {};
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return sanitized;
    }

    Object.keys(value).forEach((key) => {
      const raw = value[key];
      const numberValue = typeof raw === 'number' ? raw : Number(raw);
      if (Number.isFinite(numberValue)) {
        sanitized[key] = numberValue;
      }
    });

    return sanitized;
  }

  sanitizeBoardHorizontalScroll(value) {
    const numberValue = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(numberValue) && numberValue >= 0 ? numberValue : 0;
  }

  sanitizeExpandedCardIds(value) {
    if (!Array.isArray(value)) {
      return new Set();
    }

    return new Set(
      value
        .map((id) => (typeof id === 'number' ? id : Number(id)))
        .filter((id) => Number.isInteger(id) && id > 0)
    );
  }

  updateColumnScrollPosition(columnId, scrollTop, targetMap = this.columnScrollPositions) {
    if (!columnId || !targetMap || typeof targetMap !== 'object') return;

    const numberValue = typeof scrollTop === 'number' ? scrollTop : Number(scrollTop);
    if (!Number.isFinite(numberValue)) return;

    targetMap[columnId] = numberValue;
  }

  loadPersistedColumnScrollPositions() {
    const storageKey = this.getColumnScrollStorageKey();
    if (!storageKey) return;

    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      this.columnScrollPositions = this.sanitizeColumnScrollPositions(parsed);
    } catch (error) {
      console.warn('Failed to load column scroll positions:', error);
    }
  }

  loadPersistedBoardHorizontalScrollPosition() {
    const storageKey = this.getBoardHorizontalScrollStorageKey();
    if (!storageKey) return;

    try {
      const raw = localStorage.getItem(storageKey);
      if (raw === null) return;
      this.boardHorizontalScrollLeft = this.sanitizeBoardHorizontalScroll(raw);
    } catch (error) {
      console.warn('Failed to load board horizontal scroll position:', error);
    }
  }

  loadPersistedExpandedCardState() {
    const storageKey = this.getExpandedCardsStorageKey();
    if (!storageKey) return;

    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      this.expandedCardIds = this.sanitizeExpandedCardIds(parsed);
    } catch (error) {
      console.warn('Failed to load expanded card state:', error);
      this.expandedCardIds = new Set();
    }
  }

  persistColumnScrollPositions() {
    const storageKey = this.getColumnScrollStorageKey();
    if (!storageKey) return;

    try {
      localStorage.setItem(storageKey, JSON.stringify(this.columnScrollPositions));
    } catch (error) {
      console.warn('Failed to persist column scroll positions:', error);
    }
  }

  persistBoardHorizontalScrollPosition() {
    const storageKey = this.getBoardHorizontalScrollStorageKey();
    if (!storageKey) return;

    try {
      localStorage.setItem(storageKey, String(this.boardHorizontalScrollLeft));
    } catch (error) {
      console.warn('Failed to persist board horizontal scroll position:', error);
    }
  }

  persistExpandedCardState() {
    const storageKey = this.getExpandedCardsStorageKey();
    if (!storageKey) return;

    try {
      localStorage.setItem(storageKey, JSON.stringify(Array.from(this.expandedCardIds)));
    } catch (error) {
      console.warn('Failed to persist expanded card state:', error);
    }
  }

  schedulePersistColumnScrollPositions() {
    if (this.persistScrollTimeoutId) {
      clearTimeout(this.persistScrollTimeoutId);
    }

    this.persistScrollTimeoutId = setTimeout(() => {
      this.persistColumnScrollPositions();
      this.persistScrollTimeoutId = null;
    }, 150);
  }

  schedulePersistBoardHorizontalScrollPosition() {
    if (this.persistBoardHorizontalScrollTimeoutId) {
      clearTimeout(this.persistBoardHorizontalScrollTimeoutId);
    }

    this.persistBoardHorizontalScrollTimeoutId = setTimeout(() => {
      this.persistBoardHorizontalScrollPosition();
      this.persistBoardHorizontalScrollTimeoutId = null;
    }, 150);
  }

  captureColumnScrollPositions() {
    const newPositions = {};
    let capturedCount = 0;

    document.querySelectorAll('.column-cards[data-column-id]').forEach(columnCards => {
      const columnId = columnCards.getAttribute('data-column-id');
      if (!columnId) return;
      this.updateColumnScrollPosition(columnId, columnCards.scrollTop, newPositions);
      capturedCount += 1;
    });

    // Avoid wiping restored values during first load before columns are rendered.
    if (capturedCount === 0) return;

    this.columnScrollPositions = newPositions;

    this.schedulePersistColumnScrollPositions();
  }

  captureBoardHorizontalScrollPosition() {
    const columnsContainer = this.container?.querySelector('.columns-container');
    if (!columnsContainer) return;

    this.boardHorizontalScrollLeft = this.sanitizeBoardHorizontalScroll(columnsContainer.scrollLeft);
    this.schedulePersistBoardHorizontalScrollPosition();
  }

  captureExpandedCardState() {
    const expanded = new Set();
    let capturedCount = 0;

    this.container?.querySelectorAll('.card.has-overflow[data-card-id]').forEach((cardElement) => {
      capturedCount += 1;
      if (cardElement.classList.contains('collapsed')) {
        return;
      }

      const cardId = Number(cardElement.getAttribute('data-card-id'));
      if (Number.isInteger(cardId) && cardId > 0) {
        expanded.add(cardId);
      }
    });

    // Avoid wiping persisted state before cards are rendered during initial load.
    if (capturedCount === 0) return;

    this.expandedCardIds = expanded;
    this.persistExpandedCardState();
  }

  restoreColumnScrollPositions() {
    requestAnimationFrame(() => {
      document.querySelectorAll('.column-cards[data-column-id]').forEach(columnCards => {
        const columnId = columnCards.getAttribute('data-column-id');
        if (!columnId) return;

        const savedScrollTop = this.columnScrollPositions[columnId];
        if (typeof savedScrollTop === 'number' && savedScrollTop > 0) {
          columnCards.scrollTop = savedScrollTop;
        }
      });
    });
  }

  restoreBoardHorizontalScrollPosition() {
    requestAnimationFrame(() => {
      const columnsContainer = this.container?.querySelector('.columns-container');
      if (!columnsContainer) return;

      if (this.boardHorizontalScrollLeft > 0) {
        columnsContainer.scrollLeft = this.boardHorizontalScrollLeft;
      }
    });
  }

  restoreExpandedCardState() {
    if (!this.expandedCardIds || this.expandedCardIds.size === 0) {
      return;
    }

    this.container?.querySelectorAll('.card.has-overflow[data-card-id]').forEach((cardElement) => {
      const cardId = Number(cardElement.getAttribute('data-card-id'));
      if (!Number.isInteger(cardId) || cardId <= 0) {
        return;
      }

      if (!this.expandedCardIds.has(cardId)) {
        return;
      }

      const expandBtn = cardElement.querySelector('.card-expand-btn');
      if (!expandBtn) {
        return;
      }

      cardElement.classList.remove('collapsed');
      expandBtn.textContent = 'Show less...';
      expandBtn.setAttribute('aria-expanded', 'true');
    });
  }

  handleBeforeUnload() {
    this.captureColumnScrollPositions();
    this.persistColumnScrollPositions();
    this.captureBoardHorizontalScrollPosition();
    this.persistBoardHorizontalScrollPosition();
    this.captureExpandedCardState();
  }

  setupMobileViewportSync() {
    this.queueMobileViewportMetricsUpdate();
    window.addEventListener('resize', this.viewportMetricsHandler);
    window.addEventListener('orientationchange', this.viewportMetricsHandler);

    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', this.viewportMetricsHandler);
      window.visualViewport.addEventListener('scroll', this.viewportMetricsHandler, { passive: true });
    }
  }

  setupBoardTouchScrolling() {
    if (!this.container || this.boardTouchScrollingSetup) {
      return;
    }

    this.container.addEventListener('touchstart', this.boardTouchStartHandler, { passive: true });
    this.container.addEventListener('touchmove', this.boardTouchMoveHandler, { passive: false });
    this.container.addEventListener('touchend', this.boardTouchEndHandler, { passive: true });
    this.container.addEventListener('touchcancel', this.boardTouchEndHandler, { passive: true });
    this.container.addEventListener('contextmenu', this.boardContextMenuHandler);
    this.boardTouchScrollingSetup = true;
  }

  isMobileTouchViewport() {
    const hasTouchSupport = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
    return hasTouchSupport && window.matchMedia(`(max-width: ${MOBILE_BOARD_TOUCH_SCROLL_BREAKPOINT_PX}px)`).matches;
  }

  logMobileCardLongPressDebug(eventName, details = {}) {
    // Intentionally no-op: temporary mobile drag diagnostics removed.
    void eventName;
    void details;
  }

  canStartMobileCardLongPress(targetElement) {
    if (!targetElement || !this.canEdit) {
      return false;
    }

    const cardElement = targetElement.closest('.card');
    if (!cardElement) {
      return false;
    }

    if (cardElement.getAttribute('data-archived') === 'true') {
      return false;
    }

    const interactiveSelector = [
      '.card-delete-btn',
      '.card-archive-btn',
      '.card-unarchive-btn',
      '.card-done-btn',
      '.card-move-btn',
      '.card-expand-btn',
      '.card-checklist-checkbox',
      '.card-action-buttons',
      'button',
      'input',
      'textarea',
      'select',
      'a'
    ].join(',');

    if (targetElement.closest(interactiveSelector)) {
      return false;
    }

    return true;
  }

  clearMobileCardLongPress(state, options = {}) {
    if (!state) {
      return;
    }

    if (state.cardLongPressTimerId) {
      clearTimeout(state.cardLongPressTimerId);
      state.cardLongPressTimerId = null;
    }

    if (state.touchDragState?.cardElement) {
      state.touchDragState.cardElement.classList.remove('dragging');
      state.touchDragState.cardElement.classList.remove('mobile-drag-armed');
      state.touchDragState.cardElement.classList.remove('mobile-touch-drag-source');
      this.stopColumnAutoScroll();
    }

    if (state.touchDragState?.ghostElement) {
      state.touchDragState.ghostElement.remove();
    }

    if (state.cardElement) {
      const cardId = Number(state.cardElement.getAttribute('data-card-id'));
      if (Number.isInteger(cardId) && cardId > 0 && this.mobileCardLongPressArmedCardId === cardId) {
        this.mobileCardLongPressArmedCardId = null;
      }

      state.cardElement.classList.remove('mobile-drag-armed');

      this.logMobileCardLongPressDebug('clear-long-press', {
        cardId,
        isDragging: state.cardElement.classList.contains('dragging')
      });
    }

    state.cardLongPressCancelled = true;
    state.cardLongPressActivated = false;
    state.touchDragState = null;
  }

  activateMobileCardLongPress(state) {
    if (!state || state.cardLongPressCancelled || !state.cardElement?.isConnected) {
      return;
    }

    state.cardLongPressTimerId = null;
    state.cardLongPressActivated = true;
    const cardId = Number(state.cardElement.getAttribute('data-card-id'));
    if (Number.isInteger(cardId) && cardId > 0) {
      this.mobileCardLongPressArmedCardId = cardId;
    }
    state.cardElement.classList.add('mobile-drag-armed');
    this.logMobileCardLongPressDebug('long-press-activated', {
      cardId,
      armedCardId: this.mobileCardLongPressArmedCardId
    });
  }

  resolveColumnCardsContainerFromPoint(clientX, clientY) {
    const pointedElement = document.elementFromPoint(clientX, clientY);
    if (!(pointedElement instanceof Element)) {
      return null;
    }

    const directContainer = pointedElement.closest('.column-cards');
    if (directContainer?.isConnected) {
      return directContainer;
    }

    const pointedColumn = pointedElement.closest('.column');
    const columnContainer = pointedColumn?.querySelector('.column-cards') || null;
    return columnContainer?.isConnected ? columnContainer : null;
  }

  captureCardOriginalPosition(cardElement) {
    if (!cardElement?.isConnected) {
      return null;
    }

    const columnId = Number(cardElement.getAttribute('data-column-id'));
    const order = Number(cardElement.getAttribute('data-order'));
    const container = cardElement.closest('.column-cards');

    if (!container?.isConnected) {
      return {
        columnId,
        order,
        index: null,
        container: null,
        nextSibling: null
      };
    }

    const cardsInContainer = Array.from(container.querySelectorAll('.card'));
    const rawIndex = cardsInContainer.indexOf(cardElement);

    return {
      columnId,
      order,
      index: rawIndex >= 0 ? rawIndex : null,
      container,
      nextSibling: cardElement.nextElementSibling
    };
  }

  startMobileTouchCardDrag(state) {
    if (!state?.cardElement?.isConnected) {
      return;
    }

    const cardElement = state.cardElement;
    const cardRect = cardElement.getBoundingClientRect();
    const originalPosition = this.captureCardOriginalPosition(cardElement);
    if (!originalPosition) {
      return;
    }

    const oldColumnId = Number(originalPosition.columnId);
    const oldOrder = Number(originalPosition.order);
    const originalIndex = originalPosition.index;

    const ghostElement = cardElement.cloneNode(true);
    ghostElement.removeAttribute('id');
    ghostElement.querySelectorAll('[id]').forEach((element) => element.removeAttribute('id'));
    ghostElement.classList.remove('dragging', 'mobile-drag-armed');
    ghostElement.classList.add('mobile-touch-drag-ghost');
    ghostElement.setAttribute('aria-hidden', 'true');
    ghostElement.style.width = `${cardRect.width}px`;
    ghostElement.style.height = `${cardRect.height}px`;
    ghostElement.style.transform = `translate3d(${cardRect.left}px, ${cardRect.top}px, 0)`;
    document.body.appendChild(ghostElement);

    const pointerOffsetX = state.startX - cardRect.left;
    const pointerOffsetY = state.startY - cardRect.top;

    state.touchDragState = {
      active: true,
      cardElement,
      ghostElement,
      pointerOffsetX,
      pointerOffsetY,
      originalPosition
    };

    cardElement.classList.add('dragging');
    cardElement.classList.add('mobile-touch-drag-source');

    const cardId = Number(cardElement.getAttribute('data-card-id'));
    this.logMobileCardLongPressDebug('touch-drag-started', {
      cardId,
      oldColumnId,
      oldOrder,
      originalIndex
    });
  }

  moveMobileTouchCardDrag(state, touch) {
    const touchDragState = state?.touchDragState;
    const draggedCard = touchDragState?.cardElement;
    if (!touchDragState?.active || !draggedCard?.isConnected) {
      return;
    }

    if (touchDragState.ghostElement?.isConnected) {
      const ghostLeft = touch.clientX - touchDragState.pointerOffsetX;
      const ghostTop = touch.clientY - touchDragState.pointerOffsetY;
      touchDragState.ghostElement.style.transform = `translate3d(${ghostLeft}px, ${ghostTop}px, 0)`;
    }

    const columnContainer = this.resolveColumnCardsContainerFromPoint(touch.clientX, touch.clientY);
    if (!columnContainer) {
      this.stopColumnAutoScroll();
      return;
    }

    this.updateColumnAutoScrollDuringDrag(columnContainer, touch.clientY);

    const afterElement = this.getDragAfterElement(columnContainer, touch.clientY);
    if (!afterElement) {
      const addCardBtn = columnContainer.querySelector('.add-card-btn');
      if (addCardBtn) {
        columnContainer.insertBefore(draggedCard, addCardBtn);
      } else {
        columnContainer.appendChild(draggedCard);
      }
      return;
    }

    columnContainer.insertBefore(draggedCard, afterElement);
  }

  async finishMobileTouchCardDrag(state) {
    const touchDragState = state?.touchDragState;
    if (!touchDragState?.active || !touchDragState.cardElement?.isConnected) {
      return;
    }

    const draggedCard = touchDragState.cardElement;
    const originalPosition = touchDragState.originalPosition;
    const targetContainer = draggedCard.closest('.column-cards');

    draggedCard.classList.remove('dragging');
    draggedCard.classList.remove('mobile-touch-drag-source');
    if (touchDragState.ghostElement) {
      touchDragState.ghostElement.remove();
    }
    this.stopColumnAutoScroll();

    if (!targetContainer || !originalPosition) {
      if (originalPosition) {
        const restored = this.restoreCardPosition(draggedCard, originalPosition);
        if (!restored) {
          await this.loadBoard();
        }
      }
      return;
    }

    const cardId = Number(draggedCard.getAttribute('data-card-id'));
    const targetColumnId = Number(targetContainer.getAttribute('data-column-id'));
    const oldColumnId = Number(originalPosition.columnId);
    const newOrder = this.getDropOrderValue(targetContainer, draggedCard, originalPosition);

    this.logMobileCardLongPressDebug('touch-drop', {
      cardId,
      oldColumnId,
      targetColumnId,
      oldOrder: originalPosition.order,
      newOrder
    });

    if (targetColumnId !== oldColumnId || newOrder !== originalPosition.order) {
      this.mobileTouchDragSuppressClickUntil = Date.now() + 400;
      await this.updateCardPosition(cardId, targetColumnId, newOrder, originalPosition);
    }
  }

  resetBoardTouchScrollingState() {
    this.clearMobileCardLongPress(this.boardTouchScrollState);
    this.boardTouchScrollState = null;
  }

  getTrackedBoardTouch(event, touchId) {
    if (!event.touches || event.touches.length === 0) {
      return null;
    }

    return Array.from(event.touches).find(touch => touch.identifier === touchId) || event.touches[0];
  }

  handleBoardTouchStart(event) {
    if (!this.isMobileTouchViewport()) {
      return;
    }

    if (event.touches.length !== 1) {
      this.resetBoardTouchScrollingState();
      return;
    }

    const columnsContainer = this.container?.querySelector('.columns-container');
    if (!columnsContainer) {
      return;
    }

    const touch = event.touches[0];
    const targetElement = event.target instanceof Element ? event.target : null;
    const touchedColumn = targetElement?.closest('.column');
    const columnCardsContainer = targetElement?.closest('.column-cards') ||
      touchedColumn?.querySelector('.column-cards') ||
      null;
    const touchedCard = targetElement?.closest('.card') || null;
    const shouldTrackCardLongPress = this.canStartMobileCardLongPress(targetElement);
    const touchedCardId = touchedCard ? Number(touchedCard.getAttribute('data-card-id')) : null;

    this.logMobileCardLongPressDebug('touchstart', {
      touchId: touch.identifier,
      targetClass: targetElement?.className || null,
      touchedCardId,
      shouldTrackCardLongPress
    });

    this.boardTouchScrollState = {
      active: true,
      touchId: touch.identifier,
      startX: touch.clientX,
      startY: touch.clientY,
      lastX: touch.clientX,
      lastY: touch.clientY,
      axis: null,
      columnsContainer,
      columnCardsContainer,
      cardElement: shouldTrackCardLongPress ? touchedCard : null,
      cardLongPressTimerId: null,
      cardLongPressActivated: false,
      cardLongPressCancelled: !shouldTrackCardLongPress,
      touchDragState: null
    };

    if (shouldTrackCardLongPress) {
      this.boardTouchScrollState.cardLongPressTimerId = setTimeout(() => {
        this.activateMobileCardLongPress(this.boardTouchScrollState);
      }, MOBILE_CARD_LONG_PRESS_DELAY_MS);

      this.logMobileCardLongPressDebug('long-press-timer-started', {
        touchedCardId,
        delayMs: MOBILE_CARD_LONG_PRESS_DELAY_MS
      });
    }
  }

  handleBoardTouchMove(event) {
    const state = this.boardTouchScrollState;
    if (!state?.active) {
      return;
    }

    const touch = this.getTrackedBoardTouch(event, state.touchId);
    if (!touch) {
      this.resetBoardTouchScrollingState();
      return;
    }

    const deltaX = touch.clientX - state.lastX;
    const deltaY = touch.clientY - state.lastY;
    const totalDeltaX = touch.clientX - state.startX;
    const totalDeltaY = touch.clientY - state.startY;
    const movementDistance = Math.max(Math.abs(totalDeltaX), Math.abs(totalDeltaY));

    if (state.cardElement && !state.cardLongPressCancelled && !state.cardLongPressActivated) {
      if (movementDistance >= MOBILE_CARD_LONG_PRESS_MOVE_TOLERANCE_PX) {
        const cardId = Number(state.cardElement.getAttribute('data-card-id'));
        this.logMobileCardLongPressDebug('long-press-cancelled-by-move', {
          cardId,
          movementDistance,
          tolerance: MOBILE_CARD_LONG_PRESS_MOVE_TOLERANCE_PX
        });
        this.clearMobileCardLongPress(state);
      } else {
        return;
      }
    }

    if (state.cardLongPressActivated) {
      event.preventDefault();

      if (!state.touchDragState?.active) {
        this.startMobileTouchCardDrag(state);
      }

      this.moveMobileTouchCardDrag(state, touch);

      const cardId = state.cardElement ? Number(state.cardElement.getAttribute('data-card-id')) : null;
      this.logMobileCardLongPressDebug('touchmove-while-armed', {
        cardId,
        deltaX,
        deltaY,
        totalDeltaX,
        totalDeltaY
      });
      state.lastX = touch.clientX;
      state.lastY = touch.clientY;
      return;
    }

    if (!state.axis) {
      if (movementDistance < MOBILE_BOARD_TOUCH_SCROLL_LOCK_THRESHOLD_PX) {
        return;
      }

      if (Math.abs(totalDeltaX) > Math.abs(totalDeltaY)) {
        state.axis = 'horizontal';
      } else if (state.columnCardsContainer) {
        state.axis = 'vertical';
      } else {
        this.resetBoardTouchScrollingState();
        return;
      }
    }

    if (state.axis === 'horizontal') {
      event.preventDefault();
      state.columnsContainer.scrollLeft -= deltaX;
      this.boardHorizontalScrollLeft = this.sanitizeBoardHorizontalScroll(state.columnsContainer.scrollLeft);
      this.schedulePersistBoardHorizontalScrollPosition();
      state.lastX = touch.clientX;
      state.lastY = touch.clientY;
      return;
    }

    if (state.axis === 'vertical' && state.columnCardsContainer?.isConnected) {
      event.preventDefault();
      state.columnCardsContainer.scrollTop -= deltaY;
      state.lastX = touch.clientX;
      state.lastY = touch.clientY;
      return;
    }

    this.resetBoardTouchScrollingState();
  }

  async handleBoardTouchEnd() {
    if (this.boardTouchScrollState?.cardElement) {
      const cardId = Number(this.boardTouchScrollState.cardElement.getAttribute('data-card-id'));
      this.logMobileCardLongPressDebug('touchend', {
        cardId,
        longPressActivated: this.boardTouchScrollState.cardLongPressActivated,
        longPressCancelled: this.boardTouchScrollState.cardLongPressCancelled
      });
    }

    if (this.boardTouchScrollState?.cardLongPressActivated && this.boardTouchScrollState?.touchDragState?.active) {
      await this.finishMobileTouchCardDrag(this.boardTouchScrollState);
    }

    this.resetBoardTouchScrollingState();
  }

  handleBoardContextMenu(event) {
    if (!this.isMobileTouchViewport()) {
      return;
    }

    const targetElement = event.target instanceof Element ? event.target : null;
    const cardElement = targetElement?.closest('.card');
    if (!cardElement) {
      return;
    }

    event.preventDefault();

    const cardId = Number(cardElement.getAttribute('data-card-id'));
    this.logMobileCardLongPressDebug('contextmenu-prevented', {
      cardId,
      targetClass: targetElement?.className || null
    });
  }

  queueMobileViewportMetricsUpdate() {
    if (this.viewportMetricsRafId) {
      return;
    }

    this.viewportMetricsRafId = requestAnimationFrame(() => {
      this.viewportMetricsRafId = null;
      this.updateMobileBoardViewportMetrics();
    });
  }

  updateMobileBoardViewportMetrics() {
    if (!document.body.classList.contains('board-page')) {
      return;
    }

    this.applyHeaderSearchCollapsedState();

    const columnsContainer = this.container?.querySelector('.columns-container');
    if (!columnsContainer) {
      return;
    }

    const viewportHeight = window.visualViewport?.height || window.innerHeight || document.documentElement.clientHeight;
    if (!Number.isFinite(viewportHeight) || viewportHeight <= 0) {
      return;
    }

    const containerTop = columnsContainer.getBoundingClientRect().top;
    const bottomGap = 8;
    const availableHeight = Math.max(320, Math.floor(viewportHeight - containerTop - bottomGap));

    document.documentElement.style.setProperty('--board-mobile-available-height', `${availableHeight}px`);
  }

  /**
   * Safely parse JSON response, handling non-JSON errors
   * @param {Response} response - Fetch response object
   * @returns {Promise<Object>} Parsed JSON data or error object
   */
  async parseResponse(response) {
    try {
      const rawText = await response.text();
      if (!rawText || !rawText.trim()) {
        return {
          success: false,
          message: response.ok
            ? 'Incomplete JSON response from server'
            : `HTTP error! status: ${response.status}`,
          parseFailed: response.ok,
          parseFailureType: response.ok ? 'empty-body' : null
        };
      }

      const data = JSON.parse(rawText);
      if (!response.ok) {
        // Response parsed successfully but HTTP status indicates error
        return data;
      }
      return data;
    } catch (error) {
      // JSON parsing failed
      if (response.ok) {
        console.error('Invalid JSON response while loading board:', error);
      }
      return {
        success: false,
        message: response.ok 
          ? 'Invalid JSON response from server'
          : `HTTP error! status: ${response.status}`,
        parseFailed: response.ok,
        parseFailureType: response.ok ? 'invalid-json' : null
      };
    }
  }

  getNetworkTimeoutMultiplier() {
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (!connection) {
      return 1;
    }

    let multiplier = 1;
    switch (connection.effectiveType) {
      case 'slow-2g':
        multiplier = 4;
        break;
      case '2g':
        multiplier = 3;
        break;
      case '3g':
        multiplier = 2;
        break;
      default:
        multiplier = 1;
        break;
    }

    if (connection.saveData) {
      multiplier = Math.max(multiplier, 2);
    }

    return multiplier;
  }

  getBoardLoadTimeoutMs(attempt = 1) {
    const baseTimeoutMs = this.hasLoadedBoardData
      ? SUBSEQUENT_BOARD_LOAD_TIMEOUT_MS
      : INITIAL_BOARD_LOAD_TIMEOUT_MS;
    const multiplier = this.getNetworkTimeoutMultiplier();
    const retryBufferMs = (attempt - 1) * 5000;
    return Math.min((baseTimeoutMs * multiplier) + retryBufferMs, 45000);
  }

  /**
   * Check endpoint permission through PermissionManager with safe fallback.
   *
   * @param {string} method - HTTP method
   * @param {string} endpoint - Endpoint pattern (e.g. /api/cards/:id/archive)
   * @returns {boolean} True if endpoint is allowed
   */
  canCallPermissionEndpoint(method, endpoint) {
    if (!window.PermissionManager || !PermissionManager.initialized) {
      return false;
    }

    return PermissionManager.canCallEndpoint(method, endpoint);
  }

  /**
   * Determine whether any column-menu action is currently available.
   *
   * @returns {boolean} True if at least one menu action is permitted
   */
  canShowColumnMenu() {
    return this.canEdit ||
      this.canCallPermissionEndpoint('POST', '/api/columns/:id/cards') ||
      this.canCallPermissionEndpoint('PATCH', '/api/columns/:id') ||
      this.canCallPermissionEndpoint('POST', '/api/columns/:source_id/cards/move') ||
      this.canCallPermissionEndpoint('POST', '/api/cards/batch/archive') ||
      this.canCallPermissionEndpoint('POST', '/api/cards/batch/unarchive') ||
      this.canCallPermissionEndpoint('POST', '/api/columns/:id/archive-after') ||
      this.canCallPermissionEndpoint('DELETE', '/api/columns/:id/cards') ||
      this.canCallPermissionEndpoint('DELETE', '/api/columns/:id');
  }

  /**
   * Show a non-blocking error toast notification
   * @param {string} message - The error message to display
   * @param {number} duration - How long to show the toast in milliseconds (default 3000)
   */
  showErrorToast(message, duration = 3000) {
    // Create toast element
    const toast = document.createElement('div');
    toast.className = 'error-toast';
    toast.textContent = message;
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
    
    // Remove after specified duration
    setTimeout(() => {
      toast.style.animation = 'slideOut 0.3s ease-in';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  showSuccessToast(message, duration = 3000) {
    // Create toast element
    const toast = document.createElement('div');
    toast.className = 'success-toast';
    toast.textContent = message;
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
    
    // Remove after specified duration
    setTimeout(() => {
      toast.style.animation = 'slideOut 0.3s ease-in';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  showBoardLoadFailureMessage(parseFailed = false, parseFailureType = null, backendMessage = '') {
    const message = parseFailed
      ? (parseFailureType === 'invalid-json'
        ? 'The server response was invalid. Please try again.'
        : 'The server response was incomplete. Please try again.')
      : (backendMessage || 'The board data could not be loaded.');

    if (!parseFailed && backendMessage) {
      console.error('Board API reported load failure:', backendMessage);
    }

    this.hideBoardLoading();
    this.showErrorToast(message);
    this.showError(message);
  }

  showBoardLoadUnexpectedErrorMessage() {
    this.hideBoardLoading();
    this.showErrorToast('Error loading board. Please try again.');
    this.showError('An error occurred while loading the board');
  }

  async init() {
    if (this.isBootstrappingBoard) {
      return;
    }

    this.isBootstrappingBoard = true;

    try {
      const urlParams = new URLSearchParams(window.location.search);
      if (this.isPublicMode) {
        const slugParam = (urlParams.get('slug') || '').trim().toLowerCase();
        if (!this.isValidPublicSlug(slugParam)) {
          this.showError('Invalid or missing public board slug');
          return;
        }
        this.publicSlug = slugParam;
        this.publicBoardShareUrl = this.getPublicBoardShareUrl(this.publicSlug);
      } else {
        // Get board ID from URL query parameter
        const boardIdParam = urlParams.get('id');
        const initialSearchQuery = this.normalizeSearchQuery(urlParams.get('q'));
        this.searchQueryRaw = initialSearchQuery;
        this.searchQueryDebounced = this.isSearchQueryEligible(initialSearchQuery)
          ? initialSearchQuery
          : '';

        // Parse and validate board ID to prevent XSS
        this.boardId = boardIdParam ? parseInt(boardIdParam, 10) : null;

        if (!this.boardId || isNaN(this.boardId)) {
          this.showError('Invalid or missing board ID');
          return;
        }

        // Initialize Permission Manager with board context
        console.log('Initializing PermissionManager for board:', this.boardId);
        const permissionInitSuccess = await PermissionManager.init(this.boardId);

        if (!permissionInitSuccess) {
          console.warn('Failed to initialize PermissionManager - some features may not be available');
          // Continue anyway - the user is logged in if we're here
        }
      }

      this.render();
      this.showBoardLoading();
      this.loadPersistedColumnScrollPositions();
      this.loadPersistedBoardHorizontalScrollPosition();
      this.loadPersistedExpandedCardState();
      window.addEventListener('beforeunload', this.beforeUnloadHandler);

      if (!this.isPublicMode) {
        this.loadPersistedAssigneeFilterVisibility();
        this.watchForAssigneeFilterVisibilityUser();
        this.bindSearchInputEvents();
        this.watchForHeaderSearchControl();
        this.notifyBoardFilterVisibilityChanged();
        window.addEventListener('boardFiltersToggleRequested', this.boardFiltersToggleRequestHandler);
        window.addEventListener('boardFiltersStateRequest', this.boardFiltersStateRequestHandler);
        window.addEventListener('boardFiltersClearRequest', this.boardFiltersClearRequestHandler);
        window.addEventListener('boardWorkingStyleChanged', this.boardWorkingStyleChangedHandler);

        // Initialize WebSocket for real-time updates
        this.wsManager = new WebSocketManager(this.boardId, this);
      } else {
        this.canEdit = false;
      }
      
      // Load working style preference
      await this.loadWorkingStyle();
      
      await this.loadBoard();
      if (!this.isPublicMode) {
        this.notifyBoardFilterActiveStateChanged();
      }
      this.setupBoardTouchScrolling();
      this.setupMobileViewportSync();
      this.setupKeyboardShortcuts();
      this.setupDropdownClickOutside();
      this.setupViewListener();
    } finally {
      this.isBootstrappingBoard = false;
    }
  }

  async loadWorkingStyle() {
    const normalize = (value) => {
      if (value === 'board_task_category') {
        return 'agile';
      }
      return value === 'agile' ? 'agile' : 'kanban';
    };

    if (this.isPublicMode) {
      this.workingStyle = 'kanban';
      this.updateArchivedViewVisibility();
      return;
    }

    const headerWorkingStylePromise = window.header?.workingStyleLoadPromise;
    if (window.header?.currentBoardId === this.boardId && headerWorkingStylePromise) {
      try {
        await headerWorkingStylePromise;
        this.workingStyle = normalize(window.header.workingStyle);
        this.updateArchivedViewVisibility();
        return;
      } catch (error) {
        console.warn('Falling back to board working style fetch after header load failure:', error);
      }
    }

    try {
      const response = await fetch(`/api/boards/${this.boardId}/settings/working-style`);
      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          this.workingStyle = normalize(data.value);
        }
      } else if (response.status === 404) {
        // Setting doesn't exist, default to kanban
        this.workingStyle = 'kanban';
      }
    } catch (error) {
      console.error('Error loading working style:', error);
      this.workingStyle = 'kanban';
    }

    // Update archived view visibility based on working style
    this.updateArchivedViewVisibility();
  }

  syncPublicHeaderWorkingStyle() {
    if (!this.isPublicMode || !window.header) {
      return;
    }

    const applyWorkingStyle = () => {
      const dropdownMenu = document.getElementById('views-dropdown-menu');
      if (!dropdownMenu || typeof window.header.updateViewsDropdown !== 'function') {
        return false;
      }

      window.header.workingStyle = this.workingStyle;
      window.header.updateViewsDropdown();
      return true;
    };

    if (applyWorkingStyle()) {
      return;
    }

    if (typeof MutationObserver === 'function' && document.body) {
      const observer = new MutationObserver(() => {
        if (applyWorkingStyle()) {
          observer.disconnect();
        }
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true
      });
      return;
    }

    let attempts = 0;
    const maxAttempts = 20;
    const intervalId = window.setInterval(() => {
      attempts += 1;
      if (applyWorkingStyle() || attempts >= maxAttempts) {
        window.clearInterval(intervalId);
      }
    }, 250);
  }

  // Hide/show archived view option based on working style
  updateArchivedViewVisibility() {
    // Try to apply visibility immediately; if elements are not yet in the DOM,
    // wait for them to be inserted (header HTML is loaded asynchronously).
    const applyVisibility = () => {
      const archivedViewItem = document.querySelector('.views-dropdown-item[data-view="archived"]');
      const mobileArchivedViewItem = document.querySelector('.mobile-view-item[data-view="archived"]');
      const scheduledViewItem = document.querySelector('.views-dropdown-item[data-view="scheduled"]');
      const mobileScheduledViewItem = document.querySelector('.mobile-view-item[data-view="scheduled"]');

      // If neither element exists yet, signal that we need to retry later
      if (!archivedViewItem && !mobileArchivedViewItem && !scheduledViewItem && !mobileScheduledViewItem) {
        return false;
      }

      const displayValue = this.workingStyle === 'agile' ? 'none' : '';

      if (archivedViewItem) {
        archivedViewItem.style.display = displayValue;
      }
      if (mobileArchivedViewItem) {
        mobileArchivedViewItem.style.display = displayValue;
      }

      const scheduledDisplayValue = this.isPublicMode ? 'none' : '';
      if (scheduledViewItem) {
        scheduledViewItem.style.display = scheduledDisplayValue;
      }
      if (mobileScheduledViewItem) {
        mobileScheduledViewItem.style.display = scheduledDisplayValue;
      }

      return true;
    };

    // If we can apply immediately, no need to observe for changes.
    if (applyVisibility()) {
      return;
    }

    // Fallback: observe DOM mutations until the archived view items appear.
    if (typeof MutationObserver === 'function' && document.body) {
      const observer = new MutationObserver(() => {
        if (applyVisibility()) {
          observer.disconnect();
        }
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true
      });
    } else {
      // Very old environments: use a short polling loop as a last resort.
      let attempts = 0;
      const maxAttempts = 20;
      const intervalId = window.setInterval(() => {
        attempts += 1;
        if (applyVisibility() || attempts >= maxAttempts) {
          window.clearInterval(intervalId);
        }
      }, 250);
    }
  }

  setupViewListener() {
    // Listen for view changes from header
    window.addEventListener('viewChanged', async (e) => {
      const newView = e.detail.view;

      if (this.isPublicMode && (newView === 'scheduled' || newView === 'planner')) {
        if (window.header && typeof window.header.setView === 'function') {
          window.header.setView('task');
        }
        return;
      }

      if (newView === 'planner') {
        const initialRender = this._pendingPlannerRender;
        this._pendingPlannerRender = null;
        this.showPlannerView(initialRender);
        return;
      }

      // Leaving the planner view: hide it and fall through to the normal board render
      this.hidePlannerView();

      // Show loading overlay
      this.showBoardLoading();

      // Map view names to internal state
      if (newView === 'archived') {
        this.currentView = 'task';
        this.showArchived = true;
      } else if (newView === 'scheduled') {
        this.currentView = 'scheduled';
        this.showArchived = false;
      } else if (newView === 'done') {
        this.currentView = 'task';
        this.showArchived = false;
        this.showDone = true;
      } else { // 'task'
        this.currentView = 'task';
        this.showArchived = false;
        this.showDone = false;
      }

      await this.loadBoard();
    });
  }

  // `initialRender(plannerView)`, when given, replaces the default "open on
  // the current year" landing render - e.g. jumping straight to a specific
  // month, or entering placement mode. Without it, two renders (the default
  // here and a caller's follow-up one) would both fire their own fetches
  // and race to paint the container last.
  showPlannerView(initialRender) {
    if (!this.plannerContainer) {
      this.plannerContainer = document.getElementById('planner-container');
    }
    if (!this.plannerContainer) return;

    if (!this.plannerView) {
      this.plannerView = new PlannerView(this.boardId, this.plannerContainer, this);
    }

    this.container.style.display = 'none';
    this.plannerContainer.style.display = 'block';

    if (initialRender) {
      initialRender(this.plannerView);
    } else {
      this.plannerView.renderYear(new Date().getFullYear());
    }
  }

  hidePlannerView() {
    if (this.plannerContainer) {
      this.plannerContainer.style.display = 'none';
    }
    this.container.style.display = '';
  }

  // Re-render whatever the planner is currently showing (year or month) so
  // card changes - from this client or another - show up immediately
  // without the user having to navigate away and back.
  refreshPlannerIfVisible() {
    if (!this.plannerView || !this.plannerContainer || this.plannerContainer.style.display === 'none') {
      return;
    }
    if (this.plannerView.mode === 'year') {
      this.plannerView.renderYear(this.plannerView.currentYear);
    } else {
      this.plannerView.renderMonth(this.plannerView.currentYear, this.plannerView.currentMonth);
    }
  }

  async handleBoardWorkingStyleChanged(event) {
    const nextStyle = event?.detail?.workingStyle;
    if (!nextStyle) {
      return;
    }

    this.workingStyle = nextStyle;

    // When switching to Agile, reset to task view (agile has done view instead of archived)
    // When switching from Agile to Kanban, also reset (agile features no longer apply)
    if (this.workingStyle === 'agile' && (this.showArchived || this.showDone)) {
      this.showArchived = false;
      this.showDone = false;
      this.currentView = 'task';
      if (window.header && typeof window.header.setView === 'function') {
        window.header.setView('task');
      }
    } else if (this.workingStyle !== 'agile' && this.showDone) {
      this.showDone = false;
      this.currentView = 'task';
      this.showArchived = false;
      if (window.header && typeof window.header.setView === 'function') {
        window.header.setView('task');
      }
    }

    // Update archived view visibility based on new working style
    this.updateArchivedViewVisibility();

    await this.loadBoard();
  }

  setupDropdownClickOutside() {
    // Add click-outside handler once for all dropdowns
    document.addEventListener('click', this.closeDropdownHandler);
  }

  render() {
    // Keep initial render empty; loading state is handled by board-loading-overlay.
    this.container.innerHTML = '';
  }

  async loadBoard() {
    // Ignore duplicate startup reloads while the first board request is still in flight.
    if (this.isBootstrappingBoard && this.currentLoadController && !this.hasLoadedBoardData) {
      return;
    }

    this.stopColumnAutoScroll();
    this.captureColumnScrollPositions();
    this.captureBoardHorizontalScrollPosition();
    this.captureExpandedCardState();
    this.showBoardLoading();

    // Cancel any in-flight board load request
    if (this.currentLoadController) {
      this.currentLoadController.abort();
    }

    // Capture current view state
    const viewState = {
      currentView: this.currentView,
      showArchived: this.showArchived
    };
    this.currentViewState = viewState;
    const maxAttempts = this.hasLoadedBoardData ? 1 : MAX_INITIAL_BOARD_LOAD_ATTEMPTS;

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      const requestController = new AbortController();
      this.currentLoadController = requestController;
      const requestTimeoutMs = this.getBoardLoadTimeoutMs(attempt);
      const timeoutId = setTimeout(() => requestController.abort(), requestTimeoutMs);

      try {
        let response;

        if (this.isPublicMode) {
          const queryParams = new URLSearchParams();
          queryParams.set('archived', this.showArchived ? 'true' : 'false');

          if (this.workingStyle === 'agile') {
            queryParams.set('done', this.showDone ? 'true' : 'false');
          } else {
            queryParams.set('done', 'both');
          }

          response = await fetch(`/api/public/boards/${encodeURIComponent(this.publicSlug)}?${queryParams.toString()}`, {
            signal: requestController.signal
          });
        } else if (this.currentView === 'scheduled') {
          // Load board with all scheduled cards in a single request
          const scheduledParams = this.buildAssigneeFilterQueryParams();
          const scheduledQuery = scheduledParams.toString();
          const scheduledUrl = scheduledQuery
            ? `/api/boards/${this.boardId}/cards/scheduled?${scheduledQuery}`
            : `/api/boards/${this.boardId}/cards/scheduled`;

          response = await fetch(scheduledUrl, {
            signal: requestController.signal
          });
        } else {
          // Load board with nested structure (board -> columns -> cards)
          // Add archived parameter to filter cards based on showArchived state
          const queryParams = this.buildAssigneeFilterQueryParams();
          queryParams.set('archived', this.showArchived ? 'true' : 'false');
          response = await fetch(`/api/boards/${this.boardId}/cards?${queryParams.toString()}`, {
            signal: requestController.signal
          });
        }
        
        clearTimeout(timeoutId);
        
        // Check if this request is stale (view changed while loading)
        if (this.currentViewState !== viewState) {
          return;
        }
        
        const data = await this.parseResponse(response);
        
        // Check again after parsing in case view changed
        if (this.currentViewState !== viewState) {
          return;
        }

        if (!data.success) {
          const canRetryParseFailure = data.parseFailed === true && attempt < maxAttempts;
          if (canRetryParseFailure) {
            continue;
          }
          this.showBoardLoadFailureMessage(
            data.parseFailed === true,
            data.parseFailureType || null,
            data.message || ''
          );
          return;
        }

        const board = data.board;
        this.processBoard(board);
        // Cache only after a successful board load so header links target valid/authorized boards.
        if (!this.isPublicMode && this.boardId) {
          sessionStorage.setItem('lastVisitedBoardId', String(this.boardId));
        }
        this.hideBoardLoading();
        return;
      } catch (error) {
        clearTimeout(timeoutId);
        
        // Ignore aborted requests (they were intentionally cancelled)
        if (error.name === 'AbortError') {
          const canRetryTimeout = this.currentViewState === viewState && attempt < maxAttempts;
          if (canRetryTimeout) {
            continue;
          }

          // Only show error if this was the timeout abort, not a cancellation
          if (this.currentViewState === viewState) {
            this.hideBoardLoading();
            this.showErrorToast(`Load board timed out (${Math.round(requestTimeoutMs / 1000)}s). Please check your connection.`);
            this.showError('Load board timed out. Please check your connection.');
          }
          return;
        }
        
        // Only process errors for non-stale requests
        if (this.currentViewState === viewState) {
          console.error('Error loading board:', error);
          this.showBoardLoadUnexpectedErrorMessage();
        }
        return;
      } finally {
        // Always clear current load controller if this was the active request
        // This ensures cleanup even if there's an unexpected error path
        if (this.currentLoadController === requestController) {
          this.currentLoadController = null;
        }
      }
    }
  }

  processBoard(board) {
    try {
      if (this.isPublicMode && board && board.default_theme) {
        this.applyPublicBoardTheme(board.default_theme);
      }

      this.boardName = board.name;
      if (this.isPublicMode && Number.isInteger(board.id) && board.id > 0) {
        this.boardId = board.id;
      }

      if (typeof board.working_style === 'string') {
        const normalizedWorkingStyle = board.working_style === 'board_task_category'
          ? 'agile'
          : (board.working_style === 'agile' ? 'agile' : 'kanban');
        this.workingStyle = normalizedWorkingStyle;
        this.syncPublicHeaderWorkingStyle();
      }

      const isBoardPublic = board.is_public === true;
      this.isBoardPublic = isBoardPublic;
      this.boardArchived = board.archived === true;
      if (isBoardPublic && typeof board.public_slug === 'string' && board.public_slug.length > 0) {
        this.publicSlug = board.public_slug;
      } else {
        this.publicSlug = null;
      }
      this.publicBoardShareUrl = this.getPublicBoardShareUrl(this.publicSlug);

      this.boardOwnerData = {
        owner_id: board.owner_id,
        owner: board.owner || null,
        can_reassign_owner: board.can_reassign_owner === true,
        available_owner_users: Array.isArray(board.available_owner_users) ? board.available_owner_users : []
      };
      this.assigneeFilterUsers = this.isPublicMode
        ? []
        : (Array.isArray(board.assignee_filter_users) ? board.assignee_filter_users : []);

      const eligibleUserIds = new Set(this.assigneeFilterUsers.map((u) => u.id));
      this.assigneeFilterSelectedUserIds = new Set(
        Array.from(this.assigneeFilterSelectedUserIds).filter((userId) => eligibleUserIds.has(userId))
      );

      // Store the original unfiltered columns for counting purposes
      this.originalColumns = JSON.parse(JSON.stringify(board.columns));
      this.columns = board.columns;
      
      // Store edit permission flag (default to true for backwards compatibility)
      this.canEdit = this.isPublicMode ? false : (board.can_edit !== undefined ? board.can_edit : true);
      this.updateArchivedViewVisibility();
      
      // Filter cards based on done status and view
      if (this.workingStyle === 'agile') {
        if (this.showDone) {
          // In done view, show only cards where done=true
          this.columns = this.columns.map(column => ({
            ...column,
            cards: (column.cards || []).filter(card => card.done)
          }));
        } else {
          // In task view, show only cards where done=false
          this.columns = this.columns.map(column => ({
            ...column,
            cards: (column.cards || []).filter(card => !card.done)
          }));
        }
      }
      
      // Update header with board name and page title
      this.updateBoardTitle();
      if (!this.isPublicMode) {
        window.dispatchEvent(new CustomEvent('boardOwnerDataLoaded', {
          detail: {
            boardId: this.boardId,
            can_edit: this.canEdit,
            is_public: this.isBoardPublic,
            archived: this.boardArchived,
            public_slug: this.publicSlug,
            ...this.boardOwnerData,
          }
        }));
      }

      if (window.header && typeof window.header.setPublicBoardContext === 'function') {
        window.header.setPublicBoardContext({
          isPublicBoard: isBoardPublic,
          publicUrl: this.publicBoardShareUrl || '',
          isPublicPage: this.isPublicMode,
          showLoginCta: this.isPublicMode && !window.currentUser,
        });
      }

      this.hasLoadedBoardData = true;
      
      this.renderBoard();
    } catch (err) {
      this.showError('Error loading board: ' + err.message);
    }
  }

  applyPublicBoardTheme(theme) {
    if (!theme || !theme.settings || typeof theme.settings !== 'object') {
      return;
    }

    const root = document.documentElement;
    const body = document.body;
    const safeNamePattern = /^[A-Za-z0-9-]+$/;
    let appliedThemeValue = false;
    Object.entries(theme.settings).forEach(([key, value]) => {
      if (typeof key !== 'string' || typeof value !== 'string') {
        return;
      }

      if (!safeNamePattern.test(key)) {
        return;
      }

      const trimmedValue = value.trim();
      if (!trimmedValue) {
        return;
      }

      if (typeof CSS !== 'undefined' && typeof CSS.supports === 'function' && !CSS.supports('color', trimmedValue)) {
        return;
      }

      root.style.setProperty(`--${key}`, trimmedValue);
      if (body) {
        body.style.setProperty(`--${key}`, trimmedValue);
      }
      appliedThemeValue = true;
    });

    if (appliedThemeValue && body) {
      body.classList.remove('public-board-theme-default');
    }

    const backgroundImage = typeof theme.background_image === 'string' ? theme.background_image.trim() : '';
    const safeBackground = /^[A-Za-z0-9_.-]+$/.test(backgroundImage) ? backgroundImage : '';
    if (safeBackground) {
      root.style.setProperty('--background-image', `url('/images/backgrounds/${safeBackground}')`);
      if (body) {
        body.style.setProperty('--background-image', `url('/images/backgrounds/${safeBackground}')`);
      }
    } else {
      root.style.setProperty('--background-image', 'none');
      if (body) {
        body.style.setProperty('--background-image', 'none');
      }
    }
  }

  updateBoardTitle() {
    // Update page title
    document.title = `AFT - ${this.boardName}`;
    
    // Update header navbar with board name
    if (window.header) {
      window.header.setBoardName(this.boardName);
    }
  }

  setupKeyboardShortcuts() {
    document.addEventListener('keydown', this.keyboardHandler);
  }

  handleKeydown(e) {
    // Don't trigger shortcuts if user is typing in an input/textarea
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
      return;
    }

    // Don't trigger if any visible modal is open on the page
    const anyModalOpen = Array.from(document.querySelectorAll('.modal')).some((modal) => {
      const style = window.getComputedStyle(modal);
      return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
    });
    if (anyModalOpen) {
      return;
    }

    // Don't trigger if board is read-only
    if (!this.canEdit) {
      return;
    }

    // 'n' key - add card at top of column
    if (e.key === 'n' || e.key === 'N') {
      e.preventDefault();
      const columnId = this.hoveredColumnId || this.lastUsedColumnId;
      if (columnId) {
        const scheduled = this.currentView === 'scheduled';
        this.openAddCardModal(columnId, 0, scheduled); // 0 = top
      }
    }

    // 'm' key - add card at bottom of column
    if (e.key === 'm' || e.key === 'M') {
      e.preventDefault();
      const columnId = this.hoveredColumnId || this.lastUsedColumnId;
      if (columnId) {
        const scheduled = this.currentView === 'scheduled';
        this.openAddCardModal(columnId, null, scheduled); // default = bottom
      }
    }
  }

  cleanup() {
    // Remove event listeners to prevent memory leaks
    document.removeEventListener('keydown', this.keyboardHandler);
    document.removeEventListener('click', this.closeDropdownHandler);
    window.removeEventListener('beforeunload', this.beforeUnloadHandler);
    window.removeEventListener('boardFiltersToggleRequested', this.boardFiltersToggleRequestHandler);
    window.removeEventListener('boardFiltersStateRequest', this.boardFiltersStateRequestHandler);
    window.removeEventListener('boardFiltersClearRequest', this.boardFiltersClearRequestHandler);
    window.removeEventListener('boardWorkingStyleChanged', this.boardWorkingStyleChangedHandler);
    window.removeEventListener('resize', this.viewportMetricsHandler);
    window.removeEventListener('orientationchange', this.viewportMetricsHandler);

    if (this.searchDebounceTimer) {
      clearTimeout(this.searchDebounceTimer);
      this.searchDebounceTimer = null;
    }

    if (this.searchInputWatcherId) {
      clearInterval(this.searchInputWatcherId);
      this.searchInputWatcherId = null;
    }

    if (this.assigneeFilterVisibilityWatcherId) {
      clearInterval(this.assigneeFilterVisibilityWatcherId);
      this.assigneeFilterVisibilityWatcherId = null;
    }

    if (window.visualViewport) {
      window.visualViewport.removeEventListener('resize', this.viewportMetricsHandler);
      window.visualViewport.removeEventListener('scroll', this.viewportMetricsHandler);
    }

    if (this.container && this.boardTouchScrollingSetup) {
      this.container.removeEventListener('touchstart', this.boardTouchStartHandler);
      this.container.removeEventListener('touchmove', this.boardTouchMoveHandler);
      this.container.removeEventListener('touchend', this.boardTouchEndHandler);
      this.container.removeEventListener('touchcancel', this.boardTouchEndHandler);
      this.container.removeEventListener('contextmenu', this.boardContextMenuHandler);
      this.boardTouchScrollingSetup = false;
    }
    this.resetBoardTouchScrollingState();

    if (this.viewportMetricsRafId) {
      cancelAnimationFrame(this.viewportMetricsRafId);
      this.viewportMetricsRafId = null;
    }

    if (this.persistScrollTimeoutId) {
      clearTimeout(this.persistScrollTimeoutId);
      this.persistScrollTimeoutId = null;
    }

    if (this.persistBoardHorizontalScrollTimeoutId) {
      clearTimeout(this.persistBoardHorizontalScrollTimeoutId);
      this.persistBoardHorizontalScrollTimeoutId = null;
    }

    this.stopColumnAutoScroll();

    this.persistColumnScrollPositions();
    this.persistBoardHorizontalScrollPosition();
    this.persistExpandedCardState();
  }

  handleCloseDropdown(e) {
    if (!e.target.closest('.column-menu-wrapper')) {
      document.querySelectorAll('.column-menu-dropdown').forEach(d => {
        d.classList.remove('show');
      });
    }
  }

  async toggleArchiveView() {
    // Toggle the showArchived state
    this.showArchived = !this.showArchived;
    // Reload board with new archived parameter
    await this.loadBoard();
  }

  /**
   * Get the card count display for a column.
  * In agile mode:
   *   - Task view: shows "done/total" format using original unfiltered data
   *   - Done view: shows only count of done cards
   * Otherwise, shows just the total count.
   * 
   * All counts exclude archived and scheduled template cards.
   * 
   * @param {Object} column - The column object with cards array
   * @param {number} columnIndex - The index of the column in the columns array
   * @returns {string} Card count display string
   */
  getColumnCardCount(column, columnIndex) {
    if (!column.cards) return '0';
    
    if (this.workingStyle === 'agile') {
      // Use original unfiltered column data for accurate counts
      const originalColumn = this.originalColumns[columnIndex];
      if (!originalColumn || !originalColumn.cards) return '0';
      
      // Count all active cards (non-archived, non-scheduled) in the original data
      const allActiveCards = originalColumn.cards.filter(card => !card.archived && !card.scheduled);
      const doneCards = allActiveCards.filter(card => card.done);
      
      if (this.currentView === 'task' && !this.showArchived) {
        // Task view: show done/total format
        return `${doneCards.length}/${allActiveCards.length}`;
      } else if (this.showDone) {
        // Done view: show only done count
        return doneCards.length.toString();
      }
    }
    
    // Default behavior: just show total count
    return column.cards.length.toString();
  }

  renderAssigneeFilterBar() {
    if (!this.assigneeFilterVisible) {
      return '';
    }

    const userButtons = (this.assigneeFilterUsers || []).map((user) => {
      const displayName = user.display_name || user.username || 'Unknown';
      const selected = this.assigneeFilterSelectedUserIds.has(user.id);
      return `
        <button
          type="button"
          class="assignee-filter-avatar-btn ${selected ? 'selected' : ''}"
          data-assignee-id="${user.id}"
          title="${this.escapeHtml(displayName)}"
          aria-label="Filter ${this.escapeHtml(displayName)}"
          aria-pressed="${selected ? 'true' : 'false'}"
        >
          <span class="assignee-filter-avatar" style="background-color:${this.escapeHtml(user.profile_colour || '#90A4AE')}">
            ${this.escapeHtml(this.getInitials(displayName))}
          </span>
        </button>
      `;
    }).join('');

    const unassignedSelected = this.assigneeFilterIncludeUnassigned;
    return `
      <div class="board-assignee-filter-row">
        <div class="board-assignee-filter-bar" role="region" aria-label="Board assignee filters">
          <div class="board-assignee-filter-users" role="group" aria-label="Filter by assignee">
            ${userButtons}
            <button
              type="button"
              class="assignee-filter-avatar-btn assignee-filter-unassigned-btn ${unassignedSelected ? 'selected' : ''}"
              data-assignee-unassigned="true"
              title="Unassigned"
              aria-label="Filter unassigned cards"
              aria-pressed="${unassignedSelected ? 'true' : 'false'}"
            >
              <span class="assignee-filter-avatar assignee-filter-avatar-unassigned">U</span>
            </button>
            <label class="assignee-filter-secondary-toggle">
              <input
                type="checkbox"
                id="include-secondary-assignees-toggle"
                ${this.assigneeFilterIncludeSecondaryAssignees ? 'checked' : ''}
              >
              <span>Include secondary assignees</span>
            </label>
          </div>
          <div class="board-filter-search-control board-search-control-inline">
            <label class="visually-hidden" for="board-filter-search-input">Search board cards</label>
            <div class="board-search-input-wrap board-search-tooltip-wrap">
              <input
                type="text"
                id="board-filter-search-input"
                class="board-search-input"
                placeholder="Search cards"
                value="${this.escapeHtml(this.searchQueryRaw)}"
                maxlength="200"
                aria-label="Search board cards"
                aria-describedby="board-filter-search-tooltip"
                autocomplete="off"
                spellcheck="false"
              >
              <button
                type="button"
                id="board-filter-search-clear-btn"
                class="board-search-clear-btn"
                aria-label="Clear board search"
                title="Clear search"
                style="display:${this.searchQueryRaw ? 'inline-flex' : 'none'}"
              >
                x
              </button>
              <div
                class="board-search-tooltip"
                id="board-filter-search-tooltip"
                role="tooltip"
              >${this.escapeHtml(this.getSearchTooltipText())}</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  setupAssigneeFilterBarListeners() {
    if (!this.assigneeFilterVisible) {
      return;
    }

    this.bindSearchInputEvents();

    const assigneeButtons = this.container.querySelectorAll('.assignee-filter-avatar-btn');
    assigneeButtons.forEach((button) => {
      button.addEventListener('click', async () => {
        const isUnassigned = button.getAttribute('data-assignee-unassigned') === 'true';
        if (isUnassigned) {
          this.assigneeFilterIncludeUnassigned = !this.assigneeFilterIncludeUnassigned;
        } else {
          const rawUserId = button.getAttribute('data-assignee-id');
          const parsedUserId = parseInt(rawUserId, 10);
          if (!Number.isNaN(parsedUserId)) {
            if (this.assigneeFilterSelectedUserIds.has(parsedUserId)) {
              this.assigneeFilterSelectedUserIds.delete(parsedUserId);
            } else {
              this.assigneeFilterSelectedUserIds.add(parsedUserId);
            }
          }
        }

        this.notifyBoardFilterActiveStateChanged();
        await this.loadBoard();
      });
    });

    const includeSecondaryToggle = this.container.querySelector('#include-secondary-assignees-toggle');
    if (includeSecondaryToggle) {
      includeSecondaryToggle.addEventListener('change', async (event) => {
        this.assigneeFilterIncludeSecondaryAssignees = !!event.target.checked;
        await this.loadBoard();
      });
    }

    this.restoreSearchInputFocusIfNeeded();
  }

  renderBoard() {
    this.stopColumnAutoScroll();

    // Show/hide views dropdown in header based on columns
    if (window.header) {
      window.header.showViewsDropdown(this.columns.length > 0);
    }
    
    // Add or remove read-only class from container
    if (!this.canEdit) {
      this.container.classList.add('board-readonly');
    } else {
      this.container.classList.remove('board-readonly');
    }
    
    if (this.columns.length === 0) {
      
      this.container.innerHTML = `
        ${this.renderAssigneeFilterBar()}
        <div class="empty-board-panel">
          <div class="empty-board">
            <div class="empty-board-icon">📋</div>
            <h3>No columns yet</h3>
            <p>Add your first column to start organising tasks!</p>
            ${this.canEdit ? '<button class="btn btn-primary" id="add-column-empty-btn">+ Add Column</button>' : '<p style="color: var(--secondary-color); margin-top: 10px;">Read-only access - cannot add columns</p>'}
          </div>
        </div>
      `;
      
      // Add event listener for add column button
      if (this.canEdit) {
        const addColumnEmptyBtn = document.getElementById('add-column-empty-btn');
        if (addColumnEmptyBtn) {
          addColumnEmptyBtn.addEventListener('click', () => this.openAddColumnModal());
        }
      }

      this.setupAssigneeFilterBarListeners();
    } else {
      const canCreateCardsInTaskView = this.canEdit || this.canCallPermissionEndpoint('POST', '/api/columns/:id/cards');
      const canCreateSchedules = this.canCallPermissionEndpoint('POST', '/api/schedules');
      const canCreateCardsInCurrentView = this.currentView === 'scheduled'
        ? (canCreateCardsInTaskView && canCreateSchedules)
        : canCreateCardsInTaskView;
      const canUpdateColumns = this.canEdit || this.canCallPermissionEndpoint('PATCH', '/api/columns/:id');
      const canArchiveCard = this.canCallPermissionEndpoint('PATCH', '/api/cards/:id/archive');
      const canUnarchiveCard = this.canCallPermissionEndpoint('PATCH', '/api/cards/:id/unarchive');
      const canDeleteCard = this.canCallPermissionEndpoint('DELETE', '/api/cards/:id');
      const canToggleDone = this.canCallPermissionEndpoint('PATCH', '/api/cards/:id/done');
      const canMoveCard = this.canEdit || this.canCallPermissionEndpoint('PATCH', '/api/cards/:id');
      const canShowCardActions = canArchiveCard || canUnarchiveCard || canDeleteCard || canMoveCard ||
        (this.workingStyle === 'agile' && canToggleDone);
      const canShowColumnMenu = this.canShowColumnMenu();

      this.container.innerHTML = `
        ${!this.canEdit ? '<div class="board-readonly-indicator">Read Only</div>' : ''}
        ${this.renderAssigneeFilterBar()}
        <div class="columns-container">
          ${this.columns.map((column, index) => `
            <div class="column" data-column-id="${column.id}" data-board-id="${this.escapeHtml(String(this.boardId))}" data-order="${column.order}">
              <div class="column-header">
                <div class="column-title-group">
                  <h4>${this.escapeHtml(column.name)} <span class="card-count">(${this.getColumnCardCount(column, index)})</span></h4>
                </div>
                <div class="column-actions">
                  ${!this.showArchived && canCreateCardsInCurrentView ? `<button class="column-add-card-btn" data-column-id="${column.id}" title="Add card">+</button>` : ''}
                  ${canShowColumnMenu ? `
                  <div class="column-menu-wrapper">
                    <button class="column-menu-btn" data-column-id="${column.id}" title="Column menu">⋮</button>
                    <div class="column-menu-dropdown" data-column-id="${column.id}">
                      ${!this.showArchived && canCreateCardsInCurrentView ? `
                        <button class="column-menu-item column-menu-add-card-btn" data-column-id="${column.id}">
                          <span>+</span>
                          <span>Add card</span>
                        </button>
                      ` : ''}
                      ${canUpdateColumns ? `
                        <button class="column-menu-item column-menu-rename-btn" data-column-id="${column.id}" data-column-name="${this.escapeHtml(column.name)}">
                          <span>✎</span>
                          <span>Rename column</span>
                        </button>
                        <button class="column-menu-item column-menu-move-left-btn" data-column-id="${column.id}" data-order="${column.order}">
                          <span>◀</span>
                          <span>Move left</span>
                        </button>
                        <button class="column-menu-item column-menu-move-right-btn" data-column-id="${column.id}" data-order="${column.order}">
                          <span>▶</span>
                          <span>Move right</span>
                        </button>
                      ` : ''}
                      <button class="column-menu-item column-move-all-cards-btn" data-column-id="${column.id}">
                        <span class="icon-span">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M7 8l3 3-3 3"></path>
                            <path d="M14 8l3 3-3 3"></path>
                          </svg>
                        </span>
                        <span>Move all cards...</span>
                      </button>
                      ${this.showArchived ? `
                        <button class="column-menu-item column-unarchive-all-cards-btn" data-column-id="${column.id}">
                          <span class="icon-span">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                              <path d="M12 2v10"></path>
                              <path d="M7 7l5-5 5 5"></path>
                              <rect x="2" y="13" width="20" height="9" rx="2"></rect>
                            </svg>
                          </span>
                          <span>Unarchive all cards</span>
                        </button>
                      ` : `
                        <button class="column-menu-item column-archive-all-cards-btn" data-column-id="${column.id}">
                          <span class="icon-span">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                              <path d="M12 10v4"></path>
                              <path d="M7 15l5 5 5-5"></path>
                              <rect x="2" y="3" width="20" height="8" rx="2"></rect>
                            </svg>
                          </span>
                          <span>Archive all cards</span>
                        </button>
                        <button class="column-menu-item column-archive-after-btn" data-column-id="${column.id}">
                          <span class="icon-span">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                              <circle cx="12" cy="12" r="10"></circle>
                              <polyline points="12 6 12 12 16 14"></polyline>
                            </svg>
                          </span>
                          <span>Archive after...</span>
                        </button>
                      `}
                      <button class="column-menu-item column-delete-cards-btn" data-column-id="${column.id}">
                        <span>🗑</span>
                        <span>Delete all cards</span>
                      </button>
                      <button class="column-menu-item column-delete-btn" data-column-id="${column.id}">
                        <span>×</span>
                        <span>Delete column</span>
                      </button>
                    </div>
                  </div>` : ''}
                </div>
              </div>
              <div class="column-cards" data-column-id="${column.id}">
                ${column.cards && column.cards.length > 0 ? 
                  column.cards.map(card => `
                    <div class="card ${card.archived ? 'archived-card' : ''} ${this.currentView === 'scheduled' && !card.schedule ? 'no-schedule' : ''} ${card.assigned_to ? 'card--has-assignee' : ''}" draggable="${!card.archived && this.canEdit}" data-card-id="${card.id}" data-column-id="${column.id}" data-order="${card.order}" data-archived="${card.archived}" data-done="${card.done || false}">
                      ${canShowCardActions ? `<div class="card-action-buttons" draggable="false">`  : '<div class="card-action-buttons readonly-hidden" draggable="false">'}
                        ${this.currentView === 'scheduled' ? '' : 
                          card.archived ? 
                            `${canUnarchiveCard ? `<button class="card-unarchive-btn" data-card-id="${card.id}" title="Unarchive card" draggable="false">
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <rect x="3" y="4" width="18" height="16" rx="2"></rect>
                                <line x1="3" y1="10" x2="21" y2="10"></line>
                                <path d="M12 14v-2"></path>
                                <path d="M9 14l3 2 3-2"></path>
                              </svg>
                            </button>` : ''}` :
                            `${this.workingStyle === 'agile' ? 
                              `${canToggleDone ? `<button class="card-done-btn" data-card-id="${card.id}" title="${card.done ? 'Mark as not done' : 'Mark as done'}" draggable="false">
                                ${card.done ? '○' : '✓'}
                              </button>` : ''}` :
                              `${canArchiveCard ? `<button class="card-archive-btn" data-card-id="${card.id}" title="Archive card" draggable="false">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                  <rect x="3" y="4" width="18" height="16" rx="2"></rect>
                                  <line x1="3" y1="10" x2="21" y2="10"></line>
                                  <path d="M12 14v2"></path>
                                  <path d="M9 16l3-2 3 2"></path>
                                </svg>
                              </button>` : ''}`
                            }`
                        }
                        ${!card.archived && canMoveCard ? '<button class="card-move-btn" data-card-id="' + card.id + '" title="Move card" draggable="false">↔</button>' : ''}
                        ${canDeleteCard ? '<button class="card-delete-btn" data-card-id="' + card.id + '" title="Delete card" draggable="false">×</button>' : ''}
                      </div>
                      <div class="card-content-wrapper" id="card-content-${card.id}">
                        <h5 class="card-title">${linkifyUrls(this.escapeHtml(card.title))}</h5>
                        <p class="card-description">${linkifyUrls(this.escapeHtml(card.description))}</p>
                        ${card.updated_at || (card.comments && card.comments.length > 0) ? `
                          <div class="card-meta-row">
                            ${card.comments && card.comments.length > 0 ? `
                              <div class="card-comments-indicator">
                                💬 ${card.comments.length} ${card.comments.length === 1 ? 'comment' : 'comments'}
                              </div>
                            ` : ''}
                            ${card.updated_at ? `
                              <div class="card-timestamp" data-tooltip="${formatTooltipDateTime(card.updated_at)}" aria-label="Last updated ${formatTooltipDateTime(card.updated_at)}" tabindex="0">
                                ${formatTimeAgo(card.updated_at)}
                              </div>
                            ` : ''}
                          </div>
                        ` : ''}
                        ${card.checklist_items && card.checklist_items.length > 0 ? `
                          <div class="card-checklist">
                            <div class="card-checklist-summary">
                              ${card.checklist_items.filter(i => i.checked).length}/${card.checklist_items.length} (${calculateChecklistPercentage(card.checklist_items)}%)
                            </div>
                            ${card.checklist_items.map(item => `
                              <div class="card-checklist-item">
                                <input 
                                  type="checkbox" 
                                  class="card-checklist-checkbox" 
                                  data-item-id="${item.id}"
                                  ${item.checked ? 'checked' : ''}
                                  ${!this.canEdit ? 'disabled' : ''}
                                >
                                <span class="card-checklist-name ${item.checked ? 'checked' : ''}">${linkifyUrls(this.escapeHtml(item.name))}</span>
                              </div>
                            `).join('')}
                          </div>
                        ` : ''}
                      </div>
                      <button class="card-expand-btn" data-card-id="${card.id}" role="button" aria-expanded="false" aria-controls="card-content-${card.id}">Show more...</button>
                      ${card.assigned_to ? `<div class="card-assignee-avatar" style="background-color:${this.escapeHtml(card.assigned_to.profile_colour || '#90A4AE')}" title="${this.escapeHtml(card.assigned_to.display_name || card.assigned_to.username || '')}" aria-label="Assigned to ${this.escapeHtml(card.assigned_to.display_name || card.assigned_to.username || '')}">${this.escapeHtml(this.getInitials(card.assigned_to.display_name || card.assigned_to.username || ''))}</div>` : ''}
                    </div>
                  `).join('') : ''
                }
                ${!this.showArchived && canCreateCardsInCurrentView ? `<button class="btn btn-secondary add-card-btn" data-column-id="${column.id}">+ Add Card</button>` : ''}
              </div>
            </div>
          `).join('')}
          ${this.canEdit ? `<div class="add-column-placeholder">
            <button class="btn btn-primary" id="add-column-inline-btn">+ Add Column</button>
          </div>` : ''}
        </div>
      `;
      
      // Add event listener for add column button next to columns
      if (this.canEdit) {
        const addColumnBtn = document.getElementById('add-column-inline-btn');
        if (addColumnBtn) {
          addColumnBtn.addEventListener('click', () => this.openAddColumnModal());
        }
      }
      
      // Add hover listeners for columns to track which column is hovered
      document.querySelectorAll('.column').forEach(column => {
        column.addEventListener('mouseenter', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          if (!isNaN(columnId)) {
            this.hoveredColumnId = columnId;
          }
        });
        column.addEventListener('mouseleave', () => {
          this.hoveredColumnId = null;
        });
      });
      
      // Add event listeners for column menu buttons
      document.querySelectorAll('.column-menu-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const columnId = e.currentTarget.getAttribute('data-column-id');
          const dropdown = document.querySelector(`.column-menu-dropdown[data-column-id="${columnId}"]`);
          
          // Close all other dropdowns
          document.querySelectorAll('.column-menu-dropdown').forEach(d => {
            if (d !== dropdown) d.classList.remove('show');
          });
          
          // Toggle this dropdown
          dropdown.classList.toggle('show');
        });
      });
      
      // Add event listeners for edit column buttons
      document.querySelectorAll('.column-edit-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.target.getAttribute('data-column-id'));
          const columnName = e.target.getAttribute('data-column-name');
          this.openEditColumnModal(columnId, columnName);
        });
      });

      document.querySelectorAll('.column-menu-rename-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          const columnName = e.currentTarget.getAttribute('data-column-name');
          document.querySelectorAll('.column-menu-dropdown').forEach(d => d.classList.remove('show'));
          this.openEditColumnModal(columnId, columnName);
        });
      });

      this.setupAssigneeFilterBarListeners();
      
      // Add event listeners for add card buttons (header and empty state)
      document.querySelectorAll('.column-add-card-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.target.getAttribute('data-column-id'));
          const scheduled = this.currentView === 'scheduled';
          this.openAddCardModal(columnId, 0, scheduled); // Add at top (order 0)
        });
      });

      document.querySelectorAll('.column-menu-add-card-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          const scheduled = this.currentView === 'scheduled';
          document.querySelectorAll('.column-menu-dropdown').forEach(d => d.classList.remove('show'));
          this.openAddCardModal(columnId, 0, scheduled); // Add at top (order 0)
        });
      });
      
      document.querySelectorAll('.add-card-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.target.getAttribute('data-column-id'));
          const scheduled = this.currentView === 'scheduled';
          this.openAddCardModal(columnId, null, scheduled); // Add at bottom (default)
        });
      });
      
      // Add event listeners for delete column buttons
      document.querySelectorAll('.column-delete-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          // Close the dropdown
          document.querySelectorAll('.column-menu-dropdown').forEach(d => d.classList.remove('show'));
          this.deleteColumn(columnId);
        });
      });
      
      // Add event listeners for delete all cards buttons
      document.querySelectorAll('.column-delete-cards-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          // Close the dropdown
          document.querySelectorAll('.column-menu-dropdown').forEach(d => d.classList.remove('show'));
          this.deleteAllCardsInColumn(columnId);
        });
      });
      
      // Add event listeners for move all cards buttons
      document.querySelectorAll('.column-move-all-cards-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          // Close the dropdown
          document.querySelectorAll('.column-menu-dropdown').forEach(d => d.classList.remove('show'));
          this.openMoveAllCardsModal(columnId);
        });
      });
      
      // Add event listeners for archive all cards buttons
      document.querySelectorAll('.column-archive-all-cards-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          // Close the dropdown
          document.querySelectorAll('.column-menu-dropdown').forEach(d => d.classList.remove('show'));
          this.archiveAllCardsInColumn(columnId);
        });
      });
      
      // Add event listeners for unarchive all cards buttons
      document.querySelectorAll('.column-unarchive-all-cards-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          // Close the dropdown
          document.querySelectorAll('.column-menu-dropdown').forEach(d => d.classList.remove('show'));
          this.unarchiveAllCardsInColumn(columnId);
        });
      });
      
      // Add event listeners for archive after... buttons
      document.querySelectorAll('.column-archive-after-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          // Close the dropdown
          document.querySelectorAll('.column-menu-dropdown').forEach(d => d.classList.remove('show'));
          this.openArchiveAfterModal(columnId);
        });
      });
      
      // Add event listeners for move column buttons
      document.querySelectorAll('.column-move-left-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.target.getAttribute('data-column-id'));
          const currentOrder = parseInt(e.target.getAttribute('data-order'));
          if (currentOrder > 0) {
            this.moveColumn(columnId, currentOrder - 1);
          }
        });
      });

      document.querySelectorAll('.column-menu-move-left-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          const currentOrder = parseInt(e.currentTarget.getAttribute('data-order'));
          document.querySelectorAll('.column-menu-dropdown').forEach(d => d.classList.remove('show'));
          if (currentOrder > 0) {
            this.moveColumn(columnId, currentOrder - 1);
          }
        });
      });
      
      document.querySelectorAll('.column-move-right-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.target.getAttribute('data-column-id'));
          const currentOrder = parseInt(e.target.getAttribute('data-order'));
          const maxOrder = this.columns.length - 1;
          if (currentOrder < maxOrder) {
            this.moveColumn(columnId, currentOrder + 1);
          }
        });
      });

      document.querySelectorAll('.column-menu-move-right-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const columnId = parseInt(e.currentTarget.getAttribute('data-column-id'));
          const currentOrder = parseInt(e.currentTarget.getAttribute('data-order'));
          const maxOrder = this.columns.length - 1;
          document.querySelectorAll('.column-menu-dropdown').forEach(d => d.classList.remove('show'));
          if (currentOrder < maxOrder) {
            this.moveColumn(columnId, currentOrder + 1);
          }
        });
      });
      
      // Add event listeners for card clicks (open edit modal)
      document.querySelectorAll('.card').forEach(card => {
        card.addEventListener('click', async (e) => {
          if (this.isMobileTouchViewport() && Date.now() < this.mobileTouchDragSuppressClickUntil) {
            e.preventDefault();
            e.stopPropagation();
            return;
          }

          // Don't trigger if clicking the delete button, checklist checkbox, or expand button
          // Use closest() to handle clicks on button content (like emoji text nodes)
          if (e.target.closest('.card-delete-btn')) return;
          if (e.target.closest('.card-move-btn')) return;
          if (e.target.closest('.card-checklist-checkbox')) return;
          if (e.target.closest('.card-expand-btn')) return;
          if (e.target.closest('.card-archive-btn')) return;
          if (e.target.closest('.card-unarchive-btn')) return;
          
          const cardId = parseInt(card.getAttribute('data-card-id'));
          
          // Show loading state on the card
          card.classList.add('updating');
          
          // Reload card data to get latest state
          const cardData = await this.getCardData(cardId);
          
          // Remove loading state
          card.classList.remove('updating');
          
          if (cardData) {
            this.openEditCardModal(cardId, cardData);
          }
          // Error toast already shown by getCardData if it failed
        });
      });

      // Initialize card collapse/expand functionality
      // Use requestAnimationFrame to ensure DOM is fully rendered before measuring
      requestAnimationFrame(() => {
        // Get the collapse threshold from CSS custom property
        const collapseHeightStr = getComputedStyle(document.documentElement)
          .getPropertyValue('--card-collapse-height')
          .trim();
        const collapseHeight = parseInt(collapseHeightStr);
        
        if (!collapseHeight || isNaN(collapseHeight)) {
          console.error('Card collapse height not defined in CSS. Skipping card collapse logic.');
          return;
        }
        
        document.querySelectorAll('.card').forEach(card => {
          const contentWrapper = card.querySelector('.card-content-wrapper');
          const expandBtn = card.querySelector('.card-expand-btn');
          
          if (contentWrapper && expandBtn) {
            // Measure the actual content height
            const contentHeight = contentWrapper.scrollHeight;
            
            // If content is taller than the threshold, make it collapsible
            if (contentHeight > collapseHeight) {
              card.classList.add('has-overflow');
              card.classList.add('collapsed');
            }
          }
        });

        this.restoreExpandedCardState();
      });

      // Add event listeners for card expand buttons
      document.querySelectorAll('.card-expand-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation(); // Prevent card click event
          const card = e.currentTarget.closest('.card');
          const cardId = Number(card?.getAttribute('data-card-id'));
          
          if (card.classList.contains('collapsed')) {
            card.classList.remove('collapsed');
            e.currentTarget.textContent = 'Show less...';
            e.currentTarget.setAttribute('aria-expanded', 'true');
            if (Number.isInteger(cardId) && cardId > 0) {
              this.expandedCardIds.add(cardId);
            }
          } else {
            card.classList.add('collapsed');
            e.currentTarget.textContent = 'Show more...';
            e.currentTarget.setAttribute('aria-expanded', 'false');
            if (Number.isInteger(cardId) && cardId > 0) {
              this.expandedCardIds.delete(cardId);
            }
          }

          this.persistExpandedCardState();
        });
      });
      
      // Add event listeners for checklist checkboxes on cards
      document.querySelectorAll('.card-checklist-checkbox').forEach(checkbox => {
        checkbox.addEventListener('click', async (e) => {
          e.stopPropagation(); // Prevent card click event
          const itemId = parseInt(e.target.getAttribute('data-item-id'));
          const checked = e.target.checked;
          await this.updateChecklistItem(itemId, { checked });
          
          // Update the visual state of the text
          const label = e.target.nextElementSibling;
          if (checked) {
            label.classList.add('checked');
          } else {
            label.classList.remove('checked');
          }
          
          // Update the summary
          const card = e.target.closest('.card');
          const summaryElement = card.querySelector('.card-checklist-summary');
          if (summaryElement) {
            const allCheckboxes = card.querySelectorAll('.card-checklist-checkbox');
            const total = allCheckboxes.length;
            const checkedCount = Array.from(allCheckboxes).filter(cb => cb.checked).length;
            const items = Array.from(allCheckboxes).map(cb => ({ checked: cb.checked }));
            const percentage = calculateChecklistPercentage(items);
            summaryElement.textContent = `${checkedCount}/${total} (${percentage}%)`;
          }
        });
      });
      
      // Add event listeners for delete card buttons
      document.querySelectorAll('.card-delete-btn').forEach(btn => {
        btn.addEventListener('mousedown', (e) => {
          e.stopPropagation(); // Prevent drag from starting
        });
        btn.addEventListener('click', async (e) => {
          e.stopPropagation(); // Prevent card click event
          const cardId = parseInt(e.currentTarget.getAttribute('data-card-id'));
          const cardElement = e.currentTarget.closest('.card');
          await this.deleteCard(cardId, cardElement);
        });
      });
      
      // Add event listeners for archive card buttons
      document.querySelectorAll('.card-archive-btn').forEach(btn => {
        btn.addEventListener('mousedown', (e) => {
          e.stopPropagation(); // Prevent drag from starting
        });
        btn.addEventListener('click', async (e) => {
          e.stopPropagation(); // Prevent card click event
          const cardId = parseInt(e.currentTarget.getAttribute('data-card-id'));
          const cardElement = e.currentTarget.closest('.card');
          await this.archiveCard(cardId, cardElement);
        });
      });
      
      // Add event listeners for unarchive card buttons
      document.querySelectorAll('.card-unarchive-btn').forEach(btn => {
        btn.addEventListener('mousedown', (e) => {
          e.stopPropagation(); // Prevent drag from starting
        });
        btn.addEventListener('click', async (e) => {
          e.stopPropagation(); // Prevent card click event
          const cardId = parseInt(e.currentTarget.getAttribute('data-card-id'));
          const cardElement = e.currentTarget.closest('.card');
          await this.unarchiveCard(cardId, cardElement);
        });
      });
      
      // Add event listeners for card done buttons
      document.querySelectorAll('.card-done-btn').forEach(btn => {
        btn.addEventListener('mousedown', (e) => {
          e.stopPropagation(); // Prevent drag from starting
        });
        btn.addEventListener('click', async (e) => {
          e.stopPropagation(); // Prevent card click event
          const cardId = parseInt(e.currentTarget.getAttribute('data-card-id'));
          const cardElement = e.currentTarget.closest('.card');
          const currentDone = cardElement.getAttribute('data-done') === 'true';
          await this.updateCardDoneStatus(cardId, !currentDone, cardElement);
        });
      });

      // Add event listeners for card move buttons
      document.querySelectorAll('.card-move-btn').forEach(btn => {
        btn.addEventListener('mousedown', (e) => {
          e.stopPropagation(); // Prevent drag from starting
        });
        btn.addEventListener('click', async (e) => {
          e.stopPropagation(); // Prevent card click event
          const cardId = parseInt(e.currentTarget.getAttribute('data-card-id'));
          await this.openMoveCardModal(cardId);
        });
      });
      
      // Add drag and drop event listeners for cards (only in edit mode)
      if (this.canEdit) {
        this.setupDragAndDrop();
      }

      // Track and restore per-column scroll state after each board render.
      document.querySelectorAll('.column-cards[data-column-id]').forEach(columnCards => {
        columnCards.addEventListener('scroll', () => {
          const columnId = columnCards.getAttribute('data-column-id');
          this.updateColumnScrollPosition(columnId, columnCards.scrollTop);
          this.schedulePersistColumnScrollPositions();
        }, { passive: true });
      });

      const columnsContainer = this.container.querySelector('.columns-container');
      if (columnsContainer) {
        columnsContainer.addEventListener('scroll', () => {
          this.boardHorizontalScrollLeft = this.sanitizeBoardHorizontalScroll(columnsContainer.scrollLeft);
          this.schedulePersistBoardHorizontalScrollPosition();
        }, { passive: true });
      }

      this.restoreColumnScrollPositions();
      this.restoreBoardHorizontalScrollPosition();

      this.queueMobileViewportMetricsUpdate();
      
      // Apply permission-based rendering (if PermissionManager is initialized)
      this.applyPermissionBasedRendering();
    }
  }

  /**
   * Apply permission-based rendering to UI elements
   * This method checks user permissions and removes/hides elements the user cannot access
   * Provides a centralized, extensible approach to permission-based UI
   */
  applyPermissionBasedRendering() {
    if (!window.PermissionManager || !PermissionManager.initialized) {
      console.log('PermissionManager not available - skipping permission-based rendering');
      return;
    }
    
    console.log('Applying permission-based rendering...');

    const canCreateColumn = this.canCallPermissionEndpoint('POST', '/api/boards/:id/columns');
    const canCreateCard = this.canCallPermissionEndpoint('POST', '/api/columns/:id/cards');
    const canCreateSchedule = this.canCallPermissionEndpoint('POST', '/api/schedules');
    const canUpdateColumn = this.canCallPermissionEndpoint('PATCH', '/api/columns/:id');
    const canMoveAllCards = this.canCallPermissionEndpoint('POST', '/api/columns/:source_id/cards/move');
    const canBatchArchive = this.canCallPermissionEndpoint('POST', '/api/cards/batch/archive');
    const canBatchUnarchive = this.canCallPermissionEndpoint('POST', '/api/cards/batch/unarchive');
    const canArchiveAfter = this.canCallPermissionEndpoint('POST', '/api/columns/:id/archive-after');
    const canDeleteCardsInColumn = this.canCallPermissionEndpoint('DELETE', '/api/columns/:id/cards');
    const canDeleteColumn = this.canCallPermissionEndpoint('DELETE', '/api/columns/:id');
    const canDeleteCard = this.canCallPermissionEndpoint('DELETE', '/api/cards/:id');
    const canArchiveCard = this.canCallPermissionEndpoint('PATCH', '/api/cards/:id/archive');
    const canUnarchiveCard = this.canCallPermissionEndpoint('PATCH', '/api/cards/:id/unarchive');
    const canMoveCard = this.canEdit || this.canCallPermissionEndpoint('PATCH', '/api/cards/:id');
    
    // Remove "Add Column" buttons if user can't call create-column endpoint.
    if (!canCreateColumn) {
      document.querySelectorAll('#add-column-empty-btn, #add-column-inline-btn').forEach(btn => btn.remove());
    }
    
    // In scheduled view, creating a template through UI requires both card.create and schedule.create.
    const canUseAddCardUi = this.currentView === 'scheduled'
      ? (canCreateCard && canCreateSchedule)
      : canCreateCard;
    if (!canUseAddCardUi) {
      document.querySelectorAll('.column-add-card-btn, .column-menu-add-card-btn, .add-card-btn').forEach(btn => btn.remove());
    }
    
    // Remove column edit buttons if user cannot update columns.
    if (!canUpdateColumn) {
      document.querySelectorAll('.column-edit-btn, .column-menu-rename-btn').forEach(btn => btn.remove());
    }
    
    // Remove column move buttons if user cannot update columns.
    if (!canUpdateColumn) {
      document.querySelectorAll('.column-move-left-btn, .column-move-right-btn, .column-menu-move-left-btn, .column-menu-move-right-btn').forEach(btn => btn.remove());
    }
    
    // Remove column menu and its items based on permissions
    document.querySelectorAll('.column-menu-wrapper').forEach(menuWrapper => {
      const dropdown = menuWrapper.querySelector('.column-menu-dropdown');
      
      if (!dropdown) return;
      
      // Check each menu item and remove if no permission
      const moveAllBtn = dropdown.querySelector('.column-move-all-cards-btn');
      const archiveAllBtn = dropdown.querySelector('.column-archive-all-cards-btn');
      const unarchiveAllBtn = dropdown.querySelector('.column-unarchive-all-cards-btn');
      const archiveAfterBtn = dropdown.querySelector('.column-archive-after-btn');
      const deleteAllCardsBtn = dropdown.querySelector('.column-delete-cards-btn');
      const deleteColumnBtn = dropdown.querySelector('.column-delete-btn');
      
      if (moveAllBtn && !canMoveAllCards) {
        moveAllBtn.remove();
      }
      if (archiveAllBtn && !canBatchArchive) {
        archiveAllBtn.remove();
      }
      if (unarchiveAllBtn && !canBatchUnarchive) {
        unarchiveAllBtn.remove();
      }
      if (archiveAfterBtn && !canArchiveAfter) {
        archiveAfterBtn.remove();
      }
      if (deleteAllCardsBtn && !canDeleteCardsInColumn) {
        deleteAllCardsBtn.remove();
      }
      if (deleteColumnBtn && !canDeleteColumn) {
        deleteColumnBtn.remove();
      }
      
      // If all menu items are removed, remove the menu button too
      const remainingItems = dropdown.querySelectorAll('.column-menu-item');
      if (remainingItems.length === 0) {
        menuWrapper.remove();
      }
    });
    
    // Remove card delete buttons if user cannot call delete-card endpoint.
    if (!canDeleteCard) {
      document.querySelectorAll('.card-delete-btn').forEach(btn => btn.remove());
    }
    
    // Remove archive/unarchive buttons based on exact archive endpoints.
    if (!canArchiveCard) {
      document.querySelectorAll('.card-archive-btn').forEach(btn => btn.remove());
    }
    if (!canUnarchiveCard) {
      document.querySelectorAll('.card-unarchive-btn').forEach(btn => btn.remove());
    }

    // Remove card move buttons if user cannot call card update endpoint.
    if (!canMoveCard) {
      document.querySelectorAll('.card-move-btn').forEach(btn => btn.remove());
    }
    
    console.log('Permission-based rendering complete');
  }

  async moveColumn(columnId, newOrder) {
    await this.updateColumnPosition(columnId, newOrder);
  }

  async updateColumnPosition(columnId, order) {
    try {
      const response = await fetch(`/api/columns/${columnId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ order: order })
      });
      
      const data = await this.parseResponse(response);
      
      if (!data.success) {
        console.error('Failed to update column position:', data.message);
        // Reload board to restore correct state
        await this.loadBoard();
      } else {
        // Reload board to get updated order for all columns
        await this.loadBoard();
      }
    } catch (err) {
      console.error('Error updating column position:', err);
      // Reload board to restore correct state
      await this.loadBoard();
    }
  }

  stopColumnAutoScroll() {
    if (this.autoScrollHoverTimeoutId) {
      clearTimeout(this.autoScrollHoverTimeoutId);
      this.autoScrollHoverTimeoutId = null;
    }

    if (this.autoScrollRafId) {
      cancelAnimationFrame(this.autoScrollRafId);
      this.autoScrollRafId = null;
    }

    this.autoScrollContainer = null;
    this.autoScrollDirection = 0;
    this.autoScrollPendingContainer = null;
    this.autoScrollPendingDirection = 0;
  }

  runColumnAutoScroll() {
    if (!this.autoScrollContainer || this.autoScrollDirection === 0) {
      this.stopColumnAutoScroll();
      return;
    }

    const container = this.autoScrollContainer;
    if (!container.isConnected) {
      this.stopColumnAutoScroll();
      return;
    }

    const rect = container.getBoundingClientRect();
    const edgeThreshold = COLUMN_AUTO_SCROLL_EDGE_THRESHOLD_PX;

    const distanceToActiveEdge = this.autoScrollDirection < 0
      ? Math.max(0, this.autoScrollPointerY - rect.top)
      : Math.max(0, rect.bottom - this.autoScrollPointerY);

    const edgeProximity = Math.max(0, Math.min(1, (edgeThreshold - distanceToActiveEdge) / edgeThreshold));
    const scrollStep = Math.max(
      COLUMN_AUTO_SCROLL_MIN_STEP_PX,
      Math.round(COLUMN_AUTO_SCROLL_BASE_STEP_PX + edgeProximity * COLUMN_AUTO_SCROLL_MAX_EXTRA_STEP_PX)
    );

    const previousScrollTop = container.scrollTop;
    container.scrollTop += this.autoScrollDirection * scrollStep;

    if (container.scrollTop === previousScrollTop) {
      this.stopColumnAutoScroll();
      return;
    }

    this.autoScrollRafId = requestAnimationFrame(() => this.runColumnAutoScroll());
  }

  scheduleColumnAutoScroll(container, direction, pointerY) {
    this.autoScrollPointerY = pointerY;

    if (
      this.autoScrollContainer === container &&
      this.autoScrollDirection === direction &&
      this.autoScrollRafId
    ) {
      return;
    }

    if (
      this.autoScrollPendingContainer === container &&
      this.autoScrollPendingDirection === direction &&
      this.autoScrollHoverTimeoutId
    ) {
      return;
    }

    this.stopColumnAutoScroll();
    this.autoScrollPendingContainer = container;
    this.autoScrollPendingDirection = direction;

    this.autoScrollHoverTimeoutId = setTimeout(() => {
      this.autoScrollHoverTimeoutId = null;
      this.autoScrollContainer = this.autoScrollPendingContainer;
      this.autoScrollDirection = this.autoScrollPendingDirection;
      this.autoScrollPendingContainer = null;
      this.autoScrollPendingDirection = 0;
      this.runColumnAutoScroll();
    }, COLUMN_AUTO_SCROLL_HOVER_DELAY_MS);
  }

  updateColumnAutoScrollDuringDrag(container, clientY) {
    const rect = container.getBoundingClientRect();
    const edgeThreshold = COLUMN_AUTO_SCROLL_EDGE_THRESHOLD_PX;
    const distanceToTop = clientY - rect.top;
    const distanceToBottom = rect.bottom - clientY;

    let direction = 0;

    if (distanceToTop <= edgeThreshold && container.scrollTop > 0) {
      direction = -1;
    } else if (
      distanceToBottom <= edgeThreshold &&
      container.scrollTop + container.clientHeight < container.scrollHeight - 1
    ) {
      direction = 1;
    }

    if (direction === 0) {
      this.stopColumnAutoScroll();
      return;
    }

    this.scheduleColumnAutoScroll(container, direction, clientY);
  }

  setupDragAndDrop() {
    const cards = document.querySelectorAll('.card');
    const columnCards = document.querySelectorAll('.column-cards');
    
    let draggedCard = null;
    let originalPosition = null; // Store original position before drag
    
    // Card drag events
    cards.forEach(card => {
      card.addEventListener('dragstart', (e) => {
        if (this.isMobileTouchViewport()) {
          const cardId = Number(card.getAttribute('data-card-id'));
          this.logMobileCardLongPressDebug('native-dragstart-blocked-mobile', {
            cardId,
            targetClass: e.target?.className || null
          });
          e.preventDefault();
          return false;
        }

        const cardId = Number(card.getAttribute('data-card-id'));

        // Don't allow drag if clicking on buttons or interactive elements
        if (e.target.closest('.card-delete-btn') || 
            e.target.closest('.card-archive-btn') || 
            e.target.closest('.card-unarchive-btn') ||
            e.target.closest('.card-expand-btn') ||
            e.target.closest('.card-checklist-checkbox') ||
            e.target.closest('.card-action-buttons')) {
          e.preventDefault();
          return false;
        }
        
        e.stopPropagation(); // Prevent column from also starting to drag
        draggedCard = card;
        card.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/html', card.innerHTML);
        
        // Capture original position NOW, before any DOM manipulation
        const oldColumnId = parseInt(card.getAttribute('data-column-id'));
        const oldOrder = parseInt(card.getAttribute('data-order'));
        const originalColumnContainer = document.querySelector(`[data-column-id="${oldColumnId}"] .column-cards`);
        const actualNextSibling = card.nextElementSibling;
        const originalIndex = Array.from(originalColumnContainer?.querySelectorAll('.card') || []).indexOf(card);
        
        originalPosition = {
          columnId: oldColumnId,
          order: oldOrder,
          index: originalIndex,
          container: originalColumnContainer,
          nextSibling: actualNextSibling
        };

        this.logMobileCardLongPressDebug('dragstart-state-captured', {
          cardId,
          oldColumnId,
          oldOrder,
          originalIndex
        });
      });
      
      card.addEventListener('dragend', (e) => {
        card.classList.remove('dragging');
        card.classList.remove('mobile-drag-armed');
        const cardId = Number(card.getAttribute('data-card-id'));
        this.logMobileCardLongPressDebug('dragend', {
          cardId,
          isMobile: this.isMobileTouchViewport()
        });
        draggedCard = null;
        originalPosition = null; // Clear stored position
        this.stopColumnAutoScroll();
      });
    });
    
    // Column drop zone events
    columnCards.forEach(columnContainer => {
      columnContainer.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';

        this.updateColumnAutoScrollDuringDrag(columnContainer, e.clientY);
        
        const afterElement = this.getDragAfterElement(columnContainer, e.clientY);
        const dragging = document.querySelector('.dragging');
        
        if (!dragging) return;
        
        if (!afterElement) {
          // Append at the end (before the add card button if it exists)
          const addCardBtn = columnContainer.querySelector('.add-card-btn');
          if (addCardBtn) {
            columnContainer.insertBefore(dragging, addCardBtn);
          } else {
            columnContainer.appendChild(dragging);
          }
        } else {
          columnContainer.insertBefore(dragging, afterElement);
        }
      });
      
      columnContainer.addEventListener('drop', async (e) => {
        e.preventDefault();
        this.stopColumnAutoScroll();
        
        if (!draggedCard || !originalPosition) return;

        // Re-evaluate placement at drop time so the final order reflects where
        // the pointer is when released (important after auto-scroll movement).
        const finalAfterElement = this.getDragAfterElement(columnContainer, e.clientY);
        if (!finalAfterElement) {
          const addCardBtn = columnContainer.querySelector('.add-card-btn');
          if (addCardBtn) {
            columnContainer.insertBefore(draggedCard, addCardBtn);
          } else {
            columnContainer.appendChild(draggedCard);
          }
        } else {
          columnContainer.insertBefore(draggedCard, finalAfterElement);
        }
        
        const targetColumnId = parseInt(columnContainer.getAttribute('data-column-id'));
        const cardId = parseInt(draggedCard.getAttribute('data-card-id'));
        const oldColumnId = originalPosition.columnId;
        
        // Calculate target order using neighboring order values rather than
        // DOM index because persisted order values can contain gaps.
        const newOrder = this.getDropOrderValue(columnContainer, draggedCard, originalPosition);

        this.logMobileCardLongPressDebug('drop', {
          cardId,
          oldColumnId,
          targetColumnId,
          oldOrder: originalPosition.order,
          newOrder
        });
        
        // Only update if position or column changed
        const oldOrder = originalPosition.order;
        if (targetColumnId !== oldColumnId || newOrder !== oldOrder) {
          await this.updateCardPosition(cardId, targetColumnId, newOrder, originalPosition);
        }
      });

      columnContainer.addEventListener('dragleave', (e) => {
        if (!columnContainer.contains(e.relatedTarget)) {
          this.stopColumnAutoScroll();
        }
      });
    });
  }

  getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.card:not(.dragging)')];
    
    return draggableElements.reduce((closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      
      if (offset < 0 && offset > closest.offset) {
        return { offset: offset, element: child };
      } else {
        return closest;
      }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
  }

  getDropOrderValue(container, draggedCard, originalPosition = null) {
    const cardsInColumn = Array.from(container.querySelectorAll('.card'));
    const draggedIndex = cardsInColumn.indexOf(draggedCard);

    if (draggedIndex === -1) {
      return 0;
    }

    const targetColumnId = Number(container.getAttribute('data-column-id'));
    const oldColumnId = Number(originalPosition?.columnId);
    const oldOrder = Number(originalPosition?.order);
    const originalIndex = Number(originalPosition?.index);

    const previousCard = cardsInColumn[draggedIndex - 1] || null;
    const nextCard = cardsInColumn[draggedIndex + 1] || null;

    const previousOrder = previousCard ? Number(previousCard.getAttribute('data-order')) : Number.NaN;
    const nextOrder = nextCard ? Number(nextCard.getAttribute('data-order')) : Number.NaN;

    const isSameColumnMove = Number.isFinite(targetColumnId) && Number.isFinite(oldColumnId) && targetColumnId === oldColumnId;

    if (isSameColumnMove && Number.isInteger(originalIndex) && originalIndex >= 0) {
      if (draggedIndex > originalIndex) {
        if (Number.isFinite(previousOrder)) {
          return previousOrder;
        }
      } else if (draggedIndex < originalIndex) {
        if (Number.isFinite(nextOrder)) {
          return nextOrder;
        }
      } else if (Number.isFinite(oldOrder)) {
        return oldOrder;
      }
    }

    if (Number.isFinite(nextOrder)) {
      return nextOrder;
    }

    // Appending to end: place after the largest known order value.
    const maxOrder = cardsInColumn.reduce((max, card) => {
      if (card === draggedCard) return max;
      const order = Number(card.getAttribute('data-order'));
      if (!Number.isFinite(order)) return max;
      return Math.max(max, order);
    }, Number.NEGATIVE_INFINITY);

    if (Number.isFinite(maxOrder)) {
      return maxOrder + 1;
    }

    return draggedIndex;
  }

  async updateCardPosition(cardId, columnId, order, originalPosition = null, position = null) {
    const cardElement = document.querySelector(`[data-card-id="${cardId}"]`);

    // Add loading state with 500ms delay to avoid flashing on fast connections
    const loadingTimeout = setTimeout(() => {
      if (cardElement) {
        cardElement.classList.add('updating');
        cardElement.style.opacity = '0.6';
        cardElement.style.pointerEvents = 'none';
      }
    }, 500);

    // Set 5 second timeout for the request
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const body = { column_id: columnId };
      if (position !== null) {
        body.position = position;
      } else {
        body.order = order;
      }
      const response = await fetch(`/api/cards/${cardId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(body),
        signal: controller.signal
      });
      
      // Clear timeouts immediately after fetch completes, before processing response
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      
      const data = await this.parseResponse(response);
      
      if (!data.success) {
        console.error('Failed to update card position:', data.message);
        
        // Restore card to original position (DOM only, no API call)
        if (cardElement && originalPosition) {
          this.restoreCardPosition(cardElement, originalPosition);
        }
        
        if (cardElement) {
          cardElement.classList.remove('updating'); // Remove loading state
          cardElement.classList.add('update-failed');
          cardElement.style.opacity = '';
          cardElement.style.pointerEvents = '';
          setTimeout(() => cardElement.classList.remove('update-failed'), 3000);
        }
        
        // Show non-blocking error toast instead of blocking alert
        this.showErrorToast('Failed to move card');
        
        // Don't reload board - restoration is DOM-only
      } else {
        // Update local data attributes
        if (cardElement) {
          cardElement.setAttribute('data-column-id', columnId);
          cardElement.setAttribute('data-order', order);
          cardElement.classList.remove('updating');
          cardElement.classList.add('update-success');
          cardElement.style.opacity = '';
          cardElement.style.pointerEvents = '';
          setTimeout(() => cardElement.classList.remove('update-success'), 1000);
        }
        // Reload board to update card counts
        await this.loadBoard();
      }
    } catch (err) {
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      
      // Restore card to original position
      if (cardElement && originalPosition) {
        this.restoreCardPosition(cardElement, originalPosition);
      }
      
      if (cardElement) {
        cardElement.classList.remove('updating');
        cardElement.classList.add('update-failed');
        cardElement.style.opacity = '';
        cardElement.style.pointerEvents = '';
        setTimeout(() => cardElement.classList.remove('update-failed'), 3000);
      }
      
      if (err.name === 'AbortError') {
        console.error('Card update timeout after 5 seconds');
        this.showErrorToast('Card update timed out. Check your connection.');
      } else {
        console.error('Error updating card position:', err);
        this.showErrorToast('Failed to move card');
      }
      
      // Don't reload board - restoration is DOM-only
    }
  }

  restoreCardPosition(cardElement, originalPosition) {
    try {
      // Restore data attributes
      cardElement.setAttribute('data-column-id', originalPosition.columnId);
      cardElement.setAttribute('data-order', originalPosition.order);
      
      // Validate container is still attached to the document
      if (originalPosition.container && document.contains(originalPosition.container)) {
        if (originalPosition.nextSibling && originalPosition.container.contains(originalPosition.nextSibling)) {
          // Insert before the next sibling (exact original position)
          originalPosition.container.insertBefore(cardElement, originalPosition.nextSibling);
          return true;
        } else {
          const cardsInContainer = Array.from(originalPosition.container.querySelectorAll('.card'));
          if (Number.isInteger(originalPosition.index) && originalPosition.index >= 0 && originalPosition.index < cardsInContainer.length) {
            originalPosition.container.insertBefore(cardElement, cardsInContainer[originalPosition.index]);
            return true;
          }

          // If next sibling is gone, append at end
          const addCardBtn = originalPosition.container.querySelector('.add-card-btn');
          if (addCardBtn) {
            originalPosition.container.insertBefore(cardElement, addCardBtn);
          } else {
            originalPosition.container.appendChild(cardElement);
          }
          return true;
        }
        
      } else {
        console.warn('Cannot restore card: original container is no longer in the document');
        // Container was removed (column deleted or board reloaded)
        // The calling function will reload the board to get fresh state
        return false;
      }
    } catch (err) {
      console.error('Failed to restore card position:', err);
      // Will fall back to board reload in calling function
      return false;
    }
  }

  /**
   * Add a time interval to a date without mutating the original.
   * Handles month/year additions correctly to avoid mutation issues.
   * 
   * @param {Date} date - The base date
   * @param {number} amount - How many units to add
   * @param {string} unit - The unit (minute, hour, day, week, month, year)
   * @returns {Date} A new Date object with the interval added
   */
  addInterval(date, amount, unit) {
    switch (unit) {
      case 'minute':
        return new Date(date.getTime() + amount * 60 * 1000);
      case 'hour':
        return new Date(date.getTime() + amount * 60 * 60 * 1000);
      case 'day':
        return new Date(date.getTime() + amount * 24 * 60 * 60 * 1000);
      case 'week':
        return new Date(date.getTime() + amount * 7 * 24 * 60 * 60 * 1000);
      case 'month': {
        // Create new date to avoid mutation
        const newDate = new Date(date);
        newDate.setMonth(newDate.getMonth() + amount);
        return newDate;
      }
      case 'year': {
        // Create new date to avoid mutation
        const newDate = new Date(date);
        newDate.setFullYear(newDate.getFullYear() + amount);
        return newDate;
      }
      default:
        return new Date(date);
    }
  }

  async openScheduleModal(cardId, cardData, hasSchedule) {
    // Check database connection before opening modal
    if (window.header && !window.header.dbConnected) {
      this.showErrorToast('Cannot open schedule editor: Database is not connected. Please wait for the connection to be restored.');
      return;
    }

    const canViewSchedule = this.canCallPermissionEndpoint('GET', '/api/schedules/:id');
    const canCreateSchedule = this.canCallPermissionEndpoint('POST', '/api/schedules');
    const canEditSchedule = this.canCallPermissionEndpoint('PUT', '/api/schedules/:id');
    const canDeleteSchedule = this.canCallPermissionEndpoint('DELETE', '/api/schedules/:id');

    if (hasSchedule) {
      if (!canViewSchedule) {
        this.showErrorToast('You do not have permission to view this schedule.');
        return;
      }
      if (!canEditSchedule && !canDeleteSchedule) {
        this.showErrorToast('You do not have permission to modify this schedule.');
        return;
      }
    } else if (!canCreateSchedule) {
      this.showErrorToast('You do not have permission to create schedules.');
      return;
    }

    const allowScheduleSubmit = hasSchedule ? canEditSchedule : canCreateSchedule;
    const scheduleFieldsDisabled = hasSchedule && !canEditSchedule;
    const scheduleDisabledAttr = scheduleFieldsDisabled ? 'disabled' : '';
    
    // If card has a schedule, fetch the schedule details
    let scheduleData = null;
    if (hasSchedule && cardData.schedule) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);
      
      try {
        const response = await fetch(`/api/schedules/${cardData.schedule}`, {
          signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        const data = await this.parseResponse(response);
        
        if (data.success) {
          scheduleData = data.schedule;
        } else {
          this.showErrorToast(`Failed to load schedule: ${data.message}`);
          return;
        }
      } catch (err) {
        clearTimeout(timeoutId);
        console.error('Error fetching schedule:', err);
        
        if (err.name === 'AbortError') {
          this.showErrorToast('Load schedule timed out (5s). Please check your connection.');
        } else {
          this.showErrorToast(`Error loading schedule: ${err.message}`);
        }
        return;
      }
    }

    // Datetime-local controls expect local wall time strings (no timezone suffix).
    const toDatetimeLocalValue = (value) => {
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return '';

      const pad = (num) => String(num).padStart(2, '0');
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
    };

    // Set default values
    const defaultStartDatetime = scheduleData?.start_datetime
      ? toDatetimeLocalValue(scheduleData.start_datetime)
      : toDatetimeLocalValue(new Date());
    const defaultEndDatetime = scheduleData?.end_datetime
      ? toDatetimeLocalValue(scheduleData.end_datetime)
      : '';
    const defaultRunEvery = scheduleData?.run_every || 1;
    const defaultUnit = scheduleData?.unit || 'day';
    const defaultEnabled = scheduleData?.schedule_enabled !== false;
    const defaultAllowDuplicates = scheduleData?.allow_duplicates || false;

    // Create modal HTML
    const modalHtml = `
      <div class="modal" id="schedule-modal">
        <div class="modal-content schedule-modal-content">
          <div class="modal-header">
            <div class="modal-header-actions">
              ${hasSchedule && canEditSchedule ? `<button type="button" class="btn btn-secondary" id="edit-template-btn" data-card-id="${scheduleData?.card_id || ''}">Edit Template</button>` : ''}
              ${hasSchedule && canDeleteSchedule ? `<button type="button" class="btn btn-danger" id="delete-schedule-btn">Delete Schedule</button>` : ''}
              <button type="button" class="btn btn-secondary" id="cancel-schedule-btn">Cancel</button>
              ${allowScheduleSubmit ? `<button type="submit" form="schedule-form" class="btn btn-primary">${hasSchedule ? 'Update Schedule' : 'Create Schedule'}</button>` : ''}
            </div>
            <h2>${hasSchedule ? 'Edit Schedule' : 'Create Schedule'}</h2>
          </div>
          <form id="schedule-form">
            <div class="form-row">
              <div class="form-group">
                <label for="schedule-run-every">Run Every:</label>
                <input type="number" id="schedule-run-every" name="run-every" min="1" value="${defaultRunEvery}" required ${scheduleDisabledAttr}>
              </div>
              <div class="form-group">
                <label for="schedule-unit">Unit:</label>
                <select id="schedule-unit" name="unit" required ${scheduleDisabledAttr}>
                  <option value="minute" ${defaultUnit === 'minute' ? 'selected' : ''}>Minute(s)</option>
                  <option value="hour" ${defaultUnit === 'hour' ? 'selected' : ''}>Hour(s)</option>
                  <option value="day" ${defaultUnit === 'day' ? 'selected' : ''}>Day(s)</option>
                  <option value="week" ${defaultUnit === 'week' ? 'selected' : ''}>Week(s)</option>
                  <option value="month" ${defaultUnit === 'month' ? 'selected' : ''}>Month(s)</option>
                  <option value="year" ${defaultUnit === 'year' ? 'selected' : ''}>Year(s)</option>
                </select>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group full-width">
                <label for="schedule-start-datetime">Start Date & Time:</label>
                <input type="datetime-local" id="schedule-start-datetime" name="start-datetime" value="${defaultStartDatetime}" required ${scheduleDisabledAttr}>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group full-width">
                <label for="schedule-end-datetime">End Date & Time (Optional):</label>
                <input type="datetime-local" id="schedule-end-datetime" name="end-datetime" value="${defaultEndDatetime}" ${scheduleDisabledAttr}>
              </div>
            </div>

            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" id="schedule-enabled" name="enabled" ${defaultEnabled ? 'checked' : ''} ${scheduleDisabledAttr}>
                <span>Schedule Enabled</span>
              </label>
            </div>

            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" id="schedule-allow-duplicates" name="allow-duplicates" ${defaultAllowDuplicates ? 'checked' : ''} ${scheduleDisabledAttr}>
                <span>Allow Duplicates (create new cards even if unarchived cards from this schedule exist)</span>
              </label>
            </div>

            ${!hasSchedule ? `
            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" id="schedule-keep-source" name="keep-source" checked>
                <span>Keep Original Card (if unchecked, the original card will be deleted after creating the schedule template)</span>
              </label>
            </div>
            ` : ''}

            <div class="next-runs-section" id="next-runs-section">
              <h3>Next 4 Scheduled Runs</h3>
              <div class="next-runs-list" id="next-runs-list">
                <p class="next-runs-loading">Calculating...</p>
              </div>
            </div>
          </form>
        </div>
      </div>
    `;

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Get modal elements
    const modal = document.getElementById('schedule-modal');
    const form = document.getElementById('schedule-form');
    const cancelBtn = document.getElementById('cancel-schedule-btn');
    const deleteBtn = document.getElementById('delete-schedule-btn');
    const runEveryInput = document.getElementById('schedule-run-every');
    const unitSelect = document.getElementById('schedule-unit');
    const startDatetimeInput = document.getElementById('schedule-start-datetime');
    const endDatetimeInput = document.getElementById('schedule-end-datetime');
    const nextRunsList = document.getElementById('next-runs-list');

    // Function to calculate and display next runs
    const updateNextRuns = async () => {
      const runEvery = parseInt(runEveryInput.value);
      const unit = unitSelect.value;
      const startDatetime = startDatetimeInput.value;
      const endDatetime = endDatetimeInput.value || null;

      if (!runEvery || !unit || !startDatetime) {
        nextRunsList.innerHTML = '<p class="next-runs-empty">Please fill in required fields</p>';
        return;
      }

      try {
        // Calculate next runs client-side
        const startDateTime = new Date(startDatetime);
        const endDateTime = endDatetime ? new Date(endDatetime) : null;
        const now = new Date();

        let runs = [];
        let current = startDateTime;
        let attempts = 0;
        const maxAttempts = 100;

        while (runs.length < 4 && attempts < maxAttempts) {
          attempts++;
          
          if (current >= now && (!endDateTime || current <= endDateTime)) {
            runs.push(new Date(current));
          }

          // Add interval using utility function
          current = this.addInterval(current, runEvery, unit);

          if (endDateTime && current > endDateTime) break;
        }

        if (runs.length === 0) {
          nextRunsList.innerHTML = '<p class="next-runs-empty">No upcoming runs (schedule may have ended)</p>';
        } else {
          nextRunsList.innerHTML = runs.map(run => {
            const dateStr = run.toLocaleDateString('en-US', { 
              weekday: 'short', 
              year: 'numeric', 
              month: 'short', 
              day: 'numeric' 
            });
            const timeStr = formatTimeSync(run);
            return `<div class="next-run-item">📅 ${dateStr} at ${timeStr}</div>`;
          }).join('');
        }
      } catch (err) {
        console.error('Error calculating next runs:', err);
        nextRunsList.innerHTML = '<p class="next-runs-error">Error calculating runs</p>';
      }
    };

    // Initial calculation
    updateNextRuns();

    // Track changes
    let hasUnsavedChanges = false;
    
    // Update on input changes
    [runEveryInput, unitSelect, startDatetimeInput, endDatetimeInput].forEach(input => {
      input.addEventListener('change', () => {
        hasUnsavedChanges = true;
        updateNextRuns();
      });
      input.addEventListener('input', () => {
        hasUnsavedChanges = true;
        // Debounce for text inputs
        clearTimeout(input.updateTimeout);
        input.updateTimeout = setTimeout(updateNextRuns, 500);
      });
    });
    
    // Track checkbox changes
    const enabledCheckbox = document.getElementById('schedule-enabled');
    const duplicatesCheckbox = document.getElementById('schedule-allow-duplicates');
    [enabledCheckbox, duplicatesCheckbox].forEach(checkbox => {
      if (checkbox) {
        checkbox.addEventListener('change', () => {
          hasUnsavedChanges = true;
        });
      }
    });

    // Handle cancel with warning
    let isCancelling = false;
    const handleCancel = async () => {
      // Atomic check-and-set: if already cancelling, return immediately
      if (isCancelling) return;
      isCancelling = true;
      
      // Disable cancel button immediately to prevent double-clicks
      const wasCancelDisabled = cancelBtn.disabled;
      cancelBtn.disabled = true;
      
      try {
        if (hasUnsavedChanges) {
          if (!await showConfirm('You have unsaved changes. Are you sure you want to cancel?', 'Confirm Cancellation')) {
            // User cancelled the cancellation, re-enable button
            cancelBtn.disabled = wasCancelDisabled;
            isCancelling = false;
            return;
          }
        }
        modal.remove();
      } catch (err) {
        // Re-enable button on error
        cancelBtn.disabled = wasCancelDisabled;
        isCancelling = false;
        console.error('Error during cancel:', err);
      }
    };
    
    cancelBtn.addEventListener('click', handleCancel);

    // Handle delete
    if (deleteBtn) {
      deleteBtn.addEventListener('click', async () => {
        if (!await showConfirm('Are you sure you want to delete this schedule? This will not delete cards already created.', 'Confirm Deletion')) {
          return;
        }

        // Show deleting state
        deleteBtn.disabled = true;
        deleteBtn.textContent = 'Deleting...';

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);

        try {
          const response = await fetch(`/api/schedules/${scheduleData.id}`, {
            method: 'DELETE',
            signal: controller.signal
          });

          clearTimeout(timeoutId);
          const data = await this.parseResponse(response);

          if (data.success) {
            modal.remove();
            // Close the edit card modal too
            const editModal = document.getElementById('edit-card-modal');
            if (editModal) editModal.remove();
            await this.loadBoard();
          } else {
            deleteBtn.disabled = false;
            deleteBtn.textContent = 'Delete Schedule';
            this.showErrorToast(`Failed to delete schedule: ${data.message}`);
          }
        } catch (err) {
          clearTimeout(timeoutId);
          console.error('Error deleting schedule:', err);
          deleteBtn.disabled = false;
          deleteBtn.textContent = 'Delete Schedule';
          
          if (err.name === 'AbortError') {
            this.showErrorToast('Delete schedule timed out (5s). Please check your connection.');
          } else {
            this.showErrorToast('An error occurred while deleting the schedule');
          }
        }
      });
    }

    // Handle edit template button
    const editTemplateBtn = document.getElementById('edit-template-btn');
    if (editTemplateBtn) {
      editTemplateBtn.addEventListener('click', async () => {
        const templateCardId = parseInt(editTemplateBtn.getAttribute('data-card-id'));
        if (templateCardId) {
          // Show loading state
          editTemplateBtn.disabled = true;
          editTemplateBtn.textContent = 'Loading...';

          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 5000);

          // Fetch the template card data
          try {
            const response = await fetch(`/api/cards/${templateCardId}`, {
              signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            const data = await this.parseResponse(response);
            
            if (data.success) {
              // Close schedule modal
              modal.remove();
              // Open edit card modal for the template
              this.openEditCardModal(templateCardId, data.card);
            } else {
              editTemplateBtn.disabled = false;
              editTemplateBtn.textContent = 'Edit Template';
              this.showErrorToast(`Failed to load template card: ${data.message}`);
            }
          } catch (err) {
            clearTimeout(timeoutId);
            console.error('Error loading template card:', err);
            editTemplateBtn.disabled = false;
            editTemplateBtn.textContent = 'Edit Template';
            
            if (err.name === 'AbortError') {
              this.showErrorToast('Load template card timed out (5s). Please check your connection.');
            } else {
              this.showErrorToast('Error loading template card');
            }
          }
        }
      });
    }

    // Handle form submit
    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      if (!allowScheduleSubmit) {
        this.showErrorToast('You do not have permission to save schedule changes.');
        return;
      }

      const formData = {
        run_every: parseInt(runEveryInput.value),
        unit: unitSelect.value,
        start_datetime: startDatetimeInput.value ? new Date(startDatetimeInput.value).toISOString() : null,
        end_datetime: endDatetimeInput.value ? new Date(endDatetimeInput.value).toISOString() : null,
        schedule_enabled: document.getElementById('schedule-enabled').checked,
        allow_duplicates: document.getElementById('schedule-allow-duplicates').checked
      };

      // Show saving state
      const saveBtn = modal.querySelector('button[type="submit"]');
      saveBtn.disabled = true;
      saveBtn.textContent = hasSchedule ? 'Updating...' : 'Creating...';

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      try {
        let response;
        
        if (hasSchedule) {
          // Update existing schedule
          response = await fetch(`/api/schedules/${scheduleData.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData),
            signal: controller.signal
          });
        } else {
          // Create new schedule
          const keepSourceCheckbox = document.getElementById('schedule-keep-source');
          response = await fetch('/api/schedules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              card_id: cardId,
              keep_source_card: keepSourceCheckbox ? keepSourceCheckbox.checked : true,
              ...formData
            }),
            signal: controller.signal
          });
        }

        clearTimeout(timeoutId);
        const data = await this.parseResponse(response);

        if (data.success) {
          modal.remove();
          // Close the edit card modal too
          const editModal = document.getElementById('edit-card-modal');
          if (editModal) editModal.remove();
          await this.loadBoard();
        } else {
          saveBtn.disabled = false;
          saveBtn.textContent = hasSchedule ? 'Update Schedule' : 'Create Schedule';
          this.showErrorToast(`Failed to save schedule: ${data.message}`);
        }
      } catch (err) {
        clearTimeout(timeoutId);
        console.error('Error saving schedule:', err);
        saveBtn.disabled = false;
        saveBtn.textContent = hasSchedule ? 'Update Schedule' : 'Create Schedule';
        
        if (err.name === 'AbortError') {
          this.showErrorToast('Save schedule timed out (5s). Please check your connection.');
        } else {
          this.showErrorToast('An error occurred while saving the schedule');
        }
      }
    });

    // Close modal when clicking outside (ignore text selection drags)
    setupModalBackgroundClose(modal, handleCancel);
    setupModalEscapeClose(modal, handleCancel);
  }

  openAddColumnModal() {
    // Check database connection
    if (window.header && !window.header.dbConnected) {
      this.showErrorToast('Cannot add column: Database is not connected. Please wait for the connection to be restored.');
      return;
    }
    
    // Create modal HTML
    const modalHtml = `
      <div class="modal" id="add-column-modal">
        <div class="modal-content">
          <h2>Add New Column</h2>
          <form id="add-column-form">
            <div class="form-group">
              <label for="column-name">Column Name:</label>
              <input type="text" id="column-name" name="column-name" required>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="cancel-column-btn">Cancel</button>
              <button type="submit" class="btn btn-primary">Create Column</button>
            </div>
          </form>
        </div>
      </div>
    `;

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Get modal elements
    const modal = document.getElementById('add-column-modal');
    const form = document.getElementById('add-column-form');
    const cancelBtn = document.getElementById('cancel-column-btn');
    const nameInput = document.getElementById('column-name');

    let removeEscapeClose = () => {};
    const closeModal = () => {
      removeEscapeClose();
      modal.remove();
    };

    removeEscapeClose = setupModalEscapeClose(modal, closeModal);

    // Focus on input
    nameInput.focus();

    // Handle cancel
    cancelBtn.addEventListener('click', () => {
      closeModal();
    });

    // Handle form submit
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const columnName = nameInput.value.trim();
      
      if (columnName) {
        await this.createColumn(columnName);
        closeModal();
      }
    });

    // Close modal on background click (ignore text selection drags)
    setupModalBackgroundClose(modal, () => modal.remove());
  }

  async openAddTemplateWithScheduleModal(columnId, order = null) {
    // Check database connection
    if (window.header && !window.header.dbConnected) {
      this.showErrorToast('Cannot create scheduled card: Database is not connected. Please wait for the connection to be restored.');
      return;
    }
    
    // Track the last used column for keyboard shortcuts
    this.lastUsedColumnId = columnId;
    
    // Track checklist items to be created
    let pendingChecklistItems = [];
    let checklistVisible = false;
    let hasUnsavedChanges = false;
    
    // Datetime-local expects local wall time, not UTC clock values.
    const toDatetimeLocalValue = (value) => {
      const date = value instanceof Date ? value : new Date(value);
      if (Number.isNaN(date.getTime())) return '';

      const pad = (num) => String(num).padStart(2, '0');
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
    };

    // Set default values for schedule
    const defaultStartDatetime = toDatetimeLocalValue(new Date());
    const defaultRunEvery = 1;
    const defaultUnit = 'day';
    const defaultEnabled = true;
    const defaultAllowDuplicates = false;
    
    // Create modal HTML
    const modalHtml = `
      <div class="modal" id="add-template-schedule-modal">
        <div class="modal-content schedule-modal-content">
          <div class="modal-header">
            <div class="modal-header-actions">
              <button type="button" class="btn btn-secondary" id="cancel-template-schedule-btn">Cancel</button>
              <button type="submit" form="add-template-schedule-form" class="btn btn-primary">Create Template & Schedule</button>
            </div>
            <h2>Add New Template with Schedule</h2>
          </div>
          <form id="add-template-schedule-form">
            <div class="form-group">
              <label for="template-title">Title:</label>
              <input type="text" id="template-title" name="template-title" required>
            </div>
            <div class="form-group">
              <label for="template-description">Description:</label>
              <textarea id="template-description" name="template-description" rows="4"></textarea>
            </div>
            
            <div class="checklist-section">
              <div id="checklist-header-container">
                <button type="button" class="btn btn-secondary" id="add-checklist-item-initial-btn">+ Add Checklist</button>
              </div>
              <div id="checklist-content-container" style="display: none;">
                <div class="checklist-header">
                  <h3>Checklist</h3>
                  <span class="checklist-summary" id="checklist-summary">0/0 (0%)</span>
                </div>
                <button type="button" class="btn btn-secondary btn-sm" id="add-checklist-item-top-btn">+ Add Item</button>
                <div class="checklist-items" id="new-template-checklist-items"></div>
                <button type="button" class="btn btn-secondary btn-sm" id="add-checklist-item-bottom-btn">+ Add Item</button>
              </div>
            </div>
            
            <hr style="margin: 30px 0; border: none; border-top: 2px solid var(--border-color);">
            
            <h3 style="margin-bottom: 20px;">Schedule Settings</h3>
            
            <div class="form-row">
              <div class="form-group">
                <label for="template-schedule-run-every">Run Every:</label>
                <input type="number" id="template-schedule-run-every" name="run-every" min="1" value="${defaultRunEvery}" required>
              </div>
              <div class="form-group">
                <label for="template-schedule-unit">Unit:</label>
                <select id="template-schedule-unit" name="unit" required>
                  <option value="minute" ${defaultUnit === 'minute' ? 'selected' : ''}>Minute(s)</option>
                  <option value="hour" ${defaultUnit === 'hour' ? 'selected' : ''}>Hour(s)</option>
                  <option value="day" ${defaultUnit === 'day' ? 'selected' : ''}>Day(s)</option>
                  <option value="week" ${defaultUnit === 'week' ? 'selected' : ''}>Week(s)</option>
                  <option value="month" ${defaultUnit === 'month' ? 'selected' : ''}>Month(s)</option>
                  <option value="year" ${defaultUnit === 'year' ? 'selected' : ''}>Year(s)</option>
                </select>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group full-width">
                <label for="template-schedule-start-datetime">Start Date & Time:</label>
                <input type="datetime-local" id="template-schedule-start-datetime" name="start-datetime" value="${defaultStartDatetime}" required>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group full-width">
                <label for="template-schedule-end-datetime">End Date & Time (Optional):</label>
                <input type="datetime-local" id="template-schedule-end-datetime" name="end-datetime">
              </div>
            </div>

            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" id="template-schedule-enabled" name="enabled" ${defaultEnabled ? 'checked' : ''}>
                <span>Schedule Enabled</span>
              </label>
            </div>

            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" id="template-schedule-allow-duplicates" name="allow-duplicates" ${defaultAllowDuplicates ? 'checked' : ''}>
                <span>Allow Duplicates (create new cards even if unarchived cards from this schedule exist)</span>
              </label>
            </div>

            <div class="next-runs-section" id="next-runs-section">
              <h3>Next 4 Scheduled Runs</h3>
              <div class="next-runs-list" id="next-runs-list">
                <p class="next-runs-loading">Calculating...</p>
              </div>
            </div>
          </form>
        </div>
      </div>
    `;

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Get modal elements
    const modal = document.getElementById('add-template-schedule-modal');
    const form = document.getElementById('add-template-schedule-form');
    const cancelBtn = document.getElementById('cancel-template-schedule-btn');
    const titleInput = document.getElementById('template-title');
    const runEveryInput = document.getElementById('template-schedule-run-every');
    const unitSelect = document.getElementById('template-schedule-unit');
    const startDatetimeInput = document.getElementById('template-schedule-start-datetime');
    const endDatetimeInput = document.getElementById('template-schedule-end-datetime');
    const nextRunsList = document.getElementById('next-runs-list');
    const checklistHeaderContainer = document.getElementById('checklist-header-container');
    const checklistContentContainer = document.getElementById('checklist-content-container');
    const checklistContainer = document.getElementById('new-template-checklist-items');

    // Focus on title input
    titleInput.focus();
    
    // Track changes in title and description
    titleInput.addEventListener('input', () => {
      hasUnsavedChanges = titleInput.value.trim() !== '';
    });
    
    const descriptionInput = document.getElementById('template-description');
    descriptionInput.addEventListener('input', () => {
      hasUnsavedChanges = titleInput.value.trim() !== '' || descriptionInput.value.trim() !== '';
    });
    
    // Track changes in schedule fields
    [runEveryInput, unitSelect, startDatetimeInput, endDatetimeInput].forEach(input => {
      input.addEventListener('input', () => {
        hasUnsavedChanges = true;
      });
      input.addEventListener('change', () => {
        hasUnsavedChanges = true;
      });
    });
    
    // Checklist management
    const updateChecklistSummary = () => {
      const summaryElement = document.getElementById('checklist-summary');
      if (summaryElement) {
        const total = pendingChecklistItems.length;
        const checked = pendingChecklistItems.filter(i => i.checked).length;
        const percentage = calculateChecklistPercentage(pendingChecklistItems);
        summaryElement.textContent = `${checked}/${total} (${percentage}%)`;
      }
    };
    
    this.setupNewCardChecklistDragAndDrop(checklistContainer, pendingChecklistItems);
    
    const checklistManager = new ChecklistManager(checklistContainer, pendingChecklistItems, {
      updateSummary: updateChecklistSummary,
      deleteButtonClass: 'checklist-delete-btn-new',
      onItemAdded: () => { hasUnsavedChanges = true; },
      onItemChanged: () => { hasUnsavedChanges = true; }
    });
    
    const showChecklistUI = () => {
      if (!checklistVisible) {
        checklistVisible = true;
        checklistHeaderContainer.style.display = 'none';
        checklistContentContainer.style.display = 'block';
      }
    };

    const addInitialBtn = document.getElementById('add-checklist-item-initial-btn');
    const addTopBtn = document.getElementById('add-checklist-item-top-btn');
    const addBottomBtn = document.getElementById('add-checklist-item-bottom-btn');
    
    if (addInitialBtn) {
      addInitialBtn.addEventListener('click', () => {
        showChecklistUI();
        checklistManager.addItem(false);
      });
    }
    if (addTopBtn) {
      addTopBtn.addEventListener('click', () => {
        showChecklistUI();
        checklistManager.addItem(true);
      });
    }
    if (addBottomBtn) {
      addBottomBtn.addEventListener('click', () => {
        showChecklistUI();
        checklistManager.addItem(false);
      });
    }

    // Function to calculate and display next runs
    const updateNextRuns = async () => {
      const runEvery = parseInt(runEveryInput.value);
      const unit = unitSelect.value;
      const startDatetime = startDatetimeInput.value;
      const endDatetime = endDatetimeInput.value || null;

      if (!runEvery || !unit || !startDatetime) {
        nextRunsList.innerHTML = '<p class="next-runs-empty">Please fill in required fields</p>';
        return;
      }

      try {
        // Calculate next runs client-side
        const startDateTime = new Date(startDatetime);
        const endDateTime = endDatetime ? new Date(endDatetime) : null;
        const now = new Date();

        let runs = [];
        let current = startDateTime;
        let attempts = 0;
        const maxAttempts = 100;

        while (runs.length < 4 && attempts < maxAttempts) {
          attempts++;
          
          if (current >= now && (!endDateTime || current <= endDateTime)) {
            runs.push(new Date(current));
          }

          // Add interval using utility function
          current = this.addInterval(current, runEvery, unit);

          if (endDateTime && current > endDateTime) break;
        }

        if (runs.length === 0) {
          nextRunsList.innerHTML = '<p class="next-runs-empty">No upcoming runs (schedule may have ended)</p>';
        } else {
          nextRunsList.innerHTML = runs.map(run => {
            const dateStr = run.toLocaleDateString('en-US', { 
              weekday: 'short', 
              year: 'numeric', 
              month: 'short', 
              day: 'numeric' 
            });
            const timeStr = formatTimeSync(run);
            return `<div class="next-run-item">📅 ${dateStr} at ${timeStr}</div>`;
          }).join('');
        }
      } catch (err) {
        console.error('Error calculating next runs:', err);
        nextRunsList.innerHTML = '<p class="next-runs-error">Error calculating runs</p>';
      }
    };

    // Update next runs on input change
    runEveryInput.addEventListener('input', updateNextRuns);
    unitSelect.addEventListener('change', updateNextRuns);
    startDatetimeInput.addEventListener('change', updateNextRuns);
    endDatetimeInput.addEventListener('change', updateNextRuns);

    // Initial calculation
    updateNextRuns();

    // Handle cancel with warning if there are unsaved changes
    let isCancelling = false;
    const handleCancel = async () => {
      // Atomic check-and-set: if already cancelling, return immediately
      if (isCancelling) return;
      isCancelling = true;
      
      // Disable cancel button immediately to prevent double-clicks
      const wasCancelDisabled = cancelBtn.disabled;
      cancelBtn.disabled = true;
      
      try {
        // Check if there's any content or checklist items
        const hasContent = hasUnsavedChanges || pendingChecklistItems.some(item => item.name && item.name.trim());
        
        if (hasContent) {
          if (await showConfirm('You have unsaved changes. Are you sure you want to cancel?', 'Confirm Cancellation')) {
            modal.remove();
          } else {
            // User cancelled the cancellation, re-enable button
            cancelBtn.disabled = wasCancelDisabled;
            isCancelling = false;
          }
        } else {
          modal.remove();
        }
      } catch (err) {
        // Re-enable button on error
        cancelBtn.disabled = wasCancelDisabled;
        isCancelling = false;
        console.error('Error during cancel:', err);
      }
    };
    
    cancelBtn.addEventListener('click', handleCancel);

    // Handle form submit - create template card with schedule in one API call
    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      const title = titleInput.value.trim();
      const description = document.getElementById('template-description').value.trim();
      const validChecklistItems = pendingChecklistItems.filter(item => item.name && item.name.trim());

      const scheduleData = {
        run_every: parseInt(runEveryInput.value),
        unit: unitSelect.value,
        start_datetime: startDatetimeInput.value ? new Date(startDatetimeInput.value).toISOString() : null,
        end_datetime: endDatetimeInput.value ? new Date(endDatetimeInput.value).toISOString() : null,
        schedule_enabled: document.getElementById('template-schedule-enabled').checked,
        allow_duplicates: document.getElementById('template-schedule-allow-duplicates').checked
      };

      try {
        // Step 1: Create the template card
        const cardBody = {
          title,
          description,
          scheduled: true
        };
        if (order !== null) {
          cardBody.order = order;
        }

        const cardResponse = await fetch(`/api/columns/${columnId}/cards`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(cardBody)
        });

        const cardData = await this.parseResponse(cardResponse);

        if (!cardData.success) {
          await showAlert('Failed to create template card: ' + cardData.message, 'Error');
          return;
        }

        const cardId = cardData.card.id;

        // Step 2: Create checklist items if any
        if (validChecklistItems.length > 0) {
          for (let i = 0; i < validChecklistItems.length; i++) {
            const item = validChecklistItems[i];
            await this.createChecklistItem(cardId, item.name, i, item.checked || false);
          }
        }

        // Step 3: Create the schedule
        const scheduleResponse = await fetch('/api/schedules', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            card_id: cardId,
            ...scheduleData,
            keep_source_card: false // Don't keep original since it IS the template
          })
        });

        const scheduleResponseData = await this.parseResponse(scheduleResponse);

        if (scheduleResponseData.success) {
          modal.remove();
          await this.loadBoard();
        } else {
          await showAlert('Failed to create schedule: ' + scheduleResponseData.message, 'Error');
        }

      } catch (err) {
        console.error('Error creating template with schedule:', err);
        await showAlert('Error creating template with schedule', 'Error');
      }
    });

    // Close modal on background click with warning (ignore text selection drags)
    setupModalBackgroundClose(modal, handleCancel);
    setupModalEscapeClose(modal, handleCancel);
  }

  async createColumn(name) {
    // Check database connection before creating column
    if (window.header && !window.header.dbConnected) {
      this.showErrorToast('Cannot create column: Database is not connected. Please wait for the connection to be restored.');
      return;
    }
    
    try {
      const response = await fetch(`/api/boards/${this.boardId}/columns`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name })
      });

      const data = await this.parseResponse(response);

      if (data.success) {
        // Reload columns to show the new one
        await this.loadBoard();
      } else {
        await showAlert('Failed to create column: ' + data.message, 'Error');
      }
    } catch (err) {
      await showAlert('Error creating column: ' + err.message, 'Error');
    }
  }

  async deleteColumn(columnId) {
    if (!await showConfirm('Are you sure you want to delete this column?', 'Confirm Deletion')) {
      return;
    }

    try {
      const response = await fetch(`/api/columns/${columnId}`, {
        method: 'DELETE'
      });

      const data = await this.parseResponse(response);

      if (data.success) {
        // Reload columns to reflect deletion
        await this.loadBoard();
      } else {
        await showAlert('Failed to delete column: ' + data.message, 'Error');
      }
    } catch (err) {
      await showAlert('Error deleting column: ' + err.message, 'Error');
    }
  }

  async deleteAllCardsInColumn(columnId) {
    if (!await showConfirm('Are you sure you want to delete all cards in this column? This action cannot be undone.', 'Confirm Deletion')) {
      return;
    }

    try {
      const url = `/api/columns/${columnId}/cards`;
      
      const response = await fetch(url, {
        method: 'DELETE'
      });

      const data = await this.parseResponse(response);

      if (data.success) {
        // Reload board to reflect deletion
        await this.loadBoard();
      } else {
        await showAlert('Failed to delete cards: ' + data.message, 'Error');
      }
    } catch (err) {
      console.error('Error deleting cards:', err);
      await showAlert('Error deleting cards: ' + err.message, 'Error');
    }
  }

  async archiveAllCardsInColumn(columnId) {
    const column = this.columns.find(c => c.id === columnId);
    if (!column || !column.cards) {
      await showAlert('No cards found in this column', 'Warning');
      return;
    }

    // Get all unarchived cards
    const unarchivedCards = column.cards.filter(c => !c.archived);
    if (unarchivedCards.length === 0) {
      await showAlert('No active cards to archive in this column', 'Warning');
      return;
    }

    if (!await showConfirm(`Are you sure you want to archive all ${unarchivedCards.length} active card(s) in this column?`, 'Confirm Archive')) {
      return;
    }

    try {
      const cardIds = unarchivedCards.map(c => c.id);
      const response = await fetch('/api/cards/batch/archive', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ card_ids: cardIds })
      });

      const data = await this.parseResponse(response);

      if (data.success) {
        await this.loadBoard();
        await showAlert(`Successfully archived ${data.archived_count} card(s)`, 'Success');
      } else {
        await showAlert(data.message || 'Failed to archive cards', 'Error');
      }
    } catch (err) {
      console.error('Error archiving cards:', err);
      await showAlert('Error archiving cards: ' + err.message, 'Error');
    }
  }

  async unarchiveAllCardsInColumn(columnId) {
    const column = this.columns.find(c => c.id === columnId);
    if (!column || !column.cards) {
      await showAlert('No cards found in this column', 'Warning');
      return;
    }

    // Get all archived cards
    const archivedCards = column.cards.filter(c => c.archived);
    if (archivedCards.length === 0) {
      await showAlert('No archived cards to unarchive in this column', 'Warning');
      return;
    }

    if (!confirm(`Are you sure you want to unarchive all ${archivedCards.length} archived card(s) in this column?`)) {
      return;
    }

    try {
      const cardIds = archivedCards.map(c => c.id);
      const response = await fetch('/api/cards/batch/unarchive', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ card_ids: cardIds })
      });

      const data = await this.parseResponse(response);

      if (data.success) {
        await this.loadBoard();
        await showAlert(`Successfully unarchived ${data.unarchived_count} card(s)`, 'Success');
      } else {
        await showAlert(data.message || 'Failed to unarchive cards', 'Error');
      }
    } catch (err) {
      console.error('Error unarchiving cards:', err);
      await showAlert('Error unarchiving cards: ' + err.message, 'Error');
    }
  }

  async openMoveAllCardsModal(sourceColumnId) {
    if (window.header && !window.header.dbConnected) {
      this.showErrorToast('Cannot move cards: Database is not connected. Please wait for the connection to be restored.');
      return;
    }

    const sourceColumn = this.columns.find(c => c.id === sourceColumnId);
    if (!sourceColumn || !sourceColumn.cards || sourceColumn.cards.length === 0) {
      await showAlert('No cards to move in this column', 'Warning');
      return;
    }

    const activeCardCount = sourceColumn.cards.filter(c => !c.archived).length;
    const archivedCardCount = sourceColumn.cards.filter(c => c.archived).length;

    let cardCountMessage = `${activeCardCount} active card(s)`;
    if (archivedCardCount > 0) {
      cardCountMessage += ` (${archivedCardCount} archived)`;
    }

    // Fetch accessible boards
    let boards = [];
    try {
      const boardsController = new AbortController();
      const boardsTimeout = setTimeout(() => boardsController.abort(), 5000);
      const boardsResponse = await fetch('/api/boards?archived=false', { signal: boardsController.signal });
      clearTimeout(boardsTimeout);
      const boardsData = await this.parseResponse(boardsResponse);
      if (boardsData.success) {
        boards = boardsData.boards;
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        this.showErrorToast('Timed out loading boards. Showing current board only.');
      } else {
        console.error('Failed to fetch boards:', err);
      }
    }
    if (boards.length === 0) {
      boards = [{ id: this.boardId, name: this.boardName }];
    }

    const currentBoardColumns = this.columns.filter(c => c.id !== sourceColumnId);

    const buildColumnOptions = (columns) =>
      columns.length === 0
        ? '<option value="">-- No columns available --</option>'
        : '<option value="">-- Select Column --</option>' +
          columns.map(col => `<option value="${col.id}">${this.escapeHtml(col.name)}</option>`).join('');

    const modalHtml = `
      <div class="modal" id="move-all-cards-modal" role="dialog" aria-modal="true" aria-labelledby="move-all-cards-modal-title" aria-describedby="move-all-cards-modal-desc">
        <div class="modal-content">
          <h2 id="move-all-cards-modal-title">Move All Cards</h2>
          <p id="move-all-cards-modal-desc">Move ${cardCountMessage} from <strong>${this.escapeHtml(sourceColumn.name)}</strong> to:</p>
          <form id="move-all-cards-form">
            <div class="form-group">
              <label for="move-all-target-board">Target Board:</label>
              <select id="move-all-target-board" name="target-board">
                ${boards.map(b => `<option value="${b.id}" ${b.id === this.boardId ? 'selected' : ''}>${this.escapeHtml(b.name)}</option>`).join('')}
              </select>
            </div>
            <div class="form-group">
              <label for="target-column-select">Target Column:</label>
              <select id="target-column-select" name="target-column" required aria-required="true">
                ${buildColumnOptions(currentBoardColumns)}
              </select>
            </div>
            <div class="form-group">
              <label for="position-select">Position:</label>
              <select id="position-select" name="position" required aria-required="true">
                <option value="top">Top of column</option>
                <option value="bottom">Bottom of column</option>
              </select>
            </div>
            <div class="form-group">
              <label>
                <input type="checkbox" id="include-archived-checkbox" name="include-archived">
                Include archived cards
              </label>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="cancel-move-all-btn">Cancel</button>
              <button type="submit" class="btn btn-primary">Move Cards</button>
            </div>
          </form>
        </div>
      </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modal = document.getElementById('move-all-cards-modal');
    const form = document.getElementById('move-all-cards-form');
    const cancelBtn = document.getElementById('cancel-move-all-btn');
    const boardSelect = document.getElementById('move-all-target-board');
    const targetSelect = document.getElementById('target-column-select');
    const positionSelect = document.getElementById('position-select');
    const includeArchivedCheckbox = document.getElementById('include-archived-checkbox');

    boardSelect.focus();

    const loadColumnsForBoard = async (boardId) => {
      if (boardId === this.boardId) {
        targetSelect.innerHTML = buildColumnOptions(currentBoardColumns);
        return;
      }
      targetSelect.innerHTML = '<option value="">Loading...</option>';
      targetSelect.disabled = true;
      try {
        const colController = new AbortController();
        const colTimeout = setTimeout(() => colController.abort(), 5000);
        const response = await fetch(`/api/boards/${boardId}/columns`, { signal: colController.signal });
        clearTimeout(colTimeout);
        const data = await this.parseResponse(response);
        if (data.success && data.columns) {
          targetSelect.innerHTML = buildColumnOptions(data.columns);
        } else {
          targetSelect.innerHTML = '<option value="">-- No columns available --</option>';
          this.showErrorToast(data.message || 'Failed to load columns');
        }
      } catch (err) {
        targetSelect.innerHTML = '<option value="">-- Error loading columns --</option>';
        if (err.name === 'AbortError') {
          this.showErrorToast('Timed out loading columns');
        } else {
          console.error('Failed to fetch columns:', err);
          this.showErrorToast('Failed to load columns');
        }
      } finally {
        targetSelect.disabled = false;
      }
    };

    boardSelect.addEventListener('change', () => {
      loadColumnsForBoard(parseInt(boardSelect.value));
    });

    cancelBtn.addEventListener('click', () => {
      modal.remove();
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const targetColumnId = parseInt(targetSelect.value);
      const position = positionSelect.value;
      const includeArchived = includeArchivedCheckbox.checked;
      const targetBoardId = parseInt(boardSelect.value);

      if (targetColumnId && position) {
        modal.remove();
        await this.moveAllCards(sourceColumnId, targetColumnId, position, includeArchived, targetBoardId);
      }
    });

    setupModalBackgroundClose(modal, () => modal.remove());
  }

  async openArchiveAfterModal(columnId) {
    // Check database connection
    if (window.header && !window.header.dbConnected) {
      this.showErrorToast('Cannot archive cards: Database is not connected. Please wait for the connection to be restored.');
      return;
    }
    
    // Get column and its cards
    const column = this.columns.find(c => c.id === columnId);
    if (!column) {
      await showAlert('Column not found', 'Error');
      return;
    }

    // Create modal HTML
    const modalHtml = `
      <div class="modal" id="archive-after-modal" role="dialog" aria-modal="true" aria-labelledby="archive-after-title" aria-describedby="archive-after-description">
        <div class="modal-content">
          <h2 id="archive-after-title">Archive Cards After Period</h2>
          <p id="archive-after-description" class="modal-description">This will archive all cards in <strong>${this.escapeHtml(column.name)}</strong> that haven't been updated within the specified time period. The card's last update time is used to determine eligibility.</p>
          <form id="archive-after-form">
            <div class="form-group">
              <label for="archive-quantity">Archive cards older than:</label>
              <div class="archive-after-input-row">
                <input type="number" id="archive-quantity" name="quantity" min="1" step="1" value="7" required aria-required="true">
                <select id="archive-period" name="period" required aria-required="true">
                  <option value="minutes">Minutes</option>
                  <option value="hours">Hours</option>
                  <option value="days" selected>Days</option>
                  <option value="weeks">Weeks</option>
                </select>
              </div>
            </div>
            <div id="preview-section" class="archive-after-preview" style="display: none;" role="region" aria-live="polite">
              <h3 class="archive-after-preview-title">Preview - Most Recent Card to Archive:</h3>
              <div id="preview-content"></div>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="cancel-archive-after-btn">Cancel</button>
              <button type="button" class="btn btn-secondary" id="preview-archive-after-btn">Preview</button>
              <button type="submit" class="btn btn-primary">Archive</button>
            </div>
          </form>
        </div>
      </div>
    `;

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Get modal elements
    const modal = document.getElementById('archive-after-modal');
    const form = document.getElementById('archive-after-form');
    const cancelBtn = document.getElementById('cancel-archive-after-btn');
    const previewBtn = document.getElementById('preview-archive-after-btn');
    const quantityInput = document.getElementById('archive-quantity');
    const periodSelect = document.getElementById('archive-period');
    const previewSection = document.getElementById('preview-section');
    const previewContent = document.getElementById('preview-content');

    // Focus on quantity input
    quantityInput.focus();
    quantityInput.select();

    // Handle cancel
    cancelBtn.addEventListener('click', () => {
      modal.remove();
    });

    // Handle preview
    previewBtn.addEventListener('click', async () => {
      const quantity = parseInt(quantityInput.value);
      const period = periodSelect.value;
      
      if (!quantity || quantity < 1) {
        await showAlert('Please enter a valid quantity (minimum 1)', 'Warning');
        return;
      }
      
      previewBtn.disabled = true;
      previewBtn.textContent = 'Loading...';
      
      try {
        const response = await fetch(`/api/columns/${columnId}/archive-after`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            quantity: quantity,
            period: period,
            dry_run: true
          })
        });
        
        const data = await response.json();
        
        if (response.ok && data.success) {
          if (data.affected_count === 0) {
            previewContent.innerHTML = '<p class="archive-after-preview-empty">No cards would be archived with these settings.</p>';
          } else {
            const card = data.most_recent_card;
            const updatedDate = new Date(card.updated_at || card.created_at);
            const now = new Date();
            const daysDiff = Math.floor((now - updatedDate) / (1000 * 60 * 60 * 24));
            const affectedCount = parseInt(data.affected_count) || 0;
            
            previewContent.innerHTML = `
              <div class="archive-after-preview-card">
                <div class="archive-after-preview-card-title">${this.escapeHtml(card.title)}</div>
                <div class="archive-after-preview-card-meta">
                  Last updated: ${updatedDate.toLocaleString()} (${daysDiff} days ago)
                </div>
                <div class="archive-after-preview-card-summary">
                  <strong>${affectedCount}</strong> card(s) would be archived
                </div>
              </div>
            `;
          }
          previewSection.style.display = 'block';
        } else {
          await showAlert(data.message || 'Failed to preview archive operation', 'Error');
        }
      } catch (err) {
        console.error('Error previewing archive:', err);
        await showAlert('Error previewing archive operation', 'Error');
      } finally {
        previewBtn.disabled = false;
        previewBtn.textContent = 'Preview';
      }
    });

    // Handle form submit
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const quantity = parseInt(quantityInput.value);
      const period = periodSelect.value;
      
      if (!quantity || quantity < 1) {
        await showAlert('Please enter a valid quantity (minimum 1)', 'Warning');
        return;
      }
      
      modal.remove();
      await this.archiveCardsAfter(columnId, quantity, period);
    });

    // Close modal on background click
    setupModalBackgroundClose(modal, () => modal.remove());
  }

  async archiveCardsAfter(columnId, quantity, period) {
    // Create AbortController for timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    
    try {
      const response = await fetch(`/api/columns/${columnId}/archive-after`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          quantity: quantity,
          period: period,
          dry_run: false
        }),
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const data = await this.parseResponse(response);
      
      if (response.ok && data.success) {
        this.showSuccessToast(`Archived ${data.archived_count} card(s)`);
        await this.loadBoard(this.currentBoardId);
      } else {
        this.showErrorToast(data.message || 'Failed to archive cards');
      }
    } catch (err) {
      clearTimeout(timeoutId);
      console.error('Error archiving cards:', err);
      
      if (err.name === 'AbortError') {
        this.showErrorToast('Archive request timed out. Please check your connection.');
      } else {
        this.showErrorToast('Error archiving cards');
      }
    }
  }

  async moveAllCards(sourceColumnId, targetColumnId, position, includeArchived = false, targetBoardId = null) {
    const sourceColumn = this.columns.find(c => c.id === sourceColumnId);
    if (!sourceColumn || !sourceColumn.cards || sourceColumn.cards.length === 0) {
      return;
    }

    // For same-board moves, validate target column exists locally
    const isCrossBoard = targetBoardId !== null && targetBoardId !== this.boardId;
    if (!isCrossBoard) {
      const targetColumn = this.columns.find(c => c.id === targetColumnId);
      if (!targetColumn) {
        await showAlert('Target column not found', 'Error');
        return;
      }
    }

    try {
      // Use batch move endpoint for atomic operation
      const response = await fetch(`/api/columns/${sourceColumnId}/cards/move`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          target_column_id: targetColumnId,
          position: position,
          include_archived: includeArchived
        })
      });

      const data = await this.parseResponse(response);
      
      if (!data.success) {
        throw new Error(data.message || 'Failed to move cards');
      }
      
      // Reload board to reflect changes
      await this.loadBoard();
      
      await showAlert(`Successfully moved ${data.moved_count} card(s)`, 'Success');
    } catch (err) {
      console.error('Error moving cards:', err);
      await showAlert('Error moving cards: ' + err.message, 'Error');
    }
  }

  openEditColumnModal(columnId, currentName) {
    // Check database connection
    if (window.header && !window.header.dbConnected) {
      this.showErrorToast('Cannot edit column: Database is not connected. Please wait for the connection to be restored.');
      return;
    }
    
    // Create modal HTML
    const modalHtml = `
      <div class="modal" id="edit-column-modal">
        <div class="modal-content">
          <h2>Edit Column</h2>
          <form id="edit-column-form">
            <div class="form-group">
              <label for="edit-column-name">Column Name:</label>
              <input type="text" id="edit-column-name" name="edit-column-name" value="${this.escapeHtml(currentName)}" required>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="cancel-edit-column-btn">Cancel</button>
              <button type="submit" class="btn btn-primary">Save</button>
            </div>
          </form>
        </div>
      </div>
    `;

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Get modal elements
    const modal = document.getElementById('edit-column-modal');
    const form = document.getElementById('edit-column-form');
    const cancelBtn = document.getElementById('cancel-edit-column-btn');
    const nameInput = document.getElementById('edit-column-name');

    // Focus on input and select text
    nameInput.focus();
    nameInput.select();

    // Handle cancel
    cancelBtn.addEventListener('click', () => {
      modal.remove();
    });

    // Handle form submit
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const columnName = nameInput.value.trim();
      
      if (columnName) {
        await this.updateColumn(columnId, columnName);
        modal.remove();
      }
    });

    // Close modal on background click (ignore text selection drags)
    setupModalBackgroundClose(modal, () => modal.remove());
  }

  async updateColumn(columnId, name) {
    try {
      const response = await fetch(`/api/columns/${columnId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name })
      });

      const data = await this.parseResponse(response);

      if (data.success) {
        // Reload columns to show the updated name
        await this.loadBoard();
      } else {
        await showAlert('Failed to update column: ' + data.message, 'Error');
      }
    } catch (err) {
      await showAlert('Error updating column: ' + err.message, 'Error');
    }
  }

  openAddCardModal(columnId, order = null, scheduled = false, defaultStartDate = null, defaultEndDate = null) {
    // Check database connection before opening modal
    if (window.header && !window.header.dbConnected) {
      this.showErrorToast('Cannot create card: Database is not connected. Please wait for the connection to be restored.');
      return;
    }
    
    // Check if board is read-only
    if (!this.canEdit) {
      this.showErrorToast('Cannot create card: This board is read-only');
      return;
    }
    
    // If we're in scheduled view, open the combined template+schedule modal instead
    if (scheduled) {
      this.openAddTemplateWithScheduleModal(columnId, order);
      return;
    }
    
    // Track the last used column for keyboard shortcuts
    this.lastUsedColumnId = columnId;
    
    // Track checklist items to be created
    let pendingChecklistItems = [];
    let checklistVisible = false;
    let hasUnsavedChanges = false;
    
    // Create modal HTML
    const modalHtml = `
      <div class="modal" id="add-card-modal">
        <div class="modal-content card-modal-content">
          <h2>${scheduled ? 'Add New Template Card' : 'Add New Card'}</h2>
          <form id="add-card-form">
            <div class="form-group">
              <label for="card-title">Title:</label>
              <input type="text" id="card-title" name="card-title" required>
            </div>
            <div class="form-group">
              <label for="card-description">Description:</label>
              <textarea id="card-description" name="card-description" rows="4"></textarea>
            </div>
            
            <div class="checklist-section">
              <div id="checklist-header-container">
                <button type="button" class="btn btn-secondary" id="add-checklist-item-initial-btn">+ Add Checklist</button>
              </div>
              <div id="checklist-content-container" style="display: none;">
                <div class="checklist-header">
                  <h3>Checklist</h3>
                  <span class="checklist-summary" id="checklist-summary">0/0 (0%)</span>
                </div>
                <button type="button" class="btn btn-secondary btn-sm" id="add-checklist-item-top-btn">+ Add Item</button>
                <div class="checklist-items" id="new-card-checklist-items"></div>
                <button type="button" class="btn btn-secondary btn-sm" id="add-checklist-item-bottom-btn">+ Add Item</button>
              </div>
            </div>
            
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="cancel-card-btn">Cancel</button>
              <button type="submit" class="btn btn-primary">Create Card</button>
            </div>
          </form>
        </div>
      </div>
    `;

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Get modal elements
    const modal = document.getElementById('add-card-modal');
    const form = document.getElementById('add-card-form');
    const cancelBtn = document.getElementById('cancel-card-btn');
    const titleInput = document.getElementById('card-title');
    const checklistHeaderContainer = document.getElementById('checklist-header-container');
    const checklistContentContainer = document.getElementById('checklist-content-container');
    const checklistContainer = document.getElementById('new-card-checklist-items');

    // Focus on input
    titleInput.focus();
    
    // Track changes in title and description
    titleInput.addEventListener('input', () => {
      hasUnsavedChanges = titleInput.value.trim() !== '';
    });
    
    const descriptionInput = document.getElementById('card-description');
    descriptionInput.addEventListener('input', () => {
      hasUnsavedChanges = titleInput.value.trim() !== '' || descriptionInput.value.trim() !== '';
    });
    
    // Helper to update checklist summary
    const updateChecklistSummary = () => {
      const summaryElement = document.getElementById('checklist-summary');
      if (summaryElement) {
        const total = pendingChecklistItems.length;
        const checked = pendingChecklistItems.filter(i => i.checked).length;
        const percentage = calculateChecklistPercentage(pendingChecklistItems);
        summaryElement.textContent = `${checked}/${total} (${percentage}%)`;
      }
    };
    
    // Set up drag and drop with event delegation (only needs to be called once)
    this.setupNewCardChecklistDragAndDrop(checklistContainer, pendingChecklistItems);
    
    // Create checklist manager with event delegation
    const checklistManager = new ChecklistManager(checklistContainer, pendingChecklistItems, {
      updateSummary: updateChecklistSummary,
      deleteButtonClass: 'checklist-delete-btn-new',
      onItemAdded: () => { hasUnsavedChanges = true; },
      onItemChanged: () => { hasUnsavedChanges = true; }
    });
    
    // Show checklist UI with header and top/bottom buttons
    const showChecklistUI = () => {
      if (!checklistVisible) {
        checklistVisible = true;
        checklistHeaderContainer.style.display = 'none';
        checklistContentContainer.style.display = 'block';
      }
    };

    // Handle add checklist item buttons
    const addInitialBtn = document.getElementById('add-checklist-item-initial-btn');
    const addTopBtn = document.getElementById('add-checklist-item-top-btn');
    const addBottomBtn = document.getElementById('add-checklist-item-bottom-btn');
    
    if (addInitialBtn) {
      addInitialBtn.addEventListener('click', () => {
        showChecklistUI();
        checklistManager.addItem(false);
      });
    }
    if (addTopBtn) {
      addTopBtn.addEventListener('click', () => {
        showChecklistUI();
        checklistManager.addItem(true);
      });
    }
    if (addBottomBtn) {
      addBottomBtn.addEventListener('click', () => {
        showChecklistUI();
        checklistManager.addItem(false);
      });
    }

    // Handle cancel with warning if there are unsaved changes
    let isCancelling = false;
    const handleCancel = async () => {
      // Atomic check-and-set: if already cancelling, return immediately
      if (isCancelling) return;
      isCancelling = true;
      
      // Disable cancel button immediately to prevent double-clicks
      const wasCancelDisabled = cancelBtn.disabled;
      cancelBtn.disabled = true;
      
      try {
        // Check if there's any content or checklist items
        const hasContent = hasUnsavedChanges || pendingChecklistItems.some(item => item.name && item.name.trim());
        
        if (hasContent) {
          if (await showConfirm('You have unsaved changes. Are you sure you want to cancel?', 'Confirm Cancellation')) {
            modal.remove();
          } else {
            // User cancelled the cancellation, re-enable button
            cancelBtn.disabled = wasCancelDisabled;
            isCancelling = false;
          }
        } else {
          modal.remove();
        }
      } catch (err) {
        // Re-enable button on error
        cancelBtn.disabled = wasCancelDisabled;
        isCancelling = false;
        console.error('Error during cancel:', err);
      }
    };
    
    cancelBtn.addEventListener('click', handleCancel);

    // Handle form submit
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const title = titleInput.value.trim();
      const description = document.getElementById('card-description').value.trim();
      const submitBtn = form.querySelector('button[type="submit"]');
      
      if (title) {
        // Disable button and show loading state
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Creating...';
        submitBtn.style.opacity = '0.6';
        
        // Filter out empty checklist items
        const validChecklistItems = pendingChecklistItems.filter(item => item.name && item.name.trim());
        const success = await this.createCard(columnId, title, description, order, validChecklistItems, scheduled, defaultStartDate, defaultEndDate);
        
        if (success) {
          modal.remove();
        } else {
          // Re-enable button on failure - keep modal open
          submitBtn.disabled = false;
          submitBtn.textContent = originalText;
          submitBtn.style.opacity = '';
        }
      }
    });

    // Close modal on background click with warning (ignore text selection drags)
    setupModalBackgroundClose(modal, handleCancel);
    setupModalEscapeClose(modal, handleCancel);
  }

  async createCard(columnId, title, description, order = null, checklistItems = [], scheduled = false, startDate = null, endDate = null) {
    // Set 5 second timeout for the request
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const body = { title, description };
      if (order !== null) {
        body.order = order;
      }
      if (scheduled) {
        body.scheduled = scheduled;
      }
      if (startDate) {
        body.start_date = startDate;
      }
      if (endDate) {
        body.end_date = endDate;
      }

      const response = await fetch(`/api/columns/${columnId}/cards`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(body),
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      const data = await response.json();

      if (data.success) {
        const cardId = data.card.id;
        
        // The server broadcasts card_created to other clients via WebSocket.
        // For the originating client, we reload the board immediately via loadBoard()
        // to ensure instant UI update without waiting for broadcast.
        
        // TODO: Consider creating a batch endpoint POST /api/cards/batch that accepts card + checklist items
        // in a single request to avoid multiple sequential API calls and ensure atomicity.
        // This would prevent race conditions and improve performance.
        // If there are checklist items, create them with their checked state
        if (checklistItems.length > 0) {
          for (let i = 0; i < checklistItems.length; i++) {
            const item = checklistItems[i];
            // Pass checked state directly to createChecklistItem
            await this.createChecklistItem(cardId, item.name, i, item.checked || false);
          }
        }
        
        // Reload board once at the end to show the new card
        await this.loadBoard();
        this.refreshPlannerIfVisible();

        // If this is a template card, prompt to create a schedule
        if (scheduled) {
          const createSchedule = await showConfirm(
            'Template card created! Would you like to create a schedule for it now?\n\nSchedules automatically create new task cards from this template at regular intervals.',
            'Create Schedule?'
          );
          
          if (createSchedule) {
            try {
              this.openScheduleModal(cardId);
            } catch (err) {
              console.error('Error opening schedule modal:', err);
              this.showErrorToast('Failed to open schedule editor');
            }
          }
        }
        
        return true;
      } else {
        console.error('Failed to create card:', data.message);
        this.showErrorToast('Failed to create card');
        return false;
      }
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        console.error('Create card timeout after 5 seconds');
        this.showErrorToast('Request timed out. Check your connection.');
      } else {
        console.error('Error creating card:', err);
        this.showErrorToast('Failed to create card');
      }
      return false;
    }
  }

  openEditCardModal(cardId, cardData) {
    // Check database connection before opening modal.
    // This guards against losing unsaved edits if the DB drops while the user
    // is editing. Public users cannot edit cards, so the check is unnecessary
    // and would always block them (the db-status widget is not present on the
    // public board page and dbConnected is never set true there).
    if (!this.isPublicMode && window.header && !window.header.dbConnected) {
      this.showErrorToast('Cannot edit card: Database is not connected. Please wait for the connection to be restored.');
      return;
    }
    
    // Note: We allow opening the modal in read-only mode to view card details
    // The form inputs will be disabled via the isReadOnly checks below
    
    const checklistItems = cardData.checklist_items || [];
    const comments = cardData.comments || [];
    const hasChecklist = checklistItems.length > 0;
    const hasComments = comments.length > 0;
    
    // Remove any existing edit card modal to prevent duplicates
    const existingModal = document.getElementById('edit-card-modal');
    if (existingModal) {
      existingModal.remove();
    }
    
    // Store original values for change detection
    const originalTitle = cardData.title;
    const originalDescription = cardData.description || '';

    // Datetime-local controls expect local wall time strings (no timezone suffix).
    const toDatetimeLocalValue = (value) => {
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return '';

      const pad = (num) => String(num).padStart(2, '0');
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
    };

    const defaultStartDate = toDatetimeLocalValue(cardData.start_date);
    const defaultEndDate = toDatetimeLocalValue(cardData.end_date);
    const initialDuration = diffToDuration(defaultStartDate, defaultEndDate);
    const defaultDurationDays = initialDuration ? initialDuration.days : '';
    const defaultDurationHours = initialDuration ? initialDuration.hours : '';

    // Check if this is a scheduled template card
    const isTemplate = cardData.scheduled === true;
    const cardHasSchedule = !!cardData.schedule;
    
    // Check if board is read-only
    const isReadOnly = !this.canEdit;
    const modalTitle = isTemplate
      ? (isReadOnly ? 'Card Template Detail' : 'Edit Card Template')
      : (isReadOnly ? 'Card Detail' : 'Edit Card');
    const readonlyAttr = isReadOnly ? 'readonly' : '';
    const disabledAttr = isReadOnly ? 'disabled' : '';

    const canArchiveCard = this.canCallPermissionEndpoint('PATCH', '/api/cards/:id/archive');
    const canUnarchiveCard = this.canCallPermissionEndpoint('PATCH', '/api/cards/:id/unarchive');
    const canDeleteCard = this.canCallPermissionEndpoint('DELETE', '/api/cards/:id');
    const canToggleDone = this.canCallPermissionEndpoint('PATCH', '/api/cards/:id/done');
    const canManageAssignees = this.canCallPermissionEndpoint('PUT', '/api/cards/:id/assignees');
    const canCreateSchedule = this.canCallPermissionEndpoint('POST', '/api/schedules');
    const canEditSchedule = this.canCallPermissionEndpoint('PUT', '/api/schedules/:id');
    const canDeleteSchedule = this.canCallPermissionEndpoint('DELETE', '/api/schedules/:id');
    const canOpenScheduleEditor = cardHasSchedule
      ? (canEditSchedule || canDeleteSchedule)
      : canCreateSchedule;
    // "View in Planner" jumps straight to the month containing an existing
    // anchor date; "Place in Planner" (no start/end set yet) instead drops
    // the card into placement mode so the user can click a day to schedule
    // it. Both are always available - placing with no duration entered
    // falls back to a 1 hour task.
    const hasInitialAnchorDate = !!cardData.start_date || !!cardData.end_date;
    const plannerBtnLabel = hasInitialAnchorDate ? '📅 View in Planner' : '📅 Place in Planner';
    
    // Track changes
    let hasUnsavedChanges = false;
    let checklistOrderChanged = false;
    
    // Create modal HTML
    const modalHtml = `
      <div class="modal" id="edit-card-modal">
        <div class="modal-content card-modal-content">
          <div class="modal-header">
            ${isReadOnly ? '<div class="board-readonly-indicator" style="position: static; margin-bottom: 10px;">Read Only</div>' : ''}
            <div class="modal-header-actions">
              ${isTemplate && canOpenScheduleEditor ?
                `<button type="button" class="btn btn-secondary" id="edit-schedule-from-template-btn" data-card-id="${cardData.id}" data-has-schedule="${cardData.schedule ? 'true' : 'false'}">
                  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                  </svg>
                  Edit Schedule
                </button>` : !isReadOnly ?
                cardData.archived ? 
                  `${canUnarchiveCard ? `<button type="button" class="btn btn-secondary" id="unarchive-card-detail-btn" data-card-id="${cardData.id}">📂 Unarchive</button>` : ''}` :
                  `${this.workingStyle === 'agile' ? 
                    `${canToggleDone ? `<button type="button" class="btn btn-secondary" id="done-card-detail-btn" data-card-id="${cardData.id}" title="${cardData.done ? 'Mark as not done' : 'Mark as done'}">
                      ${cardData.done ? '○ Mark Not Done' : '✓ Mark Done'}
                    </button>` : ''}` :
                    ''
                  }
                  ${canArchiveCard && this.workingStyle !== 'agile' ? '<button type="button" class="btn btn-secondary" id="archive-card-detail-btn" data-card-id="' + cardData.id + '">🗄️ Archive</button>' : ''}` : ''
              }
              ${!isReadOnly && canManageAssignees ? `<button type="button" class="btn btn-secondary" id="assign-assignees-btn" data-card-id="${cardData.id}">👤 Assignees</button>` : ''}
              ${!isReadOnly ? `<button type="button" class="btn btn-secondary" id="view-planner-btn" data-card-id="${cardData.id}">${plannerBtnLabel}</button>` : ''}
              ${!isReadOnly && canDeleteCard ? `<button type="button" class="btn btn-danger" id="delete-card-detail-btn" data-card-id="${cardData.id}">Delete</button>` : ''}
              <button type="button" class="btn btn-secondary" id="cancel-edit-card-btn">${isReadOnly ? 'Close' : 'Cancel'}</button>
              ${!isReadOnly ? '<button type="submit" form="edit-card-form" class="btn btn-primary">Save</button>' : ''}
            </div>
            <h2>
              ${modalTitle}
              <span class="card-ref-number">Ref: #${cardData.id}</span>
            </h2>
          </div>
          <form id="edit-card-form">
            <div class="form-group">
              <label for="edit-card-title">Title:</label>
              <input type="text" id="edit-card-title" name="edit-card-title" value="${this.escapeHtml(cardData.title)}" required ${readonlyAttr}>
            </div>
            <div class="form-group">
              <label for="edit-card-description">Description:</label>
              <textarea id="edit-card-description" name="edit-card-description" rows="4" ${readonlyAttr}>${this.escapeHtml(cardData.description || '')}</textarea>
            </div>
            <div class="form-group">
              <label for="edit-card-start-date">Start Date:</label>
              <input type="datetime-local" id="edit-card-start-date" name="edit-card-start-date" value="${defaultStartDate}" ${disabledAttr}>
            </div>
            <div class="form-group">
              <label for="edit-card-end-date">End Date:</label>
              <input type="datetime-local" id="edit-card-end-date" name="edit-card-end-date" value="${defaultEndDate}" ${disabledAttr}>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label for="edit-card-duration-days">Duration (days):</label>
                <input type="number" id="edit-card-duration-days" name="edit-card-duration-days" min="0" value="${defaultDurationDays}" ${disabledAttr}>
              </div>
              <div class="form-group">
                <label for="edit-card-duration-hours">Duration (hours):</label>
                <input type="number" id="edit-card-duration-hours" name="edit-card-duration-hours" min="0" max="23" value="${defaultDurationHours}" ${disabledAttr}>
              </div>
            </div>
            
            ${!isTemplate && canOpenScheduleEditor ? `
            <div class="schedule-section">
              <button type="button" class="btn btn-secondary" id="schedule-card-btn" data-card-id="${cardData.id}" data-has-schedule="${cardData.schedule ? 'true' : 'false'}">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px;">
                  <circle cx="12" cy="12" r="10"></circle>
                  <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                ${cardData.schedule ? 'Edit Schedule' : 'Create Schedule'}
              </button>
            </div>
            ` : ''}
            
            <div class="checklist-section">
              ${hasChecklist ? `
                <div class="checklist-header">
                  <h3>Checklist</h3>
                  <span class="checklist-summary">${checklistItems.filter(i => i.checked).length}/${checklistItems.length} (${calculateChecklistPercentage(checklistItems)}%)</span>
                </div>
                ${!isReadOnly ? '<button type="button" class="btn btn-secondary btn-sm" id="add-checklist-item-top-btn">+ Add Item</button>' : ''}
                <div class="checklist-items" id="checklist-items">
                  ${checklistItems.map(item => `
                    <div class="checklist-item" data-item-id="${item.id}" data-item-order="${item.order}" draggable="${!isReadOnly}" ${item.created_at || item.updated_at ? `data-tooltip="Created: ${item.created_at ? formatTooltipDateTime(item.created_at) : 'Unknown'}&#10;Updated: ${item.updated_at ? formatTooltipDateTime(item.updated_at) : 'Unknown'}"` : ''}>
                      ${!isReadOnly ? '<span class="drag-handle" title="Drag to reorder">&#9776;</span>' : ''}
                      <input type="checkbox" class="checklist-checkbox" data-item-id="${item.id}" ${item.checked ? 'checked' : ''} ${disabledAttr}>
                      <span class="checklist-item-name">${linkifyUrls(this.escapeHtml(item.name))}</span>
                      ${!isReadOnly ? `<div class="checklist-item-actions">
                        <button type="button" class="checklist-edit-btn" data-item-id="${item.id}" title="Edit">✎</button>
                        <button type="button" class="checklist-delete-btn" data-item-id="${item.id}" title="Delete">🗑</button>
                      </div>` : ''}
                    </div>
                  `).join('')}
                </div>
                ${!isReadOnly ? '<button type="button" class="btn btn-secondary btn-sm" id="add-checklist-item-bottom-btn">+ Add Item</button>' : ''}
              ` : isReadOnly ? '' : `
                <div id="checklist-header-container">
                  <button type="button" class="btn btn-secondary" id="add-checklist-item-initial-btn">+ Add Checklist</button>
                </div>
                <div id="checklist-content-container" style="display: none;">
                  <div class="checklist-header">
                    <h3>Checklist</h3>
                    <span class="checklist-summary">0/0 (0%)</span>
                  </div>
                  <button type="button" class="btn btn-secondary btn-sm" id="add-checklist-item-top-btn">+ Add Item</button>
                  <div class="checklist-items" id="checklist-items"></div>
                  <button type="button" class="btn btn-secondary btn-sm" id="add-checklist-item-bottom-btn">+ Add Item</button>
                </div>
              `}
            </div>
            
            ${!isTemplate ? `
            <div class="card-metadata">
              <div class="card-metadata-item">
                <span class="card-metadata-label">Created:</span>
                <span class="card-metadata-value" ${cardData.created_at ? `data-tooltip="${formatTooltipDateTime(cardData.created_at)}" aria-label="Created on ${formatTooltipDateTime(cardData.created_at)}" tabindex="0"` : ''}>${cardData.created_at ? formatTimeAgoLong(cardData.created_at) : 'Unknown'}</span>
              </div>
              <div class="card-metadata-item">
                <span class="card-metadata-label">Updated:</span>
                <span class="card-metadata-value" id="card-updated-metadata-value" ${cardData.updated_at ? `data-tooltip="${formatTooltipDateTime(cardData.updated_at)}" aria-label="Last updated on ${formatTooltipDateTime(cardData.updated_at)}" tabindex="0"` : ''}>${cardData.updated_at ? formatTimeAgoLong(cardData.updated_at) : 'Unknown'}</span>
              </div>
              <div class="card-metadata-item" id="card-done-metadata" ${cardData.done_datetime ? '' : 'style="display:none;"'}>
                <span class="card-metadata-label">Done:</span>
                <span class="card-metadata-value" id="card-done-metadata-value" ${cardData.done_datetime ? `data-tooltip="${formatTooltipDateTime(cardData.done_datetime)}" aria-label="Marked done on ${formatTooltipDateTime(cardData.done_datetime)}" tabindex="0"` : ''}>${cardData.done_datetime ? formatTimeAgoLong(cardData.done_datetime) : ''}</span>
              </div>
              <div class="card-metadata-item" id="card-assignee-metadata">
                <span class="card-metadata-label">Assigned To:</span>
                <span class="card-metadata-value card-owner-value" id="card-primary-assignee-display">Loading…</span>
              </div>
              <div class="card-metadata-item" id="card-secondary-assignees-metadata" style="display:none;">
                <span class="card-metadata-label">Secondary Assignees:</span>
                <span class="card-metadata-value card-owner-value" id="card-secondary-assignees-display"></span>
              </div>
            </div>
            <div class="comments-section">
              <div class="comments-header">
                <h3>Comments</h3>
              </div>
              ${!isReadOnly ? `<div class="comment-input-container">
                <textarea id="new-comment-input" placeholder="Add a comment..." rows="3" maxlength="50000"></textarea>
                <button type="button" class="btn btn-primary btn-sm" id="post-comment-btn">Post Comment</button>
              </div>` : ''}
              <div class="comments-list" id="comments-list">
                ${hasComments ? comments.map(comment => this.generateCommentHtml(comment, isReadOnly)).join('') : '<p class="no-comments">No comments yet.</p>'}
              </div>
            </div>
            ` : ''}
          </form>
        </div>
      </div>
    `;

    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Get modal elements
    const modal = document.getElementById('edit-card-modal');
    const form = document.getElementById('edit-card-form');
    const cancelBtn = document.getElementById('cancel-edit-card-btn');
    const deleteBtn = document.getElementById('delete-card-detail-btn');
    const archiveBtn = document.getElementById('archive-card-detail-btn');
    const unarchiveBtn = document.getElementById('unarchive-card-detail-btn');
    const assignAssigneesBtn = document.getElementById('assign-assignees-btn');
    const viewPlannerBtn = document.getElementById('view-planner-btn');
    const titleInput = document.getElementById('edit-card-title');

    // Focus title only when editable; otherwise focus Close for accessibility.
    if (isReadOnly) {
      cancelBtn.focus();
    } else {
      titleInput.focus();
      titleInput.select();
    }

    // Track changes in title and description
    titleInput.addEventListener('input', () => {
      hasUnsavedChanges = titleInput.value.trim() !== originalTitle;
    });
    
    const descriptionInput = document.getElementById('edit-card-description');
    descriptionInput.addEventListener('input', () => {
      hasUnsavedChanges = hasUnsavedChanges || descriptionInput.value.trim() !== originalDescription;
    });

    // Keep start date, end date, and duration in sync. Whichever field was
    // just edited recalculates the missing one of the other two; if both
    // others already hold a genuine value, start date acts as the anchor
    // (start changed -> recalc end, duration changed -> recalc end,
    // end changed -> recalc duration). Clearing a field never cascades.
    //
    // Each field tracks an "isReal" flag (true only when the user directly
    // edited that field, false when we last derived it programmatically).
    // This matters because duration is split across two physical inputs
    // (days, hours): without the flag, editing days could derive a start
    // date as a side effect, and the very next edit to hours would then
    // misread that derived start as a genuine anchor instead of continuing
    // to derive it from end + duration.
    const startDateInput = document.getElementById('edit-card-start-date');
    const endDateInput = document.getElementById('edit-card-end-date');
    const durationDaysInput = document.getElementById('edit-card-duration-days');
    const durationHoursInput = document.getElementById('edit-card-duration-hours');

    let startIsReal = !!defaultStartDate;
    let endIsReal = !!defaultEndDate;
    let durationIsReal = !!initialDuration;

    const hasDurationValue = () => durationDaysInput.value !== '' || durationHoursInput.value !== '';
    const getDurationValues = () => ({
      days: parseInt(durationDaysInput.value, 10) || 0,
      hours: parseInt(durationHoursInput.value, 10) || 0
    });

    // Duration usable by the planner is either a real start+end pair, or a
    // duration typed in on its own (with no anchor date yet) - the planner
    // click-to-place flow supplies the missing start date.
    const getCurrentDurationMs = () => {
      if (startDateInput.value && endDateInput.value) {
        return new Date(endDateInput.value) - new Date(startDateInput.value);
      }
      if (hasDurationValue()) {
        const { days, hours } = getDurationValues();
        return (days * 24 + hours) * 60 * 60 * 1000;
      }
      return null;
    };

    const ONE_HOUR_MS = 60 * 60 * 1000;

    // An anchor date (start and/or end) switches the button to "View in
    // Planner" (jump to that month); with neither set, it stays "Place in
    // Planner" (placement mode), always available.
    const hasAnchorDate = () => !!startDateInput.value || !!endDateInput.value;

    // When only one of start/end is set, assume a 1 hour span so there's
    // still a date to jump to (start forward, or back from end).
    const getPlannerViewAnchorDate = () => {
      if (startDateInput.value) return new Date(startDateInput.value);
      if (endDateInput.value) return new Date(new Date(endDateInput.value).getTime() - ONE_HOUR_MS);
      return null;
    };

    const refreshViewPlannerButtonState = () => {
      if (!viewPlannerBtn) return;
      viewPlannerBtn.textContent = hasAnchorDate() ? '📅 View in Planner' : '📅 Place in Planner';
    };

    // Auto-save start/end date once at least one resolves to a real value
    // (dates are the first field migrated to save-on-update; title/
    // description still require the Save button for now). A duration typed
    // in with no anchor date yet has nothing to save - the planner
    // click-to-place flow supplies the missing start date instead.
    const autoSaveDates = async () => {
      if (!startDateInput.value && !endDateInput.value) return;
      const success = await this.updateCardDates(cardId, startDateInput.value, endDateInput.value);
      if (success) {
        cardData.start_date = startDateInput.value ? new Date(startDateInput.value).toISOString() : null;
        cardData.end_date = endDateInput.value ? new Date(endDateInput.value).toISOString() : null;
      }
    };
    const setDerivedStart = (value) => {
      startDateInput.value = value;
      startIsReal = false;
    };
    const setDerivedEnd = (value) => {
      endDateInput.value = value;
      endIsReal = false;
    };
    const setDerivedDuration = (duration) => {
      durationDaysInput.value = duration ? duration.days : '';
      durationHoursInput.value = duration ? duration.hours : '';
      durationIsReal = !!duration;
    };

    startDateInput.addEventListener('input', () => {
      hasUnsavedChanges = true;
      if (!startDateInput.value) { startIsReal = false; refreshViewPlannerButtonState(); return; }
      startIsReal = true;

      if (durationIsReal) {
        const { days, hours } = getDurationValues();
        setDerivedEnd(addDurationToLocalValue(startDateInput.value, days, hours));
      } else if (endIsReal) {
        setDerivedDuration(diffToDuration(startDateInput.value, endDateInput.value));
      }
      refreshViewPlannerButtonState();
    });

    const recalcFromDuration = () => {
      hasUnsavedChanges = true;
      if (!hasDurationValue()) { durationIsReal = false; refreshViewPlannerButtonState(); return; }
      durationIsReal = true;

      const { days, hours } = getDurationValues();
      if (startIsReal) {
        setDerivedEnd(addDurationToLocalValue(startDateInput.value, days, hours));
      } else if (endIsReal) {
        setDerivedStart(addDurationToLocalValue(endDateInput.value, -days, -hours));
      }
      refreshViewPlannerButtonState();
    };
    durationDaysInput.addEventListener('input', recalcFromDuration);
    durationHoursInput.addEventListener('input', recalcFromDuration);

    endDateInput.addEventListener('input', () => {
      hasUnsavedChanges = true;
      if (!endDateInput.value) { endIsReal = false; refreshViewPlannerButtonState(); return; }
      endIsReal = true;

      if (startIsReal) {
        setDerivedDuration(diffToDuration(startDateInput.value, endDateInput.value));
      } else if (durationIsReal) {
        const { days, hours } = getDurationValues();
        setDerivedStart(addDurationToLocalValue(endDateInput.value, -days, -hours));
      }
      refreshViewPlannerButtonState();
    });

    // Dates auto-save on update/unfocus rather than waiting for the Save
    // button (the first field migrated to this pattern).
    [startDateInput, endDateInput, durationDaysInput, durationHoursInput].forEach((input) => {
      input.addEventListener('blur', autoSaveDates);
    });

    // Helper to check for unposted comment
    const hasUnpostedComment = () => {
      const commentInput = document.getElementById('new-comment-input');
      return commentInput && commentInput.value.trim().length > 0;
    };

    // Handle assign assignees button
    if (assignAssigneesBtn) {
      assignAssigneesBtn.addEventListener('click', async () => {
        await this.openAssigneeModal(cardId);
      });
    }

    if (viewPlannerBtn) {
      viewPlannerBtn.addEventListener('click', () => {
        let render;
        if (hasAnchorDate()) {
          const anchorDate = getPlannerViewAnchorDate();
          render = (plannerView) => plannerView.renderMonth(anchorDate.getFullYear(), anchorDate.getMonth() + 1);
        } else {
          const rawDurationMs = getCurrentDurationMs();
          const durationMs = (rawDurationMs !== null && rawDurationMs > 0) ? rawDurationMs : ONE_HOUR_MS;
          render = (plannerView) => plannerView.enterPlacementMode(cardId, cardData.title, durationMs, new Date());
        }

        modal.remove();
        // Routed through the 'viewChanged' switch (rather than calling
        // plannerView directly here) so there's only ever one render firing
        // when the planner view appears - see showPlannerView().
        if (window.header && typeof window.header.setView === 'function') {
          this._pendingPlannerRender = render;
          window.header.setView('planner');
        } else {
          this.showPlannerView(render);
        }
      });
    }

    // Handle delete button
    if (deleteBtn) {
      deleteBtn.addEventListener('click', async () => {
        const cardElement = document.querySelector(`.card[data-card-id="${cardId}"]`);
        const wasDeleted = await this.deleteCard(cardId, cardElement);
        if (wasDeleted) {
          modal.remove();
        }
      });
    }

    // Load and display assignee data asynchronously.
    // Public board users are not authenticated so the assignees endpoint is not
    // accessible; assignee info is intentionally excluded from the public API.
    if (!isTemplate) {
      if (this.isPublicMode) {
        const primaryEl = document.getElementById('card-primary-assignee-display');
        if (primaryEl) primaryEl.textContent = '—';
      } else {
        this.loadCardAssigneeDisplay(cardId);
      }
    }

    // Handle archive button
    if (archiveBtn) {
      archiveBtn.addEventListener('click', async () => {
        // Get the card element for visual feedback
        const cardElement = document.querySelector(`.card[data-card-id="${cardId}"]`);
        modal.remove();
        await this.archiveCard(cardId, cardElement);
      });
    }

    // Handle unarchive button
    if (unarchiveBtn) {
      unarchiveBtn.addEventListener('click', async () => {
        // Get the card element for visual feedback
        const cardElement = document.querySelector(`.card[data-card-id="${cardId}"]`);
        modal.remove();
        await this.unarchiveCard(cardId, cardElement);
      });
    }

    // Handle done button (for agile working style)
    const doneBtn = document.getElementById('done-card-detail-btn');
    if (doneBtn) {
      doneBtn.addEventListener('click', async () => {
        const cardElement = document.querySelector(`.card[data-card-id="${cardId}"]`);
        // Toggle done status
        const newDoneStatus = !cardData.done;
        // Wait for update to complete before removing modal
        await this.updateCardDoneStatus(cardId, newDoneStatus, cardElement);
        modal.remove();
      });
    }

    // Handle edit schedule button from template modal
    const editScheduleFromTemplateBtn = document.getElementById('edit-schedule-from-template-btn');
    if (editScheduleFromTemplateBtn) {
      editScheduleFromTemplateBtn.addEventListener('click', async () => {
        // Check for unsaved changes
        if (hasUnsavedChanges || hasUnpostedComment()) {
          if (!await showConfirm('You have unsaved changes. Are you sure you want to open the schedule editor? Your changes will be lost.', 'Confirm Action')) {
            return;
          }
        }
        
        const hasSchedule = editScheduleFromTemplateBtn.getAttribute('data-has-schedule') === 'true';
        
        // Show loading state on button
        const originalText = editScheduleFromTemplateBtn.innerHTML;
        editScheduleFromTemplateBtn.disabled = true;
        editScheduleFromTemplateBtn.innerHTML = '<span style="opacity: 0.6;">Loading...</span>';
        
        try {
          // Try to open schedule modal - this will show error toast if it fails
          await this.openScheduleModal(cardId, cardData, hasSchedule);
          // Only remove edit card modal if schedule modal opened successfully
          modal.remove();
        } catch (err) {
          console.error('Error opening schedule modal:', err);
          // Re-enable button on error
          editScheduleFromTemplateBtn.disabled = false;
          editScheduleFromTemplateBtn.innerHTML = originalText;
        }
      });
    }

    // Handle schedule button
    const scheduleBtn = document.getElementById('schedule-card-btn');
    if (scheduleBtn) {
      scheduleBtn.addEventListener('click', async () => {
        // Check for unsaved changes
        if (hasUnsavedChanges || hasUnpostedComment()) {
          if (!await showConfirm('You have unsaved changes. Are you sure you want to open the schedule editor? Your changes will be lost.', 'Confirm Action')) {
            return;
          }
        }
        
        const hasSchedule = scheduleBtn.getAttribute('data-has-schedule') === 'true';
        
        // Show loading state on button
        const originalText = scheduleBtn.innerHTML;
        scheduleBtn.disabled = true;
        scheduleBtn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 4px; opacity: 0.6;"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg><span style="opacity: 0.6;">Loading...</span>';
        
        try {
          // Try to open schedule modal - this will show error toast if it fails
          await this.openScheduleModal(cardId, cardData, hasSchedule);
          // Only remove edit card modal if schedule modal opened successfully
          modal.remove();
        } catch (err) {
          console.error('Error opening schedule modal:', err);
          // Re-enable button on error
          scheduleBtn.disabled = false;
          scheduleBtn.innerHTML = originalText;
        }
      });
    }

    // Handle cancel with warning if there are unsaved changes
    let isCancelling = false;
    const handleCancel = async () => {
      // Atomic check-and-set: if already cancelling, return immediately
      if (isCancelling) return;
      isCancelling = true;
      
      // Disable cancel button immediately to prevent double-clicks
      const wasCancelDisabled = cancelBtn.disabled;
      cancelBtn.disabled = true;
      
      try {
        if (hasUnpostedComment()) {
          if (!await showConfirm('You have an unposted comment. Are you sure you want to cancel?', 'Confirm Action')) {
            // User cancelled the cancellation, re-enable button
            cancelBtn.disabled = wasCancelDisabled;
            isCancelling = false;
            return;
          }
        }
        if (hasUnsavedChanges || checklistOrderChanged) {
          if (await showConfirm('You have unsaved changes. Are you sure you want to cancel?', 'Confirm Cancellation')) {
            modal.remove();
          } else {
            // User cancelled the cancellation, re-enable button
            cancelBtn.disabled = wasCancelDisabled;
            isCancelling = false;
          }
        } else {
          modal.remove();
        }
      } catch (err) {
        // Re-enable button on error
        cancelBtn.disabled = wasCancelDisabled;
        isCancelling = false;
        console.error('Error during cancel:', err);
      }
    };
    
    cancelBtn.addEventListener('click', handleCancel);
    
    // Helper to update edit modal checklist summary
    const updateEditModalSummary = () => {
      const summaryElement = modal.querySelector('.checklist-summary');
      if (summaryElement) {
        const allCheckboxes = modal.querySelectorAll('.checklist-checkbox');
        const total = allCheckboxes.length;
        const checkedCount = Array.from(allCheckboxes).filter(cb => cb.checked).length;
        const items = Array.from(allCheckboxes).map(cb => ({ checked: cb.checked }));
        const percentage = calculateChecklistPercentage(items);
        summaryElement.textContent = `${checkedCount}/${total} (${percentage}%)`;
      }
    };

    // Handle checklist item checkbox changes (defer save until form submit)
    let checklistCheckboxChanges = new Map(); // Track checkbox changes: itemId -> checked state
    
    document.querySelectorAll('.checklist-checkbox').forEach(checkbox => {
      checkbox.addEventListener('change', (e) => {
        const itemId = parseInt(e.target.getAttribute('data-item-id'));
        const checked = e.target.checked;
        checklistCheckboxChanges.set(itemId, checked);
        hasUnsavedChanges = true;
        
        // Update the summary
        updateEditModalSummary();
      });
    });

    // Handle add checklist item buttons with inline editing
    let checklistVisible = hasChecklist;
    let pendingNewItems = []; // Track new items not yet saved
    
    const showChecklistUI = () => {
      if (!checklistVisible) {
        checklistVisible = true;
        const headerContainer = document.getElementById('checklist-header-container');
        const contentContainer = document.getElementById('checklist-content-container');
        if (headerContainer) headerContainer.style.display = 'none';
        if (contentContainer) contentContainer.style.display = 'block';
      }
    };
    
    const checklistContainer = document.getElementById('checklist-items');
    
    // Set up drag and drop once with event delegation
    this.setupChecklistDragAndDrop(cardId, () => {
      checklistOrderChanged = true;
    });
    
    // Create checklist manager for new items with event delegation
    const checklistManager = new ChecklistManager(checklistContainer, pendingNewItems, {
      updateSummary: updateEditModalSummary,
      deleteButtonClass: 'checklist-delete-btn-temp',
      onItemCommitted: () => {
        hasUnsavedChanges = true;
      },
      onItemChanged: () => {
        hasUnsavedChanges = true;
      }
    });

    const addTopBtn = document.getElementById('add-checklist-item-top-btn');
    const addBottomBtn = document.getElementById('add-checklist-item-bottom-btn');
    const addInitialBtn = document.getElementById('add-checklist-item-initial-btn');

    if (addTopBtn) {
      addTopBtn.addEventListener('click', () => {
        showChecklistUI();
        checklistManager.addItem(true);
      });
    }
    if (addBottomBtn) {
      addBottomBtn.addEventListener('click', () => {
        showChecklistUI();
        checklistManager.addItem(false);
      });
    }
    if (addInitialBtn) {
      addInitialBtn.addEventListener('click', () => {
        showChecklistUI();
        checklistManager.addItem(false);
      });
    }

    // Handle edit checklist item buttons - inline editing
    document.querySelectorAll('.checklist-edit-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const itemId = parseInt(e.target.getAttribute('data-item-id'));
        const itemElement = e.target.closest('.checklist-item');
        const nameSpan = itemElement.querySelector('.checklist-item-name');
        const currentName = nameSpan.textContent;
        
        // Replace span with input for inline editing
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'checklist-item-input';
        input.value = currentName;
        input.setAttribute('data-item-id', itemId);
        nameSpan.replaceWith(input);
        input.focus();
        input.select();
        
        // Disable dragging while editing
        itemElement.draggable = false;
        
        const saveEdit = async () => {
          const newName = input.value.trim();
          if (newName && newName !== currentName) {
            // Show saving state
            input.disabled = true;
            
            const success = await this.updateChecklistItem(itemId, { name: newName });
            
            if (success) {
              const newNameSpan = document.createElement('span');
              newNameSpan.className = 'checklist-item-name';
              newNameSpan.innerHTML = linkifyUrls(this.escapeHtml(newName));
              input.replaceWith(newNameSpan);
              hasUnsavedChanges = false; // This action was already saved
            } else {
              // Error toast already shown, restore input and re-enable
              input.disabled = false;
              input.focus();
              input.select();
              return; // Stay in edit mode to allow retry
            }
          } else if (newName) {
            // No change, just restore
            const newNameSpan = document.createElement('span');
            newNameSpan.className = 'checklist-item-name';
            newNameSpan.innerHTML = linkifyUrls(this.escapeHtml(currentName));
            input.replaceWith(newNameSpan);
          } else {
            // Empty name, restore original
            const newNameSpan = document.createElement('span');
            newNameSpan.className = 'checklist-item-name';
            newNameSpan.innerHTML = linkifyUrls(this.escapeHtml(currentName));
            input.replaceWith(newNameSpan);
          }
          // Re-enable dragging
          itemElement.draggable = true;
        };
        
        // Save on blur
        input.addEventListener('blur', () => {
          setTimeout(saveEdit, 100);
        });
        
        // Save on Enter
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            input.blur();
          } else if (e.key === 'Escape') {
            // Cancel edit
            const newNameSpan = document.createElement('span');
            newNameSpan.className = 'checklist-item-name';
            newNameSpan.textContent = currentName;
            input.replaceWith(newNameSpan);
            itemElement.draggable = true;
          }
        });
      });
    });

    // Handle delete checklist item buttons
    const createDeleteHandler = (btn) => {
      return async (e) => {
        if (await showConfirm('Delete this checklist item?', 'Confirm Deletion')) {
          const itemId = parseInt(e.target.getAttribute('data-item-id'));
          const itemElement = e.target.closest('.checklist-item');
          
          // Store item data for potential restoration
          const itemData = {
            id: itemId,
            html: itemElement.outerHTML,
            parentNode: itemElement.parentNode,
            nextSibling: itemElement.nextSibling
          };
          
          // Remove item from DOM
          itemElement.remove();
          updateEditModalSummary();
          
          // Attempt to delete from server
          const success = await this.deleteChecklistItem(itemId, cardId);
          
          if (success) {
            hasUnsavedChanges = false; // This action was already saved
            
            // Update the card in board view to reflect deletion
            const cardElement = document.querySelector(`.card[data-card-id="${cardId}"]`);
            if (cardElement) {
              const checklistElement = cardElement.querySelector('.card-checklist');
              const remainingItems = modal.querySelectorAll('.checklist-item').length;
              
              // If no items left, remove the entire checklist section
              if (remainingItems === 0 && checklistElement) {
                checklistElement.remove();
              } else if (checklistElement) {
                // Update the checklist item count and remove this specific item from board view
                const boardChecklistItem = checklistElement.querySelector(`input[data-item-id="${itemId}"]`)?.closest('.card-checklist-item');
                if (boardChecklistItem) {
                  boardChecklistItem.remove();
                }
                
                // Update summary in board view
                const summaryElement = checklistElement.querySelector('.card-checklist-summary');
                if (summaryElement) {
                  const boardCheckboxes = checklistElement.querySelectorAll('.card-checklist-checkbox');
                  const total = boardCheckboxes.length;
                  const checked = Array.from(boardCheckboxes).filter(cb => cb.checked).length;
                  const items = Array.from(boardCheckboxes).map(cb => ({ checked: cb.checked }));
                  const percentage = calculateChecklistPercentage(items);
                  summaryElement.textContent = `${checked}/${total} (${percentage}%)`;
                }
              }
            }
          } else {
            // Restore item to DOM on failure
            if (itemData.nextSibling) {
              itemData.parentNode.insertBefore(document.createRange().createContextualFragment(itemData.html).firstChild, itemData.nextSibling);
            } else {
              itemData.parentNode.appendChild(document.createRange().createContextualFragment(itemData.html).firstChild);
            }
            
            // Reattach event listeners to restored element
            const restoredElement = itemData.parentNode.querySelector(`[data-item-id="${itemId}"]`);
            if (restoredElement) {
              const deleteBtn = restoredElement.querySelector('.checklist-delete-btn');
              const editBtn = restoredElement.querySelector('.checklist-edit-btn');
              const checkbox = restoredElement.querySelector('.checklist-checkbox');
              
              // Re-attach delete handler using the factory function
              if (deleteBtn) {
                deleteBtn.addEventListener('click', createDeleteHandler(deleteBtn));
              }
              
              // Re-attach edit handler (simplified - full handler is complex, just show it's restorable)
              if (editBtn) {
                editBtn.addEventListener('click', async (e) => {
                  this.showErrorToast('Please refresh the modal to edit this item after a failed delete.');
                });
              }
              
              // Re-attach checkbox handler
              if (checkbox) {
                checkbox.addEventListener('change', (e) => {
                  const itemId = parseInt(e.target.getAttribute('data-item-id'));
                  const checked = e.target.checked;
                  checklistCheckboxChanges.set(itemId, checked);
                  hasUnsavedChanges = true;
                  updateEditModalSummary();
                });
              }
            }
            
            updateEditModalSummary();
          }
        }
      };
    };
    
    // Attach delete handlers to all delete buttons
    document.querySelectorAll('.checklist-delete-btn').forEach(btn => {
      btn.addEventListener('click', createDeleteHandler(btn));
    });

    // Handle post comment button (only if comments section exists)
    const postCommentBtn = document.getElementById('post-comment-btn');
    const newCommentInput = document.getElementById('new-comment-input');
    const MAX_COMMENT_LENGTH = 50000;
    
    if (postCommentBtn && newCommentInput) {
      postCommentBtn.addEventListener('click', async () => {
        const commentText = newCommentInput.value.trim();
        if (!commentText) return;
        
        // Validate comment length on client side
        if (commentText.length > MAX_COMMENT_LENGTH) {
          await showAlert(`Comment is too long. Maximum length is ${MAX_COMMENT_LENGTH.toLocaleString()} characters. Your comment is ${commentText.length.toLocaleString()} characters.`, 'Invalid Input');
          return;
        }
        
        // Show posting state
        postCommentBtn.disabled = true;
        postCommentBtn.textContent = 'Posting...';
        
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);
        
        try {
          const response = await fetch(`/api/cards/${cardId}/comments`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({ comment: commentText }),
            signal: controller.signal
          });
          
          clearTimeout(timeoutId);
          const data = await response.json();
          
          if (data.success) {
            // Add the new comment to the UI at the top of the list
            const commentsList = document.getElementById('comments-list');
            const noCommentsMsg = commentsList.querySelector('.no-comments');
            if (noCommentsMsg) {
              noCommentsMsg.remove();
            }
            
            const sanitizedComment = this.sanitizeCommentData(data.comment);
            const isLongComment = sanitizedComment.comment.split('\n').length > 10 || sanitizedComment.comment.length > 500;
            const newComment = this.createCommentElement(sanitizedComment);
            
            commentsList.prepend(newComment);
            
            // Attach delete handler to new comment
            const deleteBtn = newComment.querySelector('.comment-delete-btn');
            deleteBtn.addEventListener('click', () => this.deleteCommentHandler(deleteBtn, cardId));
            
            // Attach read more handler if it's a long comment
            if (isLongComment) {
              const readMoreBtn = newComment.querySelector('.comment-read-more');
              readMoreBtn.addEventListener('click', (e) => {
                const commentText = newComment.querySelector('.comment-text');
                this.toggleCommentCollapse(commentText, e.target);
              });
            }
            
            // Update card timestamp in UI
            await this.updateCardTimestamp(cardId);
            
            // Clear input and reset button
            newCommentInput.value = '';
            postCommentBtn.disabled = false;
            postCommentBtn.textContent = 'Post Comment';
          } else {
            this.showErrorToast(`Failed to post comment: ${data.message}`);
            postCommentBtn.disabled = false;
            postCommentBtn.textContent = 'Post Comment';
          }
        } catch (err) {
          clearTimeout(timeoutId);
          console.error('Error posting comment:', err);
          
          if (err.name === 'AbortError') {
            this.showErrorToast('Post comment timed out (5s). Please check your connection.');
          } else {
            this.showErrorToast(`Error posting comment: ${err.message}`);
          }
          
          postCommentBtn.disabled = false;
          postCommentBtn.textContent = 'Post Comment';
        }
      });
    }
    
    // Handle delete comment buttons (only if comments section exists)
    document.querySelectorAll('.comment-delete-btn').forEach(btn => {
      btn.addEventListener('click', () => this.deleteCommentHandler(btn, cardId));
    });
    
    // Handle read more buttons (only if comments section exists)
    document.querySelectorAll('.comment-read-more').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const commentId = e.target.getAttribute('data-comment-id');
        const commentText = document.querySelector(`.comment-text[data-comment-id="${commentId}"]`);
        this.toggleCommentCollapse(commentText, e.target);
      });
    });

    // Handle form submit
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      // Check for unposted comment
      if (hasUnpostedComment()) {
        if (!await showConfirm('You have an unposted comment. Are you sure you want to save without posting it?', 'Confirm Action')) {
          return;
        }
      }
      
      const title = titleInput.value.trim();
      const description = document.getElementById('edit-card-description').value.trim();
      const startDateValue = startDateInput.value;
      const endDateValue = endDateInput.value;
      // Save button is in modal header, not in form
      const saveBtn = modal.querySelector('button[type="submit"]');

      if (startDateValue && endDateValue && new Date(endDateValue) < new Date(startDateValue)) {
        this.showErrorToast('End date cannot be before start date');
        return;
      }

      if (title) {
        // Validate that template cards have a schedule
        if (isTemplate && !cardData.schedule) {
          const createSchedule = await showConfirm(
            'This is a template card without a schedule. Template cards need a schedule to automatically create task cards.\n\nWould you like to create a schedule for this template now?',
            'Create Schedule?'
          );
          
          if (createSchedule) {
            // Save changes first, then open schedule modal
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';
            
            const success = await this.updateCard(cardId, title, description, startDateValue, endDateValue);
            
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
            
            if (!success) {
              // Error toast already shown by updateCard
              return; // Stay in modal to allow retry
            }
            
            modal.remove();
            
            // Open schedule modal for this template
            try {
              this.openScheduleModal(cardData.id);
            } catch (err) {
              await showAlert('Failed to open the schedule modal. Please try again.\n\nError: ' + (err && err.message ? err.message : err), 'Error');
            }
            return;
          } else {
            // User chose not to create a schedule, ask if they still want to save
            const saveAnyway = await showConfirm('Save template without a schedule? (You can add a schedule later using the Edit Schedule button)', 'Confirm Action');
            if (!saveAnyway) {
              return; // Don't save, stay in modal
            }
          }
        }
        
        // Show saving state
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';
        
        let allSuccessful = true;
        
        // TODO: PERFORMANCE - Consider creating a batch endpoint PATCH /api/cards/{id}/batch that accepts
        // card updates + checklist item changes (creates, updates, deletes, reorders) in a single
        // transaction. This would:
        // - Reduce network overhead (1 request instead of N)
        // - Ensure atomicity (all changes succeed or fail together)
        // - Prevent race conditions from interleaved requests
        // - Improve performance on slow connections
        // - Use database transactions for consistency
        // - Support bulk updates (e.g., UPDATE checklist_items SET ... WHERE id IN (...))
        // Current implementation: N sequential API calls (can be slow for cards with many checklist items)
        
        // 1. Update the card
        const cardUpdateSuccess = await this.updateCard(cardId, title, description, startDateValue, endDateValue);
        if (!cardUpdateSuccess) {
          allSuccessful = false;
        }
        
        // 2. Save checkbox changes for existing items
        // PERF: Sequential updates - could be batched
        for (const [itemId, checked] of checklistCheckboxChanges.entries()) {
          const success = await this.updateChecklistItem(itemId, { checked });
          if (!success) {
            allSuccessful = false;
            // Rollback checkbox in UI
            const checkbox = modal.querySelector(`.checklist-checkbox[data-item-id="${itemId}"]`);
            if (checkbox) {
              checkbox.checked = !checked;
            }
          }
        }
        
        // 3. Save any pending new checklist items in their current DOM order
        const checklistContainer = document.getElementById('checklist-items');
        const allItems = Array.from(checklistContainer.querySelectorAll('.checklist-item'));
        
        for (let i = 0; i < allItems.length; i++) {
          const el = allItems[i];
          const tempId = el.getAttribute('data-temp-id');
          
          // Check if this is a pending new item
          if (tempId) {
            const pendingItem = pendingNewItems.find(item => item.tempId === Number(tempId));
            if (pendingItem && pendingItem.name) {
              // Save with the current position index and checked state
              const success = await this.createChecklistItem(cardId, pendingItem.name, i, pendingItem.checked);
              if (!success) {
                allSuccessful = false;
                // Mark the item as failed (keep it in UI so user can retry)
                el.classList.add('update-failed');
              }
            }
          }
        }
        
        // 4. Update order for existing items if changed
        // PERF: Sequential updates - could use bulk update endpoint
        if (checklistOrderChanged) {
          for (let i = 0; i < allItems.length; i++) {
            const el = allItems[i];
            const itemId = el.getAttribute('data-item-id');
            if (itemId && itemId !== 'null') {
              const success = await this.updateChecklistItem(parseInt(itemId), { order: i });
              if (!success) {
                allSuccessful = false;
              }
            }
          }
        }
        
        // Re-enable save button
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
        
        // Reload board if card update succeeded, even if checklist operations failed
        // This ensures the card title/description changes are visible
        if (cardUpdateSuccess || allSuccessful) {
          await this.loadBoard();
        }
        
        if (allSuccessful) {
          hasUnsavedChanges = false;
          checklistOrderChanged = false;
          checklistCheckboxChanges.clear();
          modal.remove();
        } else {
          // Some operations failed - stay in modal for retry
          // Clear the checkbox changes that succeeded so they won't be retried
          for (const [itemId, checked] of checklistCheckboxChanges.entries()) {
            const checkbox = modal.querySelector(`.checklist-checkbox[data-item-id="${itemId}"]`);
            if (checkbox && checkbox.checked === checked) {
              // This one succeeded, remove from pending changes
              checklistCheckboxChanges.delete(itemId);
            }
          }
          
          // Show appropriate message based on what succeeded
          if (cardUpdateSuccess) {
            this.showErrorToast('Card updated, but some checklist changes failed. Please review and try again.');
          } else {
            this.showErrorToast('Failed to save changes. Please try again.');
          }
        }
      }
    });

    // Close modal on background click with warning (ignore text selection drags)
    setupModalBackgroundClose(modal, handleCancel);
    setupModalEscapeClose(modal, handleCancel);
  }

  async getCardData(cardId) {
    // Fetch single card data from dedicated endpoint
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    const url = this.isPublicMode
      ? `/api/public/boards/${encodeURIComponent(this.publicSlug)}/cards/${cardId}`
      : `/api/cards/${cardId}`;

    try {
      const response = await fetch(url, {
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      const data = await response.json();
      
      if (data.success) {
        return data.card;
      } else {
        console.error('Failed to get card data:', data.message);
        this.showErrorToast(`Failed to load card: ${data.message}`);
        return null;
      }
    } catch (err) {
      clearTimeout(timeoutId);
      console.error('Error getting card data:', err.message);
      
      if (err.name === 'AbortError') {
        this.showErrorToast('Load card timed out (5s). Please check your connection.');
      } else {
        this.showErrorToast(`Error loading card: ${err.message}`);
      }
      return null;
    }
  }

  async updateCardTimestamp(cardId) {
    // Fetch updated card data and update timestamps in UI
    const cardData = await this.getCardData(cardId);
    if (!cardData) return;

    // Update the timestamp in the card edit modal if it's open for this card
    const modalCardId = document.getElementById('edit-card-modal')?.getAttribute('data-card-id');
    if (modalCardId && parseInt(modalCardId) === cardId) {
      // Update the updated_at metadata in the modal
      const updatedMetadataValue = document.getElementById('card-updated-metadata-value');
      if (updatedMetadataValue) {
        if (cardData.updated_at) {
          updatedMetadataValue.textContent = formatTimeAgoLong(cardData.updated_at);
          updatedMetadataValue.setAttribute('data-tooltip', formatTooltipDateTime(cardData.updated_at));
          updatedMetadataValue.setAttribute('aria-label', `Last updated on ${formatTooltipDateTime(cardData.updated_at)}`);
          updatedMetadataValue.setAttribute('tabindex', '0');
        } else {
          updatedMetadataValue.textContent = 'Unknown';
          updatedMetadataValue.removeAttribute('data-tooltip');
          updatedMetadataValue.removeAttribute('aria-label');
          updatedMetadataValue.removeAttribute('tabindex');
        }
      }

      const doneMetadataRow = document.getElementById('card-done-metadata');
      const doneMetadataValue = document.getElementById('card-done-metadata-value');
      if (doneMetadataRow && doneMetadataValue) {
        if (cardData.done_datetime) {
          doneMetadataRow.style.display = '';
          doneMetadataValue.textContent = formatTimeAgoLong(cardData.done_datetime);
          doneMetadataValue.setAttribute('data-tooltip', formatTooltipDateTime(cardData.done_datetime));
          doneMetadataValue.setAttribute('aria-label', `Marked done on ${formatTooltipDateTime(cardData.done_datetime)}`);
          doneMetadataValue.setAttribute('tabindex', '0');
        } else {
          doneMetadataRow.style.display = 'none';
          doneMetadataValue.textContent = '';
          doneMetadataValue.removeAttribute('data-tooltip');
          doneMetadataValue.removeAttribute('aria-label');
          doneMetadataValue.removeAttribute('tabindex');
        }
      }
    }

    // Update the timestamp on the card itself on the board
    const cardElement = document.querySelector(`.card[data-card-id="${cardId}"]`);
    if (cardElement) {
      const timestampElement = cardElement.querySelector('.card-timestamp');
      if (cardData.updated_at) {
        if (timestampElement) {
          // Update existing timestamp
          timestampElement.textContent = formatTimeAgo(cardData.updated_at);
          timestampElement.setAttribute('data-tooltip', formatTooltipDateTime(cardData.updated_at));
          timestampElement.setAttribute('aria-label', `Last updated ${formatTooltipDateTime(cardData.updated_at)}`);
        } else {
          // Create timestamp element if it doesn't exist
          // First check if card-meta-row exists
          let metaRow = cardElement.querySelector('.card-meta-row');
          if (!metaRow) {
            // Create the meta row structure
            const cardContentWrapper = cardElement.querySelector('.card-content-wrapper');
            const checklistElement = cardElement.querySelector('.card-checklist');
            if (cardContentWrapper) {
              metaRow = document.createElement('div');
              metaRow.className = 'card-meta-row';
              // Insert before checklist or at the end of content wrapper
              if (checklistElement) {
                cardContentWrapper.insertBefore(metaRow, checklistElement);
              } else {
                cardContentWrapper.appendChild(metaRow);
              }
            }
          }
          
          if (metaRow) {
            // Create and append timestamp element to the meta row
            const timestamp = document.createElement('div');
            timestamp.className = 'card-timestamp';
            timestamp.setAttribute('data-tooltip', formatTooltipDateTime(cardData.updated_at));
            timestamp.setAttribute('aria-label', `Last updated ${formatTooltipDateTime(cardData.updated_at)}`);
            timestamp.setAttribute('tabindex', '0');
            timestamp.textContent = formatTimeAgo(cardData.updated_at);
            metaRow.appendChild(timestamp);
          }
        }
      }
    }
  }

  async createChecklistItem(cardId, name, order = null, checked = false) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    
    try {
      const body = { name, checked };
      if (order !== null) {
        body.order = order;
      }
      
      const response = await fetch(`/api/cards/${cardId}/checklist-items`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(body),
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      const data = await response.json();

      if (!data.success) {
        this.showErrorToast(`Failed to create checklist item: ${data.message}`);
        return false;
      }
      // Update card timestamp in UI
      await this.updateCardTimestamp(cardId);
      return true;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        this.showErrorToast('Create checklist item timed out (5s). Please check your connection.');
      } else {
        this.showErrorToast(`Error creating checklist item: ${err.message}`);
      }
      return false;
    }
  }

  async updateChecklistItem(itemId, updates) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    
    try {
      const response = await fetch(`/api/checklist-items/${itemId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(updates),
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      const data = await response.json();

      if (!data.success) {
        this.showErrorToast(`Failed to update checklist item: ${data.message}`);
        return false;
      }
      // Update card timestamp in UI - extract cardId from DOM
      const modalCardId = document.getElementById('edit-card-modal')?.getAttribute('data-card-id');
      if (modalCardId) {
        await this.updateCardTimestamp(parseInt(modalCardId));
      }
      return true;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        this.showErrorToast('Update checklist item timed out (5s). Please check your connection.');
      } else {
        this.showErrorToast(`Error updating checklist item: ${err.message}`);
      }
      return false;
    }
  }

  async deleteChecklistItem(itemId, cardId = null) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    
    try {
      const response = await fetch(`/api/checklist-items/${itemId}`, {
        method: 'DELETE',
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      const data = await response.json();

      if (!data.success) {
        this.showErrorToast(`Failed to delete checklist item: ${data.message}`);
        return false;
      }
      // Update card timestamp in UI
      if (cardId) {
        await this.updateCardTimestamp(cardId);
      } else {
        // Get cardId from modal if not provided
        const modalCardId = document.getElementById('edit-card-modal')?.getAttribute('data-card-id');
        if (modalCardId) {
          await this.updateCardTimestamp(parseInt(modalCardId));
        }
      }
      return true;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        this.showErrorToast('Delete checklist item timed out (5s). Please check your connection.');
      } else {
        this.showErrorToast(`Error deleting checklist item: ${err.message}`);
      }
      return false;
    }
  }

  async updateCardDates(cardId, startDate, endDate) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const response = await fetch(`/api/cards/${cardId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          start_date: startDate ? new Date(startDate).toISOString() : null,
          end_date: endDate ? new Date(endDate).toISOString() : null
        }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      const data = await response.json();

      if (data.success) {
        this.refreshPlannerIfVisible();
        return true;
      }
      this.showErrorToast(`Failed to save dates: ${data.message}`);
      return false;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        this.showErrorToast('Save dates timed out (5s). Please check your connection.');
      } else {
        this.showErrorToast(`Error saving dates: ${err.message}`);
      }
      return false;
    }
  }

  async updateCard(cardId, title, description, startDate = undefined, endDate = undefined) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const response = await fetch(`/api/cards/${cardId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          title,
          description,
          start_date: startDate ? new Date(startDate).toISOString() : null,
          end_date: endDate ? new Date(endDate).toISOString() : null
        }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      const data = await response.json();

      if (data.success) {
        // The server broadcasts card_updated to other clients via WebSocket.
        // For the originating client, we return true immediately since the API
        // request itself confirms the update succeeded. The client should reload
        // the board if needed.
        this.refreshPlannerIfVisible();
        return true;
      } else {
        this.showErrorToast(`Failed to update card: ${data.message}`);
        return false;
      }
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        this.showErrorToast('Update card timed out (5s). Please check your connection.');
      } else {
        this.showErrorToast(`Error updating card: ${err.message}`);
      }
      return false;
    }
  }

  async deleteCard(cardId, cardElement = null) {
    if (!await showConfirm('Are you sure you want to delete this card?', 'Confirm Deletion')) {
      return false;
    }

    // Show loading state
    if (cardElement) {
      cardElement.classList.add('updating');
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const response = await fetch(`/api/cards/${cardId}`, {
        method: 'DELETE',
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      const data = await response.json();

      if (data.success) {
        // The server broadcasts card_deleted to other clients via WebSocket.
        // For the originating client, we reload the board immediately below
        // to ensure instant UI update and remove the card element.
        
        // Reload board to reflect deletion
        await this.loadBoard();
        this.refreshPlannerIfVisible();
        return true;
      } else {
        if (cardElement) {
          cardElement.classList.remove('updating');
        }
        this.showErrorToast(`Failed to delete card: ${data.message}`);
        return false;
      }
    } catch (err) {
      clearTimeout(timeoutId);
      if (cardElement) {
        cardElement.classList.remove('updating');
      }
      
      if (err.name === 'AbortError') {
        this.showErrorToast('Delete card timed out (5s). Please check your connection.');
      } else {
        this.showErrorToast(`Error deleting card: ${err.message}`);
      }
      return false;
    }
  }

  async archiveCard(cardId, cardElement = null) {
    // Show loading state after delay to avoid flashing on fast connections
    const loadingTimeout = setTimeout(() => {
      if (cardElement) {
        cardElement.classList.add('updating');
      }
    }, 500);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const response = await fetch(`/api/cards/${cardId}/archive`, {
        method: 'PATCH',
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      const data = await response.json();

      if (data.success) {
        clearTimeout(loadingTimeout);
        // Reload board to reflect archiving
        await this.loadBoard();
        this.refreshPlannerIfVisible();
      } else {
        clearTimeout(loadingTimeout);
        if (cardElement) {
          cardElement.classList.remove('updating');
        }
        this.showErrorToast(`Failed to archive card: ${data.message}`);
      }
    } catch (err) {
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      if (cardElement) {
        cardElement.classList.remove('updating');
      }
      
      if (err.name === 'AbortError') {
        this.showErrorToast('Archive card timed out (5s). Please check your connection.');
      } else {
        this.showErrorToast(`Error archiving card: ${err.message}`);
      }
    }
  }

  async unarchiveCard(cardId, cardElement = null) {
    // Show loading state after delay to avoid flashing on fast connections
    const loadingTimeout = setTimeout(() => {
      if (cardElement) {
        cardElement.classList.add('updating');
      }
    }, 500);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const response = await fetch(`/api/cards/${cardId}/unarchive`, {
        method: 'PATCH',
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      const data = await response.json();

      if (data.success) {
        // Reload board to reflect unarchiving
        await this.loadBoard();
        this.refreshPlannerIfVisible();
      } else {
        if (cardElement) {
          cardElement.classList.remove('updating');
        }
        this.showErrorToast(`Failed to unarchive card: ${data.message}`);
      }
    } catch (err) {
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      if (cardElement) {
        cardElement.classList.remove('updating');
      }
      
      if (err.name === 'AbortError') {
        this.showErrorToast('Unarchive card timed out (5s). Please check your connection.');
      } else {
        this.showErrorToast(`Error unarchiving card: ${err.message}`);
      }
    }
  }

  async updateCardDoneStatus(cardId, done, cardElement = null) {
    // Show loading state after delay to avoid flashing on fast connections
    const loadingTimeout = setTimeout(() => {
      if (cardElement) {
        cardElement.classList.add('updating');
      }
    }, 500);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const response = await fetch(`/api/cards/${cardId}/done`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ done: done }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      
      const data = await response.json();

      if (response.ok && data.success) {
        // Show success message
        const statusText = done ? 'Card marked as done' : 'Card marked as not done';
        this.showSuccessToast(statusText, 2000);
        
        // If in agile mode, reload the board so the card appears/disappears based on done status
        if (this.workingStyle === 'agile') {
          await this.loadBoard();
        } else {
          // For kanban mode, just update the button
          if (cardElement) {
            cardElement.setAttribute('data-done', done);
            
            // Update the button appearance
            const btn = cardElement.querySelector('.card-done-btn');
            if (btn) {
              btn.textContent = done ? '✓' : '○';
              btn.setAttribute('title', done ? 'Mark as not done' : 'Mark as done');
            }
            
            cardElement.classList.remove('updating');
          }
        }
      } else {
        if (cardElement) {
          cardElement.classList.remove('updating');
        }
        const errorMsg = data.message || `Server error: ${response.status}`;
        this.showErrorToast(`Failed to update card status: ${errorMsg}`);
      }
    } catch (err) {
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      if (cardElement) {
        cardElement.classList.remove('updating');
      }
      
      if (err.name === 'AbortError') {
        this.showErrorToast('Update card status timed out (5s). Please check your connection.');
      } else {
        this.showErrorToast(`Error updating card status: ${err.message}`);
      }
    }
  }

  setupChecklistDragAndDrop(cardId, onOrderChange) {
    const container = document.getElementById('checklist-items');
    this._setupChecklistDragAndDropInternal(container, { onOrderChange });
  }

  setupNewCardChecklistDragAndDrop(container, pendingChecklistItems) {
    this._setupChecklistDragAndDropInternal(container, { pendingChecklistItems });
  }

  /**
   * Internal method to set up drag-and-drop for checklist items.
   * Supports two modes:
   * 1. Edit mode: Pass onOrderChange callback to be notified of reordering
   * 2. New card mode: Pass pendingChecklistItems array to keep in sync with DOM order
   */
  _setupChecklistDragAndDropInternal(container, options = {}) {
    const { onOrderChange, pendingChecklistItems } = options;
    
    // Use a flag to track if we've already set up listeners on this container
    if (container._dragListenersSetup) return;
    container._dragListenersSetup = true;

    let draggedElement = null;

    // Event delegation for drag events
    container.addEventListener('dragstart', (e) => {
      if (e.target.classList.contains('checklist-item')) {
        draggedElement = e.target;
        e.target.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
      }
    });

    container.addEventListener('dragend', (e) => {
      if (e.target.classList.contains('checklist-item')) {
        e.target.classList.remove('dragging');
        
        // Handle order change based on mode
        if (onOrderChange) {
          // Edit mode: notify that order changed (will be saved on form submit)
          onOrderChange();
        } else if (pendingChecklistItems) {
          // New card mode: update pendingChecklistItems array to match new DOM order
          const allItems = Array.from(container.querySelectorAll('.checklist-item'));
          const newOrder = allItems.map(el => {
            const tempId = Number(el.getAttribute('data-temp-id'));
            return pendingChecklistItems.find(i => i.tempId === tempId);
          }).filter(Boolean);
          
          // Update the array in place
          pendingChecklistItems.length = 0;
          pendingChecklistItems.push(...newOrder);
        }
        
        draggedElement = null;
      }
    });

    container.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      
      const afterElement = this.getChecklistDragAfterElement(container, e.clientY);
      
      if (draggedElement && afterElement === null) {
        container.appendChild(draggedElement);
      } else if (draggedElement) {
        container.insertBefore(draggedElement, afterElement);
      }
    });
  }

  getChecklistDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.checklist-item:not(.dragging)')];
    
    return draggableElements.reduce((closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      
      if (offset < 0 && offset > closest.offset) {
        return { offset: offset, element: child };
      } else {
        return closest;
      }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
  }

  showError(message) {
    this.container.innerHTML = `
      <div class="empty-board">
        <div class="empty-board-icon">⚠️</div>
        <h3>Error</h3>
        <p>${this.escapeHtml(message)}</p>
        <button class="btn btn-secondary" onclick="window.location.href='/'">← Back to Boards</button>
      </div>
    `;
  }

  showBoardLoading() {
    if (this.boardLoadingDelayTimeoutId) {
      return;
    }

    this.boardLoadingDelayTimeoutId = setTimeout(() => {
      this.boardLoadingDelayTimeoutId = null;

      // Add or show loading overlay
      let overlay = this.container.querySelector('.board-loading-overlay');
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'board-loading-overlay';
        overlay.innerHTML = `
          <div class="board-loading-content">
            <div class="board-loading-text">Board data is loading...</div>
          </div>
        `;
        this.container.appendChild(overlay);
      }
      overlay.style.display = 'flex';
    }, BOARD_LOADING_OVERLAY_DELAY_MS);
  }

  hideBoardLoading() {
    if (this.boardLoadingDelayTimeoutId) {
      clearTimeout(this.boardLoadingDelayTimeoutId);
      this.boardLoadingDelayTimeoutId = null;
    }

    const overlay = this.container.querySelector('.board-loading-overlay');
    if (overlay) {
      overlay.style.display = 'none';
    }
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  getInitials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return '?';

    let rawInitials;
    if (parts.length === 1) {
      rawInitials = parts[0].slice(0, 2);
    } else {
      rawInitials = `${parts[0][0]}${parts[parts.length - 1][0]}`;
    }

    const safeInitials = rawInitials
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, '');

    return safeInitials || '?';
  }

  toggleCommentCollapse(commentText, button) {
    if (commentText.classList.contains('collapsed')) {
      commentText.classList.remove('collapsed');
      button.textContent = 'Read less';
      button.setAttribute('aria-expanded', 'true');
    } else {
      commentText.classList.add('collapsed');
      button.textContent = 'Read more...';
      button.setAttribute('aria-expanded', 'false');
    }
  }

  formatCommentDate(dateString) {
    if (!dateString) return '';
    
    // Parse the date string - assumes ISO 8601 format from server
    // The Date constructor automatically handles timezone conversion to local time
    const date = new Date(dateString);
    const now = new Date();
    
    // Calculate difference in milliseconds
    // Both dates are in local timezone, so comparison is accurate
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    // Return relative time for recent comments
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins} minute${diffMins === 1 ? '' : 's'} ago`;
    if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`;
    if (diffDays < 7) return `${diffDays} day${diffDays === 1 ? '' : 's'} ago`;
    
    // Format as date/time for older comments (day/month/year format)
    const dateOptions = { day: 'numeric', month: 'short', year: 'numeric' };
    return date.toLocaleDateString('en-GB', dateOptions) + ' ' + formatTimeSync(date);
  }

  /**
  * Load and display assignee data in the edit card modal metadata section.
   * @param {number} cardId
   */
  async loadCardAssigneeDisplay(cardId) {
    const primaryEl = document.getElementById('card-primary-assignee-display');
    const secondaryRow = document.getElementById('card-secondary-assignees-metadata');
    const secondaryEl = document.getElementById('card-secondary-assignees-display');
    if (!primaryEl) return;
    try {
      const resp = await fetch(`/api/cards/${cardId}/assignees`);
      if (!resp.ok) throw new Error('Failed to load assignees');
      const data = await resp.json();
      const formatUser = (u) => u.display_name || u.username || 'Unknown user';
      primaryEl.textContent = data.primary_assignee ? formatUser(data.primary_assignee) : 'Unassigned';
      if (data.secondary_assignees && data.secondary_assignees.length > 0) {
        secondaryEl.textContent = data.secondary_assignees.map(formatUser).join(', ');
        if (secondaryRow) secondaryRow.style.display = '';
      } else {
        if (secondaryRow) secondaryRow.style.display = 'none';
      }
    } catch (e) {
      if (primaryEl) primaryEl.textContent = '—';
    }
  }

  /**
  * Open a modal for assigning primary and secondary assignees of a card.
   * @param {number} cardId
   */
  async openAssigneeModal(cardId) {
    // Remove any existing assignee modal
    const existing = document.getElementById('assignee-modal');
    if (existing) existing.remove();

    // Load current assignees and available users
    let ownersData;
    try {
      const resp = await fetch(`/api/cards/${cardId}/assignees`);
      if (!resp.ok) throw new Error('Failed to load assignees');
      ownersData = await resp.json();
    } catch (e) {
      this.showErrorToast('Failed to load assignee data. Please try again.');
      return;
    }

    const { primary_assignee, secondary_assignees, available_users } = ownersData;
    const sanitizedPrimaryAssignee = primary_assignee ? this.sanitizeAssigneeUser(primary_assignee) : null;
    const sanitizedSecondaryAssignees = (secondary_assignees || []).map((user) => this.sanitizeAssigneeUser(user));
    const sanitizedAvailableUsers = (available_users || []).map((user) => this.sanitizeAssigneeUser(user));
    const primaryId = sanitizedPrimaryAssignee ? String(sanitizedPrimaryAssignee.id) : '';
    const secondaryIds = new Set(sanitizedSecondaryAssignees.map(u => u.id));

    const formatUser = (u) => u.displayName;

    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.id = 'assignee-modal';

    const modalContent = document.createElement('div');
    modalContent.className = 'modal-content assignee-modal-content';

    const modalHeader = document.createElement('div');
    modalHeader.className = 'modal-header';

    const headerActions = document.createElement('div');
    headerActions.className = 'modal-header-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn btn-secondary';
    cancelBtn.id = 'owner-modal-cancel-btn';
    cancelBtn.textContent = 'Cancel';

    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'btn btn-primary';
    saveBtn.id = 'owner-modal-save-btn';
    saveBtn.textContent = 'Save';

    headerActions.append(cancelBtn, saveBtn);

    const title = document.createElement('h2');
    title.textContent = 'Assign To';
    modalHeader.append(headerActions, title);

    const primarySection = document.createElement('div');
    primarySection.className = 'form-group assignee-modal-section';
    const primaryLabel = document.createElement('label');
    primaryLabel.textContent = 'Assigned To:';
    const primaryGrid = document.createElement('div');
    primaryGrid.className = 'primary-assignee-grid';
    primaryGrid.setAttribute('role', 'group');
    primaryGrid.setAttribute('aria-label', 'Select primary assignee');

    const secondarySection = document.createElement('div');
    secondarySection.className = 'form-group assignee-modal-section';
    const secondaryLabel = document.createElement('label');
    secondaryLabel.textContent = 'Secondary Assignees:';
    const secondaryGrid = document.createElement('div');
    secondaryGrid.className = 'secondary-assignee-grid';
    secondaryGrid.id = 'secondary-assignees-list';
    secondaryGrid.setAttribute('role', 'group');
    secondaryGrid.setAttribute('aria-label', 'Toggle secondary assignees');

    primaryGrid.appendChild(this.createAssigneeOptionButton({
      className: 'primary-assignee-option',
      userId: '',
      selected: primaryId === '',
      label: 'Unassigned',
      initials: '-',
      unassigned: true
    }));

    sanitizedAvailableUsers.forEach((user) => {
      primaryGrid.appendChild(this.createAssigneeOptionButton({
        className: 'primary-assignee-option',
        userId: String(user.id),
        selected: String(user.id) === primaryId,
        label: formatUser(user),
        initials: this.getInitials(formatUser(user)),
        profileColour: user.profileColour
      }));

      secondaryGrid.appendChild(this.createAssigneeOptionButton({
        className: 'secondary-assignee-option',
        userId: String(user.id),
        selected: secondaryIds.has(user.id),
        label: formatUser(user),
        initials: this.getInitials(formatUser(user)),
        profileColour: user.profileColour
      }));
    });

    if (secondaryGrid.childElementCount === 0) {
      const emptyState = document.createElement('p');
      emptyState.className = 'assignee-modal-empty-state';
      emptyState.textContent = 'No eligible users found.';
      secondaryGrid.appendChild(emptyState);
    }

    primarySection.append(primaryLabel, primaryGrid);
    secondarySection.append(secondaryLabel, secondaryGrid);
    modalContent.append(modalHeader, primarySection, secondarySection);
    modal.appendChild(modalContent);
    document.body.appendChild(modal);

    setupModalBackgroundClose(modal, () => modal.remove());
    cancelBtn.addEventListener('click', () => modal.remove());

    const primaryButtons = modal.querySelectorAll('.primary-assignee-option');
    const secondaryButtons = modal.querySelectorAll('.secondary-assignee-option');

    const syncSecondaryDisabledState = () => {
      const selectedPrimary = modal.querySelector('.primary-assignee-option.selected');
      const selectedPrimaryId = selectedPrimary ? selectedPrimary.dataset.userId : '';

      secondaryButtons.forEach((secondaryButton) => {
        const shouldDisable = selectedPrimaryId !== '' && secondaryButton.dataset.userId === selectedPrimaryId;
        secondaryButton.disabled = shouldDisable;
        secondaryButton.setAttribute('aria-disabled', shouldDisable ? 'true' : 'false');

        if (shouldDisable) {
          secondaryButton.classList.remove('selected');
          secondaryButton.setAttribute('aria-pressed', 'false');
        }
      });
    };

    primaryButtons.forEach((button) => {
      button.addEventListener('click', () => {
        primaryButtons.forEach((candidate) => {
          const isSelected = candidate === button;
          candidate.classList.toggle('selected', isSelected);
          candidate.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
        });

        syncSecondaryDisabledState();
      });
    });

    secondaryButtons.forEach((button) => {
      button.addEventListener('click', () => {
        if (button.disabled) {
          return;
        }

        const isSelected = !button.classList.contains('selected');
        button.classList.toggle('selected', isSelected);
        button.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
      });
    });

    syncSecondaryDisabledState();

    saveBtn.addEventListener('click', async () => {
      const selectedPrimary = modal.querySelector('.primary-assignee-option.selected');
      const primaryOwnerIdRaw = selectedPrimary ? selectedPrimary.dataset.userId : '';
      const primaryOwnerId = primaryOwnerIdRaw === '' ? null : parseInt(primaryOwnerIdRaw, 10);

      const selectedSecondary = modal.querySelectorAll('.secondary-assignee-option.selected');
      const secondaryAssigneeIds = Array.from(selectedSecondary)
        .map(button => parseInt(button.dataset.userId, 10))
        .filter(id => !Number.isNaN(id));

      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';

      try {
        const resp = await fetch(`/api/cards/${cardId}/assignees`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ assigned_to_id: primaryOwnerId, secondary_assignee_ids: secondaryAssigneeIds }),
        });
        const result = await resp.json();
        if (!resp.ok || !result.success) {
          throw new Error(result.message || 'Failed to save assignees');
        }
        modal.remove();
        // Refresh owner display in the edit card modal
        this.loadCardAssigneeDisplay(cardId);
      } catch (e) {
        this.showErrorToast(e.message || 'Failed to save assignees. Please try again.');
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
      }
    });
  }

  generateCommentHtml(comment, isReadOnly = false) {
    const isLongComment = comment.comment.split('\n').length > 10 || comment.comment.length > 500;
    return `
      <div class="comment-item" data-comment-id="${comment.id}">
        <div class="comment-header">
          <span class="comment-date" data-tooltip="${formatTooltipDateTime(comment.created_at)}" aria-label="Created on ${formatTooltipDateTime(comment.created_at)}" tabindex="0">${this.formatCommentDate(comment.created_at)}</span>
          ${!isReadOnly ? `<button type="button" class="comment-delete-btn" data-comment-id="${comment.id}" title="Delete" aria-label="Delete comment">🗑</button>` : ''}
        </div>
        <div class="comment-text ${isLongComment ? 'collapsed' : ''}" id="comment-text-${comment.id}" data-comment-id="${comment.id}">${linkifyUrls(this.escapeHtml(comment.comment))}</div>
        ${isLongComment ? `<button type="button" class="comment-read-more" data-comment-id="${comment.id}" aria-expanded="false" aria-controls="comment-text-${comment.id}" aria-label="Expand comment">Read more...</button>` : ''}
      </div>
    `;
  }

  createCommentElement(comment, isReadOnly = false) {
    const isLongComment = comment.comment.split('\n').length > 10 || comment.comment.length > 500;
    const commentItem = document.createElement('div');
    commentItem.className = 'comment-item';
    commentItem.setAttribute('data-comment-id', String(comment.id));

    const commentHeader = document.createElement('div');
    commentHeader.className = 'comment-header';

    const commentDate = document.createElement('span');
    commentDate.className = 'comment-date';
    commentDate.setAttribute('data-tooltip', formatTooltipDateTime(comment.created_at));
    commentDate.setAttribute('aria-label', `Created on ${formatTooltipDateTime(comment.created_at)}`);
    commentDate.setAttribute('tabindex', '0');
    commentDate.textContent = this.formatCommentDate(comment.created_at);
    commentHeader.appendChild(commentDate);

    if (!isReadOnly) {
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'comment-delete-btn';
      deleteBtn.setAttribute('data-comment-id', String(comment.id));
      deleteBtn.title = 'Delete';
      deleteBtn.setAttribute('aria-label', 'Delete comment');
      deleteBtn.textContent = '🗑';
      commentHeader.appendChild(deleteBtn);
    }

    const commentText = document.createElement('div');
    commentText.className = `comment-text${isLongComment ? ' collapsed' : ''}`;
    commentText.id = `comment-text-${comment.id}`;
    commentText.setAttribute('data-comment-id', String(comment.id));
    appendLinkifiedText(commentText, comment.comment);

    commentItem.append(commentHeader, commentText);

    if (isLongComment) {
      const readMoreBtn = document.createElement('button');
      readMoreBtn.type = 'button';
      readMoreBtn.className = 'comment-read-more';
      readMoreBtn.setAttribute('data-comment-id', String(comment.id));
      readMoreBtn.setAttribute('aria-expanded', 'false');
      readMoreBtn.setAttribute('aria-controls', `comment-text-${comment.id}`);
      readMoreBtn.setAttribute('aria-label', 'Expand comment');
      readMoreBtn.textContent = 'Read more...';
      commentItem.appendChild(readMoreBtn);
    }

    return commentItem;
  }

  createAssigneeOptionButton({ className, userId, selected, label, initials, profileColour, unassigned = false }) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `${className}${selected ? ' selected' : ''}`;
    button.setAttribute('data-user-id', String(userId));
    button.setAttribute('aria-pressed', selected ? 'true' : 'false');

    const avatarChip = document.createElement('span');
    avatarChip.className = `user-avatar-chip${unassigned ? ' unassigned-chip' : ''}`;
    if (!unassigned) {
      avatarChip.style.backgroundColor = this.sanitizeProfileColour(profileColour);
    }
    avatarChip.textContent = this.sanitizePlainText(initials);

    const nameSpan = document.createElement('span');
    nameSpan.className = 'primary-assignee-name';
    nameSpan.textContent = this.sanitizePlainText(label);

    button.append(avatarChip, nameSpan);
    return button;
  }

  sanitizePlainText(text) {
    return String(text ?? '').replace(/[\u0000-\u001F\u007F]/g, '');
  }

  sanitizeProfileColour(colour) {
    const normalized = typeof colour === 'string' ? colour.trim() : '';
    if (!normalized) {
      return '#90A4AE';
    }

    if (typeof CSS !== 'undefined' && typeof CSS.supports === 'function' && CSS.supports('color', normalized)) {
      return normalized;
    }

    return '#90A4AE';
  }

  sanitizeCommentData(comment) {
    return {
      id: Number.parseInt(comment?.id, 10) || 0,
      created_at: this.sanitizePlainText(comment?.created_at),
      comment: this.sanitizePlainText(comment?.comment)
    };
  }

  sanitizeAssigneeUser(user) {
    const displayName = this.sanitizePlainText(user?.display_name || user?.username || 'Unknown user');
    return {
      id: Number.parseInt(user?.id, 10) || 0,
      displayName,
      profileColour: this.sanitizeProfileColour(user?.profile_colour)
    };
  }

  async deleteCommentHandler(deleteBtn, cardId) {
    const commentId = parseInt(deleteBtn.getAttribute('data-comment-id'));
    
    if (!await showConfirm('Are you sure you want to delete this comment?', 'Confirm Deletion')) {
      return;
    }
    
    try {
      const response = await fetch(`/api/comments/${commentId}`, {
        method: 'DELETE'
      });
      
      const data = await response.json();
      
      if (data.success) {
        // Remove comment from UI
        const commentItem = deleteBtn.closest('.comment-item');
        commentItem.remove();
        
        // If no comments left, show "no comments" message
        const commentsList = document.getElementById('comments-list');
        if (commentsList && commentsList.querySelectorAll('.comment-item').length === 0) {
          commentsList.innerHTML = '<p class="no-comments">No comments yet.</p>';
        }
        
        // Update card timestamp in UI
        await this.updateCardTimestamp(cardId);
      } else {
        await showAlert('Failed to delete comment: ' + data.message, 'Error');
      }
    } catch (err) {
      console.error('Error deleting comment:', err);
      await showAlert('Error deleting comment', 'Error');
    }
  }

  computeMoveCardOrder(targetColumnId, position, cardId) {
    const sourceColumns = Array.isArray(this.originalColumns) && this.originalColumns.length > 0
      ? this.originalColumns
      : this.columns;
    const targetColumn = sourceColumns.find(c => c.id === targetColumnId);
    const targetCards = (targetColumn?.cards || [])
      .filter(c => !c.archived && c.id !== cardId)
      .map(c => Number(c.order))
      .filter(Number.isFinite);

    if (targetCards.length === 0) {
      return 0;
    }

    if (position === 'top') {
      return Math.min(...targetCards);
    }

    return Math.max(...targetCards) + 1;
  }

  getCardOriginalPosition(cardId) {
    const cardElement = this.container.querySelector(`.card[data-card-id="${cardId}"]`);
    if (!cardElement) return null;

    return this.captureCardOriginalPosition(cardElement);
  }

  async openMoveCardModal(cardId) {
    if (window.header && !window.header.dbConnected) {
      this.showErrorToast('Cannot move card: Database is not connected. Please wait for the connection to be restored.');
      return;
    }

    const sourceColumns = Array.isArray(this.originalColumns) && this.originalColumns.length > 0
      ? this.originalColumns
      : this.columns;

    let sourceCard = null;
    let sourceColumn = null;

    sourceColumns.some((column) => {
      const card = (column.cards || []).find(c => c.id === cardId);
      if (card) {
        sourceCard = card;
        sourceColumn = column;
        return true;
      }
      return false;
    });

    if (!sourceCard || !sourceColumn) {
      await showAlert('Card not found', 'Error');
      return;
    }

    // Fetch accessible boards
    let boards = [];
    try {
      const boardsController = new AbortController();
      const boardsTimeout = setTimeout(() => boardsController.abort(), 5000);
      const boardsResponse = await fetch('/api/boards?archived=false', { signal: boardsController.signal });
      clearTimeout(boardsTimeout);
      const boardsData = await this.parseResponse(boardsResponse);
      if (boardsData.success) {
        boards = boardsData.boards;
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        this.showErrorToast('Timed out loading boards. Showing current board only.');
      } else {
        console.error('Failed to fetch boards:', err);
      }
    }
    if (boards.length === 0) {
      boards = [{ id: this.boardId, name: this.boardName }];
    }

    const currentBoardColumns = sourceColumns.filter(c => c.id !== sourceColumn.id);

    const buildColumnOptions = (columns) =>
      columns.length === 0
        ? '<option value="">-- No columns available --</option>'
        : '<option value="">-- Select Column --</option>' +
          columns.map(col => `<option value="${col.id}">${this.escapeHtml(col.name)}</option>`).join('');

    const modalHtml = `
      <div class="modal" id="move-card-modal" role="dialog" aria-modal="true" aria-labelledby="move-card-modal-title" aria-describedby="move-card-modal-desc">
        <div class="modal-content">
          <h2 id="move-card-modal-title">Move Card</h2>
          <p id="move-card-modal-desc">Move <strong>${this.escapeHtml(sourceCard.title || 'Untitled card')}</strong> from <strong>${this.escapeHtml(sourceColumn.name)}</strong> to:</p>
          <form id="move-card-form">
            <div class="form-group">
              <label for="move-card-target-board">Target Board:</label>
              <select id="move-card-target-board" name="target-board">
                ${boards.map(b => `<option value="${b.id}" ${b.id === this.boardId ? 'selected' : ''}>${this.escapeHtml(b.name)}</option>`).join('')}
              </select>
            </div>
            <div class="form-group">
              <label for="move-card-target-column">Target Column:</label>
              <select id="move-card-target-column" name="target-column" required aria-required="true">
                ${buildColumnOptions(currentBoardColumns)}
              </select>
            </div>
            <div class="form-group">
              <label for="move-card-position">Position:</label>
              <select id="move-card-position" name="position" required aria-required="true">
                <option value="top">Top of column</option>
                <option value="bottom">Bottom of column</option>
              </select>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-secondary" id="cancel-move-card-btn">Cancel</button>
              <button type="submit" class="btn btn-primary">Move Card</button>
            </div>
          </form>
        </div>
      </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modal = document.getElementById('move-card-modal');
    const form = document.getElementById('move-card-form');
    const cancelBtn = document.getElementById('cancel-move-card-btn');
    const boardSelect = document.getElementById('move-card-target-board');
    const columnSelect = document.getElementById('move-card-target-column');
    const positionSelect = document.getElementById('move-card-position');

    boardSelect.focus();

    const loadColumnsForBoard = async (boardId) => {
      if (boardId === this.boardId) {
        columnSelect.innerHTML = buildColumnOptions(currentBoardColumns);
        return;
      }
      columnSelect.innerHTML = '<option value="">Loading...</option>';
      columnSelect.disabled = true;
      try {
        const colController = new AbortController();
        const colTimeout = setTimeout(() => colController.abort(), 5000);
        const response = await fetch(`/api/boards/${boardId}/columns`, { signal: colController.signal });
        clearTimeout(colTimeout);
        const data = await this.parseResponse(response);
        if (data.success && data.columns) {
          columnSelect.innerHTML = buildColumnOptions(data.columns);
        } else {
          columnSelect.innerHTML = '<option value="">-- No columns available --</option>';
          this.showErrorToast(data.message || 'Failed to load columns');
        }
      } catch (err) {
        columnSelect.innerHTML = '<option value="">-- Error loading columns --</option>';
        if (err.name === 'AbortError') {
          this.showErrorToast('Timed out loading columns');
        } else {
          console.error('Failed to fetch columns:', err);
          this.showErrorToast('Failed to load columns');
        }
      } finally {
        columnSelect.disabled = false;
      }
    };

    boardSelect.addEventListener('change', () => {
      loadColumnsForBoard(parseInt(boardSelect.value));
    });

    cancelBtn.addEventListener('click', () => {
      modal.remove();
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const targetColumnId = parseInt(columnSelect.value);
      const position = positionSelect.value;
      const targetBoardId = parseInt(boardSelect.value);

      if (!targetColumnId || !position) {
        return;
      }

      modal.remove();

      if (targetBoardId === this.boardId) {
        // Same board: compute order locally and use existing update path
        const newOrder = this.computeMoveCardOrder(targetColumnId, position, cardId);
        const originalPosition = this.getCardOriginalPosition(cardId);
        await this.updateCardPosition(cardId, targetColumnId, newOrder, originalPosition);
      } else {
        // Cross-board: let backend compute order from position
        const originalPosition = this.getCardOriginalPosition(cardId);
        const fallbackOrder = Number.isFinite(originalPosition?.order) ? originalPosition.order : 0;
        await this.updateCardPosition(cardId, targetColumnId, fallbackOrder, originalPosition, position);
    });

    setupModalBackgroundClose(modal, () => modal.remove());
  }
}

// Initialize board manager when DOM is ready
document.addEventListener('DOMContentLoaded', async () => {
  if (window.__aftBoardBootstrapDone) {
    return;
  }
  window.__aftBoardBootstrapDone = true;

  if (window.authBootstrapPromise) {
    const canContinue = await window.authBootstrapPromise;
    if (!canContinue) {
      return;
    }
  }

  window.boardManager = new BoardManager();
  window.boardManager.init();
});
