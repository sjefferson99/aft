/**
 * Shared utility functions for the AFT application
 */

/**
 * Global fetch wrapper to handle setup redirects and authentication
 */
(function() {
  const originalFetch = window.fetch;

  function isPublicPagePath(pathname) {
    const publicPages = window.__aftPublicPagePaths || [
      '/login.html',
      '/register.html',
      '/logout.html',
      '/setup.html',
      '/about.html',
      '/docs.html',
      '/public-board.html'
    ];

    return publicPages.some((pagePath) => (pathname || '').includes(pagePath));
  }

  window.fetch = async function(...args) {
    const response = await originalFetch.apply(this, args);
    
    // Clone response so we can read it twice if needed
    const clonedResponse = response.clone();
    
    // Handle 401 Unauthorized responses
    if (response.status === 401) {
      console.error('Authentication required (401 Unauthorized)');
      // Clear cached user data on authentication failure
      sessionStorage.removeItem('currentUser');
      window.currentUser = null;
      window.userDataReady = false;
      
      // Don't redirect on public pages.
      if (!isPublicPagePath(window.location.pathname)) {
        console.error('Authentication required, redirecting to login page');
        // Store the current page to redirect back after login
        sessionStorage.setItem('redirectAfterLogin', window.location.pathname + window.location.search);
        window.location.href = '/login.html';
      }
      return response;
    }
    
    // Check if this is a JSON response indicating setup required
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      try {
        const data = await clonedResponse.json();
        if (data.redirect === '/setup.html' && !window.location.pathname.includes('setup.html')) {
          window.location.href = '/setup.html';
          return response;
        }
      } catch (e) {
        // Not JSON or couldn't parse, just return original response
      }
    }
    
    return response;
  };
})();

/**
 * Apply time formatting based on user's preference.
 * Helper function used by both formatTime and formatTimeSync.
 * 
 * @param {Date} dateObj - Date object to format
 * @param {string} timeFormat - Either '12' or '24'
 * @param {boolean} includeSeconds - Whether to include seconds in the output
 * @param {string} timezone - IANA timezone name
 * @returns {string} Formatted time string
 */
function applyTimeFormat(dateObj, timeFormat, includeSeconds, timezone = 'UTC') {
  if (timeFormat === '12') {
    const options = {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: timezone
    };
    if (includeSeconds) {
      options.second = '2-digit';
    }
    return dateObj.toLocaleTimeString('en-US', options);
  } else {
    const options = {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: timezone
    };
    if (includeSeconds) {
      options.second = '2-digit';
    }
    return dateObj.toLocaleTimeString('en-GB', options);
  }
}

function parseTimestampAsUtc(date) {
  if (date instanceof Date) {
    return date;
  }

  if (typeof date !== 'string') {
    return new Date(date);
  }

  const trimmed = date.trim();
  if (!trimmed) {
    return new Date(trimmed);
  }

  // Treat naive backend timestamps as UTC.
  const hasExplicitTimezone = /(?:Z|[+\-]\d{2}:\d{2})$/i.test(trimmed);
  return new Date(hasExplicitTimezone ? trimmed : `${trimmed}Z`);
}

function getCachedTimezone() {
  const timezone = sessionStorage.getItem('timezone') || 'UTC';
  return timezone.trim() || 'UTC';
}

function formatDatePart(dateObj, locale = 'en-GB') {
  return dateObj.toLocaleDateString(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: getCachedTimezone(),
  });
}

async function preloadUserTimezone() {
  if (sessionStorage.getItem('timezone')) {
    return;
  }

  try {
    const response = await fetch('/api/settings/timezone');
    if (response.ok) {
      const data = await response.json();
      if (data.success && typeof data.value === 'string' && data.value.trim()) {
        sessionStorage.setItem('timezone', data.value.trim());
        return;
      }
    }
  } catch (err) {
    console.error('Error preloading timezone:', err);
  }

  sessionStorage.setItem('timezone', 'UTC');
}

/**
 * Preload the time format preference into session storage.
 * Call this early on page load to avoid fallbacks in synchronous formatting.
 * @returns {Promise<void>}
 */
async function preloadTimeFormat() {
  if (sessionStorage.getItem('timeFormat')) {
    return; // Already cached
  }
  
  try {
    const response = await fetch('/api/settings/time_format');
    if (response.ok) {
      const data = await response.json();
      if (data.success) {
        const value = data.value || '24';
        sessionStorage.setItem('timeFormat', (value === '12' || value === '24') ? value : '24');
      }
    }
  } catch (err) {
    console.error('Error preloading time format:', err);
  }
}

/**
 * Format time according to user's time format preference.
 * Uses session storage to cache the preference and avoid API calls on every render.
 * 
 * @param {Date|string} date - Date object or ISO date string
 * @param {boolean} includeSeconds - Whether to include seconds in the output
 * @returns {Promise<string>} Formatted time string (e.g., "2:30 PM" or "14:30")
 */
async function formatTime(date, includeSeconds = false) {
  const dateObj = parseTimestampAsUtc(date);
  
  // Check session storage first
  let timeFormat = sessionStorage.getItem('timeFormat');
  
  // If not cached, fetch from API
  if (!timeFormat) {
    try {
      const response = await fetch('/api/settings/time_format');
      if (response.ok) {
        const data = await response.json();
        if (data.success && (data.value === '12' || data.value === '24')) {
          timeFormat = data.value;
          sessionStorage.setItem('timeFormat', timeFormat);
        } else {
          timeFormat = '24'; // fallback
        }
      } else {
        timeFormat = '24'; // fallback
      }
    } catch (err) {
      console.error('Error fetching time format preference:', err);
      timeFormat = '24'; // fallback
    }
  }
  
  // Format using helper function
  return applyTimeFormat(dateObj, timeFormat, includeSeconds, getCachedTimezone());
}

/**
 * Format time synchronously using cached preference.
 * Falls back to 24-hour format if preference not yet cached.
 * Use this for synchronous rendering contexts.
 * 
 * @param {Date|string} date - Date object or ISO date string
 * @param {boolean} includeSeconds - Whether to include seconds in the output
 * @returns {string} Formatted time string (e.g., "2:30 PM" or "14:30")
 */
function formatTimeSync(date, includeSeconds = false) {
  const dateObj = parseTimestampAsUtc(date);
  
  // Check session storage (synchronous) and validate
  const cachedFormat = sessionStorage.getItem('timeFormat') || '24';
  const timeFormat = (cachedFormat === '12' || cachedFormat === '24') ? cachedFormat : '24';
  
  // Format using helper function
  return applyTimeFormat(dateObj, timeFormat, includeSeconds, getCachedTimezone());
}

/**
 * Format a date/timestamp for display in tooltips.
 * Returns a consistent format across the application: "4 Dec 2025 14:30" or "4 Dec 2025 2:30 PM"
 * Uses synchronous formatting with cached time format preference.
 * 
 * @param {Date|string} date - Date object or ISO date string
 * @returns {string} Formatted date string
 */
function formatTooltipDateTime(date) {
  const dateObj = parseTimestampAsUtc(date);
  const datePart = formatDatePart(dateObj);
  const timePart = formatTimeSync(dateObj);
  return `${datePart} ${timePart}`;
}

/**
 * Format a timestamp as relative time (e.g., "2m ago", "5h ago", "3d ago")
 * Similar to formatCommentDate but more concise for display on cards
 * 
 * @param {Date|string|null} date - Date object or ISO date string, or null
 * @returns {string} Formatted relative time string
 */
function formatTimeAgo(date) {
  if (!date) return '';
  
  const dateObj = parseTimestampAsUtc(date);
  const now = new Date();
  
  const diffMs = now - dateObj;
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  const diffWeeks = Math.floor(diffMs / 604800000);
  const diffMonths = Math.floor(diffMs / 2592000000);
  const diffYears = Math.floor(diffMs / 31536000000);
  
  if (diffSecs < 10) return 'just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffWeeks < 4) return `${diffWeeks}w ago`;
  if (diffMonths < 12) return `${diffMonths}mo ago`;
  return `${diffYears}y ago`;
}

/**
 * Format a timestamp as relative time with longer format (e.g., "2 minutes ago", "5 hours ago")
 * Used for more prominent displays like in modals
 * 
 * @param {Date|string|null} date - Date object or ISO date string, or null
 * @returns {string} Formatted relative time string
 */
function formatTimeAgoLong(date) {
  if (!date) return '';
  
  const dateObj = parseTimestampAsUtc(date);
  const now = new Date();
  
  const diffMs = now - dateObj;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins} minute${diffMins === 1 ? '' : 's'} ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`;
  if (diffDays < 7) return `${diffDays} day${diffDays === 1 ? '' : 's'} ago`;
  
  // For older dates, show the formatted date
  return formatDatePart(dateObj) + ' ' + formatTimeSync(dateObj);
}

/**
 * Calculate the whole-day/hour duration between two datetime-local value
 * strings (e.g. "2026-06-20T09:00"). Used to keep a card's duration fields
 * in sync with its start/end date pickers.
 *
 * @param {string} startLocalValue - datetime-local value string
 * @param {string} endLocalValue - datetime-local value string
 * @returns {{days: number, hours: number}|null} Duration, or null if either
 *   input is empty/invalid or end is before start.
 */
function diffToDuration(startLocalValue, endLocalValue) {
  if (!startLocalValue || !endLocalValue) return null;

  const start = new Date(startLocalValue);
  const end = new Date(endLocalValue);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null;

  const diffMs = end.getTime() - start.getTime();
  if (diffMs < 0) return null;

  const totalHours = Math.floor(diffMs / 3600000);
  return { days: Math.floor(totalHours / 24), hours: totalHours % 24 };
}

/**
 * Add a days/hours duration to a datetime-local value string, returning a
 * new datetime-local value string for the resulting end date.
 *
 * @param {string} startLocalValue - datetime-local value string
 * @param {number} days
 * @param {number} hours
 * @returns {string} datetime-local value string, or '' if start is invalid
 */
function addDurationToLocalValue(startLocalValue, days, hours) {
  if (!startLocalValue) return '';

  const start = new Date(startLocalValue);
  if (Number.isNaN(start.getTime())) return '';

  const totalMs = ((days || 0) * 24 + (hours || 0)) * 3600000;
  const end = new Date(start.getTime() + totalMs);

  const pad = (num) => String(num).padStart(2, '0');
  return `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}T${pad(end.getHours())}:${pad(end.getMinutes())}`;
}

/**
 * Modal Dialog System
 * Replaces browser alert(), confirm(), and prompt() with styled modals
 */
class ModalDialog {
  constructor() {
    this.modal = null;
    this.title = null;
    this.message = null;
    this.input = null;
    this.cancelBtn = null;
    this.confirmBtn = null;
    this.isOpen = false;
    this.currentCleanup = null;
    this.isInitialized = false;
  }

  ensureInitialized() {
    // Lazy initialization - only create modal when first needed
    if (this.isInitialized && this.modal) {
      return true;
    }

    // Check if DOM is ready
    if (typeof document === 'undefined' || !document.body) {
      console.error('ModalDialog: Document body not available yet');
      return false;
    }

    // Create modal HTML structure
    const modalHTML = `
      <div id="appModal" class="modal-app" role="dialog" aria-modal="true" aria-labelledby="appModalTitle" aria-describedby="appModalMessage">
        <div class="modal-content">
          <div class="modal-header">
            <h2 id="appModalTitle"></h2>
          </div>
          <div class="modal-body">
            <p id="appModalMessage"></p>
            <input type="text" id="appModalInput" style="display: none;" class="modal-input">
          </div>
          <div class="modal-actions">
            <button class="btn btn-secondary" id="appModalCancelBtn" style="display: none;">Cancel</button>
            <button class="btn btn-primary" id="appModalConfirmBtn">OK</button>
          </div>
        </div>
      </div>
    `;

    // Add modal to body if not already present
    if (!document.getElementById('appModal')) {
      document.body.insertAdjacentHTML('beforeend', modalHTML);
    }

    // Get references to modal elements
    this.modal = document.getElementById('appModal');
    this.title = document.getElementById('appModalTitle');
    this.message = document.getElementById('appModalMessage');
    this.input = document.getElementById('appModalInput');
    this.cancelBtn = document.getElementById('appModalCancelBtn');
    this.confirmBtn = document.getElementById('appModalConfirmBtn');

    // Verify all elements were found
    if (!this.modal || !this.title || !this.message || !this.input || !this.cancelBtn || !this.confirmBtn) {
      console.error('ModalDialog: Failed to initialize modal elements');
      return false;
    }

    this.isInitialized = true;
    return true;
  }

  show(title, message, options = {}) {
    return new Promise((resolve) => {
      // Ensure modal is initialized
      if (!this.ensureInitialized()) {
        console.error('ModalDialog: Cannot show modal - initialization failed');
        // Fallback to browser alert/confirm
        if (options.showInput) {
          resolve(prompt(message, options.defaultValue || ''));
        } else if (options.showCancel) {
          resolve(confirm(message));
        } else {
          alert(message);
          resolve(true);
        }
        return;
      }

      // If modal is already open, wait for it to close first
      if (this.isOpen) {
        // Clean up previous modal immediately
        if (this.currentCleanup) {
          this.currentCleanup();
        }
        // Remove show class and wait for animation to complete
        this.modal.classList.remove('show');
        
        // Wait for CSS animation to complete (300ms from modalSlideIn animation)
        // Adding small buffer for safety
        setTimeout(() => {
          this.isOpen = false;
          this.currentCleanup = null;
          // Now show the new modal
          this.showModalContent(title, message, options, resolve);
        }, 350);
        return;
      }

      this.showModalContent(title, message, options, resolve);
    });
  }

  showModalContent(title, message, options, resolve) {
      this.isOpen = true;
      this.title.textContent = title;
      
      // Handle multi-line messages by converting \n to <br> and preserving whitespace
      // Clear existing content first
      this.message.innerHTML = '';
      
      // Split message by newlines and create text nodes with breaks
      const lines = message.split('\n');
      lines.forEach((line, index) => {
        this.message.appendChild(document.createTextNode(line));
        if (index < lines.length - 1) {
          this.message.appendChild(document.createElement('br'));
        }
      });
      
      // Handle input field for prompt
      if (options.showInput) {
        this.input.style.display = 'block';
        this.input.value = options.defaultValue || '';
      } else {
        this.input.style.display = 'none';
      }

      // Handle cancel button for confirm/prompt
      if (options.showCancel) {
        this.cancelBtn.style.display = 'inline-block';
        this.cancelBtn.textContent = options.cancelText || 'Cancel';
      } else {
        this.cancelBtn.style.display = 'none';
      }

      // Set confirm button text
      this.confirmBtn.textContent = options.confirmText || 'OK';

      // Blur currently focused element to prevent scroll on modal close
      if (document.activeElement && document.activeElement !== document.body) {
        document.activeElement.blur();
      }

      // Show modal
      this.modal.classList.add('show');

      // Handle confirm
      const handleConfirm = () => {
        cleanup();
        this.modal.classList.remove('show');
        this.isOpen = false;
        this.currentCleanup = null;
        
        // Ensure no element receives focus that could cause scrolling
        if (document.activeElement && document.activeElement !== document.body) {
          document.activeElement.blur();
        }
        
        if (options.showInput) {
          resolve(this.input.value);
        } else {
          resolve(true);
        }
      };

      // Handle cancel
      const handleCancel = () => {
        cleanup();
        this.modal.classList.remove('show');
        this.isOpen = false;
        this.currentCleanup = null;
        
        // Ensure no element receives focus that could cause scrolling
        if (document.activeElement && document.activeElement !== document.body) {
          document.activeElement.blur();
        }
        
        if (options.showInput) {
          resolve(null);
        } else {
          resolve(false);
        }
      };

      // Handle escape/Enter key
      const handleEscape = (e) => {
        if (e.key === 'Escape') {
          handleCancel();
        } else if (e.key === 'Enter') {
          // Only auto-confirm on Enter for alert and prompt modals
          if (!options.showCancel || options.showInput) {
            e.preventDefault();
            handleConfirm();
          }
        }
      };

      // Handle backdrop click (click outside modal content)
      const handleBackdropClick = (e) => {
        // Only close if clicking directly on the backdrop, not on modal content
        if (e.target === this.modal) {
          handleCancel();
        }
      };

      // Cleanup function
      const cleanup = () => {
        this.confirmBtn.removeEventListener('click', handleConfirm);
        this.cancelBtn.removeEventListener('click', handleCancel);
        document.removeEventListener('keydown', handleEscape);
        this.modal.removeEventListener('click', handleBackdropClick);
      };

      // Store cleanup function for potential early cleanup
      this.currentCleanup = cleanup;

      // Add event listeners
      this.confirmBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        handleConfirm();
      });
      this.cancelBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        handleCancel();
      });
      document.addEventListener('keydown', handleEscape);
      this.modal.addEventListener('click', handleBackdropClick);

      // Focus appropriate element after ensuring DOM is ready
      // Using requestAnimationFrame for more reliable focus timing
      // preventScroll prevents the browser from scrolling to the focused element
      requestAnimationFrame(() => {
        if (options.showInput) {
          this.input.focus({ preventScroll: true });
        } else {
          this.confirmBtn.focus({ preventScroll: true });
        }
      });
  }

  alert(message, title = 'Alert') {
    return this.show(title, message, { showCancel: false });
  }

  confirm(message, title = 'Confirm') {
    return this.show(title, message, { showCancel: true, confirmText: 'OK', cancelText: 'Cancel' });
  }

  prompt(message, defaultValue = '', title = 'Input') {
    return this.show(title, message, { showInput: true, showCancel: true, defaultValue });
  }
}

// Create global modal instance
const modalDialog = new ModalDialog();

/**
 * Close a modal when Escape is pressed, using the provided close handler.
 * Returns a cleanup function that removes the Escape listener.
 *
 * @param {HTMLElement} modal - The modal element to bind.
 * @param {Function} closeHandler - Function to invoke when Escape is pressed.
 * @returns {Function} Cleanup function that removes the listener.
 */
const MODAL_ESCAPE_CLEANUP_KEY = '__aftModalEscapeCleanup';

function setupModalEscapeClose(modal, closeHandler) {
  if (!modal || typeof closeHandler !== 'function') {
    return () => {};
  }

  const previousCleanup = modal[MODAL_ESCAPE_CLEANUP_KEY];
  if (typeof previousCleanup === 'function') {
    previousCleanup();
  }

  const handleKeydown = (event) => {
    if (event.key !== 'Escape') {
      return;
    }

    event.preventDefault();
    Promise.resolve(closeHandler()).catch((error) => {
      console.error('Error in modal Escape close handler:', error);
    });
  };

  document.addEventListener('keydown', handleKeydown);

  const cleanup = () => {
    document.removeEventListener('keydown', handleKeydown);
    if (modal[MODAL_ESCAPE_CLEANUP_KEY] === cleanup) {
      modal[MODAL_ESCAPE_CLEANUP_KEY] = null;
    }
  };

  modal[MODAL_ESCAPE_CLEANUP_KEY] = cleanup;
  return cleanup;
}

/**
 * Display a styled alert modal dialog (replacement for browser alert()).
 * Supports multi-line messages using \n characters.
 * 
 * @param {string} message - The message to display. Use \n for line breaks.
 * @param {string} [title='Alert'] - The title of the alert dialog.
 * @returns {Promise<boolean>} Promise that resolves to true when dismissed.
 * 
 * @example
 * await showAlert('Operation completed successfully!');
 * 
 * @example
 * await showAlert('Error details:\n\nFailed to save data.\nPlease try again.', 'Error');
 */
function showAlert(message, title = 'Alert') {
  return modalDialog.alert(message, title);
}

/**
 * Display a styled confirmation modal dialog (replacement for browser confirm()).
 * Supports multi-line messages using \n characters.
 * 
 * @param {string} message - The message to display. Use \n for line breaks.
 * @param {string} [title='Confirm'] - The title of the confirmation dialog.
 * @returns {Promise<boolean>} Promise that resolves to true if OK is clicked, false if Cancel is clicked or dialog is dismissed.
 * 
 * @example
 * const confirmed = await showConfirm('Are you sure you want to delete this item?');
 * if (confirmed) {
 *   // Proceed with deletion
 * }
 * 
 * @example
 * const result = await showConfirm('This action cannot be undone.\n\nAre you sure?', 'Warning');
 */
function showConfirm(message, title = 'Confirm') {
  return modalDialog.confirm(message, title);
}

/**
 * Display a styled prompt modal dialog (replacement for browser prompt()).
 * Allows user to input text with an optional default value.
 * 
 * @param {string} message - The message to display.
 * @param {string} [defaultValue=''] - The default value for the input field.
 * @param {string} [title='Input'] - The title of the prompt dialog.
 * @returns {Promise<string|null>} Promise that resolves to the input value if OK is clicked, null if Cancel is clicked or dialog is dismissed.
 * 
 * @example
 * const name = await showPrompt('Enter your name:', 'John Doe');
 * if (name !== null) {
 *   console.log('User entered:', name);
 * }
 * 
 * @example
 * const boardName = await showPrompt('Enter board name:', '', 'Create Board');
 */
function showPrompt(message, defaultValue = '', title = 'Input') {
  return modalDialog.prompt(message, defaultValue, title);
}

/**
 * Load and apply the current theme to the page.
 * This function fetches the theme settings from the server and applies them to CSS variables.
 * Available on all pages that include utils.js.
 * @async
 */
async function loadAndApplyThemeGlobal() {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    
    const response = await fetch('/api/settings/theme', {
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      throw new Error(`Failed to load theme: ${response.statusText}`);
    }
    
    const theme = await response.json();
    
    if (!theme || !theme.settings) {
      throw new Error('Invalid theme data');
    }
    
    const root = document.documentElement;
    const settings = theme.settings;
    
    // Apply all color variables
    Object.keys(settings).forEach(key => {
      root.style.setProperty(`--${key}`, settings[key]);
    });
    
    // Apply background image
    if (theme.background_image) {
      root.style.setProperty('--background-image', `url('/images/backgrounds/${theme.background_image}')`);
      sessionStorage.setItem('backgroundImage', theme.background_image);
    } else {
      root.style.setProperty('--background-image', 'none');
      sessionStorage.setItem('backgroundImage', 'none');
    }
    
    // Update sessionStorage for persistence
    sessionStorage.setItem('currentTheme', JSON.stringify(settings));
  } catch (error) {
    if (error.name === 'AbortError') {
      console.error('✗ Load theme request timed out');
    } else {
      console.error('✗ Error loading and applying theme:', error);
    }
  }
}

/**
 * Escape HTML special characters to prevent XSS.
 * 
 * @param {string} unsafe - Unsafe string to escape
 * @returns {string} Escaped string
 */
function escapeHtml(unsafe) {
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Global user context for storing current user and permissions.
 * 
 * Populated from sessionStorage cache (set during login) or fetched from /api/auth/me
 * by header.js on first page load. Cached in sessionStorage to avoid API calls on 
 * every page navigation.
 * 
 * Structure:
 * {
 *   id: number,
 *   email: string,
 *   username: string,
 *   display_name: string,
 *   permissions: string[],  // e.g., ['board.view', 'card.edit', 'user.manage']
 *   roles: object[]
 * }
 */
window.currentUser = null;

/**
 * Flag indicating whether user data has been loaded by header.js.
 * Set to true after header completes loading (whether user is logged in or not).
 * Use this to wait for user data before checking permissions.
 */
window.userDataReady = false;

/**
 * Check if the current user has a specific permission.
 * 
 * @param {string} permission - The permission to check (e.g., 'user.manage')
 * @returns {boolean} True if user has the permission
 */
function hasPermission(permission) {
  if (!window.currentUser || !window.currentUser.permissions) {
    return false;
  }
  
  // system.admin has all permissions
  if (window.currentUser.permissions.includes('system.admin')) {
    return true;
  }
  
  return window.currentUser.permissions.includes(permission);
}

/**
 * Show an access denied message and optionally redirect.
 * 
 * @param {string} message - Custom message to display
 * @param {string} redirectTo - URL to redirect to (optional, defaults to home)
 */
function showAccessDenied(message = 'You do not have permission to access this page.', redirectTo = '/') {
  // Create overlay
  const overlay = document.createElement('div');
  overlay.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-color: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
  `;
  
  // Create modal
  const modal = document.createElement('div');
  modal.style.cssText = `
    background-color: var(--card-bg, #ffffff);
    color: var(--text-primary, #2C3E50);
    padding: 30px;
    border-radius: 8px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    max-width: 500px;
    text-align: center;
  `;
  
  // Create content
  modal.innerHTML = `
    <svg style="width: 64px; height: 64px; margin-bottom: 20px; color: var(--error-color, #e74c3c);" 
         viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"></circle>
      <line x1="12" y1="8" x2="12" y2="12"></line>
      <line x1="12" y1="16" x2="12.01" y2="16"></line>
    </svg>
    <h2 style="margin: 0 0 15px 0; font-size: 24px;">Access Denied</h2>
    <p style="margin: 0 0 25px 0; font-size: 16px;">${escapeHtml(message)}</p>
    <button id="access-denied-btn" style="
      background-color: var(--primary-color, #3498db);
      color: white;
      border: none;
      padding: 12px 24px;
      border-radius: 6px;
      font-size: 16px;
      cursor: pointer;
      transition: background-color 0.2s;
    ">Go to Home</button>
  `;
  
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  
  // Handle button click
  document.getElementById('access-denied-btn').addEventListener('click', () => {
    window.location.href = redirectTo;
  });
}

