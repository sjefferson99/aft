// Header component functionality

// Central logo configuration — change this one path to update the logo everywhere
const LOGO_PATH = '/images/AFT_logo.webp';
// PNG favicon path — used for the page favicon (wider browser support than WebP)
const FAVICON_PATH = '/images/AFT_logo.png';

/**
 * Close all pinned dropdown menus except the specified one.
 * This provides centralized coordination of menu states.
 * @param {HTMLElement|null} exceptMenu - Menu to keep open (null to close all)
 * @global
 */
function closeAllMenusExcept(exceptMenu = null) {
  const settingsMenu = document.getElementById('settings-dropdown-menu');
  const userMenu = document.getElementById('user-dropdown-menu');
  const notificationsPopup = document.getElementById('notifications-popup');
  const allMenus = [settingsMenu, userMenu, notificationsPopup].filter(Boolean);
  
  allMenus.forEach(menu => {
    if (menu !== exceptMenu) {
      const wasPinned = menu.classList.contains('pinned');
      
      if (wasPinned) {
        menu.classList.remove('pinned');
      }
      
      // Sync notifications component state if closing notifications
      // (regardless of whether it was pinned or just had state set)
      if (menu === notificationsPopup && window.notifications && window.notifications.isPopupOpen) {
        window.notifications.isPopupOpen = false;
      }
    }
  });
}

/**
 * Update hover state for all dropdown menus based on whether any are pinned.
 * This is shared between header dropdowns and notifications.
 * @global
 */
function updateMenuHoverState() {
  const settingsMenu = document.getElementById('settings-dropdown-menu');
  const userMenu = document.getElementById('user-dropdown-menu');
  const notificationsPopup = document.getElementById('notifications-popup');
  const allMenus = [settingsMenu, userMenu, notificationsPopup].filter(Boolean);
  
  // Check if any menu is pinned
  const anyPinned = allMenus.some(menu => menu.classList.contains('pinned'));
  
  // Add/remove no-hover class on all menus
  allMenus.forEach(menu => {
    if (anyPinned) {
      menu.classList.add('no-hover');
    } else {
      menu.classList.remove('no-hover');
    }
  });
}

const AUTH_BOOTSTRAP_LOADING_DELAY_MS = 500;
let authBootstrapLoadingTimeoutId = null;

function isPublicPagePath(pathname) {
  // Use the shared allowlist set by theme-loader.js; fall back to a local copy
  // in case this script ever runs without theme-loader.js on the page.
  const publicPages = window.__aftPublicPagePaths || [
    '/login.html',
    '/register.html',
    '/logout.html',
    '/setup.html',
    '/about.html',
    '/docs.html',
    '/public-board.html'
  ];

  return publicPages.some((pagePath) => pathname.includes(pagePath));
}

async function ensureAuthenticatedForProtectedPage() {
  const currentPath = window.location.pathname || '';
  if (isPublicPagePath(currentPath)) {
    return true;
  }

  try {
    const response = await fetch('/api/auth/me', {
      cache: 'no-store'
    });

    if (response.ok) {
      const data = await response.json();
      if (data && data.user) {
        window.currentUser = data.user;
        window.userDataReady = true;
        sessionStorage.setItem('currentUser', JSON.stringify(data.user));
        return true;
      }
    }
  } catch (error) {
    console.error('Authentication bootstrap check failed:', error);
  }

  window.currentUser = null;
  window.userDataReady = false;
  sessionStorage.removeItem('currentUser');

  if (!isPublicPagePath(currentPath)) {
    sessionStorage.setItem('redirectAfterLogin', `${window.location.pathname}${window.location.search}${window.location.hash}`);
    window.location.href = '/login.html';
  }

  return false;
}

function showAuthBootstrapLoading() {
  const currentPath = window.location.pathname || '';
  if (isPublicPagePath(currentPath)) {
    return null;
  }

  let panel = document.getElementById('auth-bootstrap-loading');
  if (panel) {
    return panel;
  }

  panel = document.createElement('div');
  panel.id = 'auth-bootstrap-loading';
  panel.setAttribute('role', 'status');
  panel.setAttribute('aria-live', 'polite');
  panel.style.cssText = [
    'position: fixed',
    'inset: 0',
    'display: flex',
    'align-items: center',
    'justify-content: center',
    'z-index: 10001',
    'background: rgba(0, 0, 0, 0.25)',
    'backdrop-filter: blur(2px)'
  ].join(';');

  const content = document.createElement('div');
  content.style.cssText = [
    'background: var(--page-panel-background, #fff)',
    'color: var(--text-bold, #2d3f57)',
    'padding: 14px 20px',
    'border-radius: 10px',
    'box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18)',
    'font-size: 16px',
    'font-weight: 500',
    'text-align: center'
  ].join(';');
  content.textContent = 'Checking authentication...';
  panel.appendChild(content);

  document.body.appendChild(panel);
  return panel;
}

function scheduleAuthBootstrapLoading() {
  const currentPath = window.location.pathname || '';
  if (isPublicPagePath(currentPath)) {
    return;
  }

  if (authBootstrapLoadingTimeoutId) {
    return;
  }

  authBootstrapLoadingTimeoutId = setTimeout(() => {
    authBootstrapLoadingTimeoutId = null;
    showAuthBootstrapLoading();
  }, AUTH_BOOTSTRAP_LOADING_DELAY_MS);
}

function hideAuthBootstrapLoading() {
  if (authBootstrapLoadingTimeoutId) {
    clearTimeout(authBootstrapLoadingTimeoutId);
    authBootstrapLoadingTimeoutId = null;
  }

  const panel = document.getElementById('auth-bootstrap-loading');
  if (panel) {
    panel.remove();
  }
}

// Start auth bootstrap as early as possible so page-specific scripts can gate on it.
if (!window.authBootstrapPromise && !isPublicPagePath(window.location.pathname || '')) {
  window.authBootstrapPromise = ensureAuthenticatedForProtectedPage();
}

class Header {
  constructor() {
    this.statusIcon = null;
    this.statusText = null;
    this.versionInfo = null;
    this.statusPresentationObserver = null;
    this.currentView = 'task'; // Default view
    this.workingStyle = 'kanban'; // Working style: 'kanban' or 'agile'
    this.boardStyleEditable = false;
    this.boardVisibilityEditable = false;
    this.boardIsPublic = false;
    this.boardArchived = false;
    this.boardPublicSlug = null;
    this.currentBoardId = null;
    this.dbConnected = false; // Track database connection status
    this.wsConnected = false; // Track WebSocket connection status
    this.wsConnectionStartTime = null; // Track when WebSocket connection attempt started (for timeout detection)
    this.wsCheckInterval = null; // WebSocket check interval
    this.mobileBreakpoint = 900;
    this.boardFiltersVisibilityHandler = this.handleBoardFiltersVisibilityChanged.bind(this);
    this.boardFiltersActiveStateHandler = this.handleBoardFiltersActiveStateChanged.bind(this);
    this.boardOwnerDataLoadedHandler = this.handleBoardOwnerDataLoaded.bind(this);
    this.boardFilterStateWatchInterval = null;
    this.workingStyleLoadPromise = null;
    this.boardReassignmentOptions = null;
    this.boardOwnerDataListenerBound = false;
    this._prevUnhealthyServices = null; // Track previous scheduler health state for toast deduplication
    this.isPublicBoardPage = (window.location.pathname || '').includes('/public-board.html');
  }

  applyBrandingAssets(logoPath = LOGO_PATH, faviconPath = FAVICON_PATH) {
    const logoImg = document.querySelector('.header-logo');
    if (logoImg) {
      logoImg.src = logoPath;
    }

    const faviconLinks = document.querySelectorAll('link[rel="icon"]');
    const isDefaultAssets = logoPath === LOGO_PATH && faviconPath === FAVICON_PATH;

    let customMimeType = '';
    if (!isDefaultAssets) {
      const normalizedPath = (faviconPath || '').toLowerCase();
      if (normalizedPath.endsWith('.webp')) {
        customMimeType = 'image/webp';
      } else if (normalizedPath.endsWith('.png')) {
        customMimeType = 'image/png';
      } else if (normalizedPath.endsWith('.gif')) {
        customMimeType = 'image/gif';
      } else if (normalizedPath.endsWith('.jpg') || normalizedPath.endsWith('.jpeg')) {
        customMimeType = 'image/jpeg';
      }
    }

    faviconLinks.forEach((faviconLink) => {
      if (isDefaultAssets) {
        const currentType = (faviconLink.getAttribute('type') || '').toLowerCase();
        faviconLink.href = currentType === 'image/webp' ? LOGO_PATH : FAVICON_PATH;
        return;
      }

      faviconLink.href = faviconPath;

      if (customMimeType) {
        faviconLink.setAttribute('type', customMimeType);
      } else {
        faviconLink.removeAttribute('type');
      }
    });
  }

  async applyCustomLogoIfSet() {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const response = await fetch('/api/branding/logo', {
        signal: controller.signal,
        cache: 'no-store'
      });
      clearTimeout(timeoutId);

      if (!response.ok) {
        return;
      }

      const data = await response.json();
      const filename = typeof data.filename === 'string' ? data.filename.trim() : '';

      if (!filename) {
        return;
      }

      const customLogoPath = `/images/backgrounds/logos/${encodeURIComponent(filename)}`;
      this.applyBrandingAssets(customLogoPath, customLogoPath);
    } catch (error) {
      clearTimeout(timeoutId);
      if (error.name !== 'AbortError') {
        console.warn('Failed to load custom branding logo:', error);
      }
    }
  }

  getLastVisitedBoardId() {
    const rawBoardId = sessionStorage.getItem('lastVisitedBoardId');
    if (!rawBoardId) {
      return null;
    }

    const parsedBoardId = parseInt(rawBoardId, 10);
    return Number.isFinite(parsedBoardId) && parsedBoardId > 0 ? parsedBoardId : null;
  }

  updatePrimaryNavigationTargets() {
    const logoLink = document.querySelector('.header-logo-link');
    if (!logoLink) {
      return;
    }

    const isBoardPage = (window.location.pathname || '').includes('/board.html');
    if (isBoardPage) {
      logoLink.setAttribute('href', '/');
      return;
    }

    const lastBoardId = this.getLastVisitedBoardId();
    if (lastBoardId) {
      logoLink.setAttribute('href', `/board.html?id=${lastBoardId}`);
    } else {
      logoLink.setAttribute('href', '/');
    }
  }

  // Load the header HTML component
  async load() {
    const response = await fetch('/components/header.html');
    const html = await response.text();
    const parser = new DOMParser();
    const parsedDocument = parser.parseFromString(html, 'text/html');
    const headerElement = parsedDocument.body.firstElementChild;

    if (!headerElement) {
      throw new Error('Header component did not contain a root element');
    }

    document.body.prepend(document.importNode(headerElement, true));
    this.updatePrimaryNavigationTargets();

    // Apply default branding first, then replace with custom instance branding if configured.
    this.applyBrandingAssets();
    await this.applyCustomLogoIfSet();
    
    // Get references to status elements after HTML is inserted
    this.statusIcon = document.getElementById('status-icon');
    this.statusText = document.getElementById('status-text');
    this.versionInfo = document.getElementById('version-info');
    
    // Initialize status as "Connected" by default (optimistic approach)
    // Will be updated by checks if there's an actual problem
    if (this.statusIcon && this.statusText) {
      this.statusIcon.className = 'status-icon success';
      this.statusText.textContent = 'Connected';
    }
    
    // Add click handler to db-status
    const dbStatus = document.querySelector('.db-status');
    if (dbStatus) {
      dbStatus.addEventListener('click', () => {
        window.location.href = '/system-info.html';
      });
      dbStatus.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') {
          return;
        }
        event.preventDefault();
        window.location.href = '/system-info.html';
      });
    }

    this.initializeStatusWidgetPresentation();
    
    // Initialize notifications if the class exists
    if (typeof Notifications !== 'undefined') {
      window.notifications = new Notifications();
    }
    
    // Initialize dropdown pin behavior for settings and user menus
    this.initializeDropdownPin();

    // Initialize mobile drawer behavior
    this.initializeMobileMenu();

    // Initialize mobile notifications panel
    this.initializeMobileNotifications();

    // Initialize board-only filter toggle in settings menu
    this.initializeBoardFilterToggleMenu();
    
    // Initialize clear filters menu item
    this.initializeBoardFilterClearMenu();
    
    // Load current user info
    await this.loadCurrentUser();
    
    // Load working style preference
    this.workingStyleLoadPromise = this.loadWorkingStyle();
    await this.workingStyleLoadPromise;

    // Initialize board style toggle in settings menu
    this.initializeBoardStyleToggleMenu();

    // Initialize board visibility toggle in settings menu
    this.initializeBoardVisibilityToggleMenu();

    // Initialize board archive toggle in settings menu
    this.initializeBoardArchiveToggleMenu();

    // Initialize public-link rotation action in settings menu
    this.initializeRotatePublicLinkMenu();

    // Initialize embed code copy action in settings menu
    this.initializeCopyEmbedCodeMenu();

    // Initialize board reassignment in settings menu
    await this.initializeBoardReassignMenu();
    
    // Initialize views dropdown
    this.initializeViewsDropdown();

    if (!this.isPublicBoardPage) {
      // Load boards dropdown
      this.loadBoardsDropdown();

      // Fetch version info immediately (without checking status)
      this.loadVersionInfo();

      // Poll database status every 5 seconds
      this.statusCheckInterval = setInterval(() => {
        this.checkDatabaseStatus();
      }, 5000);

      // Initialize WebSocket monitoring
      this.monitorWebSocketConnection();

      // Store last WebSocket state to detect changes
      this.lastWsState = null;
    } else {
      this.setPublicBoardContext({
        isPublicBoard: false,
        publicUrl: '',
        isPublicPage: true,
        showLoginCta: !window.currentUser,
      });

      let attempts = 0;
      const maxAttempts = 40;
      const hydrateInterval = setInterval(() => {
        attempts += 1;
        const manager = window.boardManager;
        if (manager && manager.hasLoadedBoardData) {
          this.setPublicBoardContext({
            isPublicBoard: true,
            publicUrl: manager.publicBoardShareUrl || '',
            isPublicPage: true,
            showLoginCta: !window.currentUser,
          });
          clearInterval(hydrateInterval);
          return;
        }

        if (attempts >= maxAttempts) {
          clearInterval(hydrateInterval);
        }
      }, 150);
    }
  }

  buildStatusWidgetTooltipText() {
    const statusLabel = this.statusText ? (this.statusText.textContent || '').trim() : '';
    const versionLabel = this.versionInfo ? (this.versionInfo.textContent || '').trim() : '';
    const lines = [];

    if (statusLabel) {
      lines.push(statusLabel);
    }
    if (versionLabel) {
      lines.push(versionLabel);
    }
    lines.push('More info: Open System Info');

    return lines.join(' | ');
  }

  refreshStatusWidgetPresentation() {
    const dbStatus = document.querySelector('.db-status');
    if (!dbStatus || !this.statusIcon || !this.statusText) {
      return;
    }

    const isHealthy = this.statusIcon.classList.contains('success');
    const tooltipText = this.buildStatusWidgetTooltipText();

    dbStatus.setAttribute('role', 'button');
    dbStatus.setAttribute('tabindex', '0');
    dbStatus.setAttribute('aria-label', tooltipText);
    dbStatus.setAttribute('title', tooltipText);

    if (isHealthy) {
      dbStatus.classList.add('status-compact');
    } else {
      dbStatus.classList.remove('status-compact');
    }
  }

  initializeStatusWidgetPresentation() {
    if (!this.statusIcon || !this.statusText) {
      return;
    }

    if (this.statusPresentationObserver) {
      this.statusPresentationObserver.disconnect();
      this.statusPresentationObserver = null;
    }

    this.statusPresentationObserver = new MutationObserver(() => {
      this.refreshStatusWidgetPresentation();
    });

    this.statusPresentationObserver.observe(this.statusIcon, {
      attributes: true,
      attributeFilter: ['class']
    });
    this.statusPresentationObserver.observe(this.statusText, {
      childList: true,
      characterData: true,
      subtree: true
    });

    if (this.versionInfo) {
      this.statusPresentationObserver.observe(this.versionInfo, {
        childList: true,
        characterData: true,
        subtree: true
      });
    }

    this.refreshStatusWidgetPresentation();
  }

  /**
   * Monitor WebSocket connection status with periodic checks and event listeners.
   * 
   * Polls WebSocket status every 5 seconds to detect disconnections.
   * Also listens for connect/disconnect events to update immediately.
   * On initial page load, don't report connecting sockets as failed.
   */
  /**
   * Monitor WebSocket connection status with periodic checks and event listeners.
   * 
   * Sets up two mechanisms for status updates:
   * 1. Periodic polling every 5 seconds (fallback for all scenarios)
   * 2. Real-time event listeners via WebSocketManager.onSocketCreated callback
   *    (only works if wsManager exists before or shortly after this is called)
   * 
   * The callback pattern allows header.js to get immediate socket events without
   * waiting for the 5-second polling interval. The callback is set on wsManager.onSocketCreated
   * which the WebSocketManager checks and invokes when socket is created.
   */
  monitorWebSocketConnection() {
    // Check WebSocket status every 5 seconds
    this.wsCheckInterval = setInterval(() => {
      this.checkWebSocketStatusWithInitialDelay();
    }, 5000);
    
    // Attempt to attach event listener callback if wsManager already exists
    // (this works if board page has already initialized)
    this.attachWebSocketCallback();
    
    // Also set up a watcher to attach callback when wsManager becomes available
    // (this handles cases where header loads before board page initializes wsManager)
    this.watchForWebSocketManager();
  }

  /**
   * Attach socket event listeners via wsManager callback pattern.
   * Safe to call multiple times - only attaches if wsManager exists and callback not yet set.
   */
  attachWebSocketCallback() {
    if (window.boardManager && window.boardManager.wsManager) {
      const wsManager = window.boardManager.wsManager;
      // Only set callback if it hasn't been set already (avoid overwriting)
      if (!wsManager.onSocketCreated) {
        wsManager.onSocketCreated = (socket) => {
          socket.on('connect', () => {
            this.updateWebSocketStatus();
          });
          socket.on('disconnect', () => {
            this.updateWebSocketStatus();
          });
        };
      }
    }
  }

  /**
   * Watch for wsManager to become available and attach callback when it does.
   * Uses a polling approach since we can't rely on event listeners at this stage.
   */
  watchForWebSocketManager() {
    let attempts = 0;
    const maxAttempts = 50; // Watch for up to ~5 seconds (5000ms / 100ms per check)
    
    const watchInterval = setInterval(() => {
      attempts++;
      if (window.boardManager && window.boardManager.wsManager) {
        this.attachWebSocketCallback();
        clearInterval(watchInterval); // Found it, stop watching
      } else if (attempts >= maxAttempts) {
        clearInterval(watchInterval); // Give up after max attempts
      }
    }, 100); // Check every 100ms
  }

  /**
   * Check WebSocket status with awareness of initial page load.
   * 
   * On initial page load, don't mark a "connecting" socket as an error.
   * Only mark as error if socket exists and is clearly disconnected (not connecting).
   */
  checkWebSocketStatusWithInitialDelay() {
    const { wsHealthy, wsConnecting, ...rest } = this._getWebSocketConnectionState();
    
    // Track state changes by comparing individual properties
    const newState = { ...rest, wsHealthy, wsConnecting };
    
    // Only update if state actually changed (not on every 5s interval)
    const stateChanged = !this.lastWsState || 
                        this.lastWsState.hasSocket !== newState.hasSocket ||
                        this.lastWsState.wsHealthy !== newState.wsHealthy ||
                        this.lastWsState.wsConnecting !== newState.wsConnecting;
    
    if (stateChanged) {
      this.lastWsState = newState;
      this.updateWebSocketStatus();
    }
  }

  /**
   * Update WebSocket connection status by checking available sockets.
   * 
   * Checks for board manager socket or theme builder socket.
   * Only shows error if socket exists and is not connecting and not healthy.
   */
  _getWebSocketConnectionState() {
    // Only check WebSocket if socket.io is actually loaded on this page
    if (typeof io === 'undefined') {
      // Socket.io not loaded on this page - that's OK
      return { hasSocket: false, wsHealthy: false, wsConnecting: false, ioLoaded: false };
    }
    
    // Socket.IO is loaded on this page, so check for actual sockets
    // Check for board manager socket OR theme builder socket
    const boardSocket = (window.boardManager && 
                         window.boardManager.wsManager && 
                         window.boardManager.wsManager.socket);
    const boardSocketConnected = boardSocket && boardSocket.connected;
    
    const themeSocket = window.AFT?.themeBuilderSocket || window.themeBuilderSocket;
    const themeSocketConnected = themeSocket && themeSocket.connected;
    
    // Check if either socket is connecting
    // A socket is "connecting" if it exists but is not connected and not explicitly disconnected
    // Socket.IO's internal state handles reconnection automatically
    const boardSocketConnecting = boardSocket && !boardSocketConnected && 
                                  boardSocket.io?.engine?.readyState && 
                                  boardSocket.io.engine.readyState !== 'closed';
    const themeSocketConnecting = themeSocket && !themeSocketConnected && 
                                  themeSocket.io?.engine?.readyState && 
                                  themeSocket.io.engine.readyState !== 'closed';
    
    const hasSocket = !!boardSocket || !!themeSocket;
    const wsHealthy = boardSocketConnected || themeSocketConnected;
    const wsConnecting = boardSocketConnecting || themeSocketConnecting;
    
    return { hasSocket, wsHealthy, wsConnecting, ioLoaded: true };
  }

  updateWebSocketStatus() {
    const { hasSocket, wsHealthy, wsConnecting, ioLoaded } = this._getWebSocketConnectionState();
    
    this.wsConnected = wsHealthy;
    
    // If Socket.IO library failed to load on a page that needs it, show error
    // Note: REST API calls still work without WebSocket, so don't block card operations
    if (ioLoaded && !hasSocket && !wsConnecting) {
      this.statusIcon.className = 'status-icon error';
      this.statusText.textContent = 'WebSocket Disconnected';
      this.statusText.title = 'Real-time updates are unavailable. Board changes will not sync in real-time. Try force reloading (Ctrl+Shift+R).';
      // Note: Don't modify dbConnected here - this method doesn't verify server/DB health
      // Only checkDatabaseStatus() can safely set dbConnected=true after verifying server is reachable
      return;
    }
    
    // Only show connection error if socket exists and is not connecting and is not healthy
    // Note: REST API calls and card creation still work without WebSocket
    if (hasSocket && !wsHealthy && !wsConnecting) {
      this.statusIcon.className = 'status-icon error';
      this.statusText.textContent = 'WebSocket Disconnected';
      this.statusText.title = 'Real-time updates are unavailable. Board changes will not sync in real-time. Try force reloading (Ctrl+Shift+R).';
      // Note: Don't modify dbConnected here - this method doesn't verify server/DB health
      // Only checkDatabaseStatus() can safely set dbConnected=true after verifying server is reachable
    }
  }

  // Set the board name in the header
  setBoardName(boardName) {
    const navBoardNameText = document.getElementById('nav-board-name-text');
    const mobileBoardNameText = document.getElementById('header-mobile-board-name');

    if (mobileBoardNameText) {
      mobileBoardNameText.textContent = boardName || 'Board';
      mobileBoardNameText.setAttribute('title', boardName || 'Board');
    }

    if (navBoardNameText) {
      if (boardName) {
        navBoardNameText.textContent = boardName;
        document.title = `AFT - ${boardName}`;
      } else {
        navBoardNameText.textContent = '';
        document.title = 'AFT';
      }
    }
  }

  setPublicBoardContext(options = {}) {
    const {
      isPublicBoard = false,
      publicUrl = '',
      isPublicPage = false,
      showLoginCta = false,
    } = options;

    const useMinimalPublicChrome = isPublicPage === true;
    const headerEl = document.querySelector('.header');
    if (headerEl) {
      headerEl.classList.toggle('header-public-board', useMinimalPublicChrome);
    }

    const selectorsToHideInMinimalMode = [
      '.boards-dropdown',
      '.notifications-dropdown',
      '.settings-dropdown',
      '.user-dropdown',
      '.db-status'
    ];

    selectorsToHideInMinimalMode.forEach((selector) => {
      const element = document.querySelector(selector);
      if (element) {
        element.style.display = useMinimalPublicChrome ? 'none' : '';
      }
    });

    const mobileToggle = document.getElementById('mobile-menu-toggle');
    if (mobileToggle) {
      mobileToggle.style.display = useMinimalPublicChrome ? 'none' : '';
    }

    const shouldShowPublicBadge = isPublicBoard && !!window.currentUser;
    this.ensurePublicBoardBadge(shouldShowPublicBadge, publicUrl);
    this.ensureMobilePublicBoardBadge(shouldShowPublicBadge && !useMinimalPublicChrome, publicUrl);
    this.ensurePublicBoardLoginCta(useMinimalPublicChrome && showLoginCta);
  }

  ensurePublicBoardBadge(showBadge, publicUrl) {
    const navBoardName = document.querySelector('.nav-board-name');
    if (!navBoardName) {
      return;
    }

    let badgeButton = document.getElementById('public-board-badge-btn');
    if (!badgeButton) {
      badgeButton = document.createElement('button');
      badgeButton.id = 'public-board-badge-btn';
      badgeButton.type = 'button';
      badgeButton.className = 'public-board-badge-btn';
      badgeButton.setAttribute('aria-label', 'Copy public board link');
      badgeButton.textContent = 'Public: Copy Share Link';
      navBoardName.appendChild(badgeButton);
    }

    this.applyPublicLinkBadgeState(badgeButton, showBadge, publicUrl);
  }

  ensureMobilePublicBoardBadge(showBadge, publicUrl) {
    const headerRight = document.querySelector('.header-right');
    if (!headerRight) {
      return;
    }

    let badgeButton = document.getElementById('public-board-badge-mobile-btn');
    if (!badgeButton) {
      badgeButton = document.createElement('button');
      badgeButton.id = 'public-board-badge-mobile-btn';
      badgeButton.type = 'button';
      badgeButton.className = 'public-board-badge-btn public-board-badge-mobile-btn';
      badgeButton.setAttribute('aria-label', 'Copy public board link');
      badgeButton.textContent = 'Copy Link';
      const mobileToggle = document.getElementById('mobile-menu-toggle');
      if (mobileToggle && mobileToggle.parentElement === headerRight) {
        headerRight.insertBefore(badgeButton, mobileToggle);
      } else {
        headerRight.appendChild(badgeButton);
      }
    }

    this.applyPublicLinkBadgeState(badgeButton, showBadge, publicUrl);
  }

  applyPublicLinkBadgeState(badgeButton, showBadge, publicUrl) {
    if (!badgeButton) {
      return;
    }

    if (!showBadge || !publicUrl) {
      badgeButton.style.display = 'none';
      badgeButton.onclick = null;
      return;
    }

    // Clear inline style so responsive CSS controls visibility (desktop vs mobile).
    badgeButton.style.display = '';
    badgeButton.onclick = async () => {
      try {
        await navigator.clipboard.writeText(publicUrl);
        this.showHeaderToast('Public board link copied to clipboard');
      } catch (error) {
        this.showHeaderToast('Unable to copy link automatically', true);
      }
    };
  }

  ensurePublicBoardLoginCta(showLoginCta) {
    const headerRight = document.querySelector('.header-right');
    if (!headerRight) {
      return;
    }

    let loginLink = document.getElementById('public-board-login-link');
    if (!loginLink) {
      loginLink = document.createElement('a');
      loginLink.id = 'public-board-login-link';
      loginLink.className = 'header-link public-board-login-link';
      loginLink.textContent = 'Login';
      headerRight.insertBefore(loginLink, headerRight.firstChild);
    }

    if (!showLoginCta) {
      loginLink.style.display = 'none';
      loginLink.onclick = null;
      return;
    }

    const redirectPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    loginLink.href = '/login.html';
    loginLink.onclick = () => {
      // Keep redirect behavior aligned with login.js expectations.
      sessionStorage.setItem('redirectAfterLogin', redirectPath);
    };
    loginLink.style.display = 'inline-flex';
  }

  showHeaderToast(message, isError = false) {
    const toast = document.createElement('div');
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    toast.className = 'header-inline-toast';
    toast.textContent = message;
    toast.style.background = isError ? 'var(--error-color)' : 'var(--success-color)';

    document.body.appendChild(toast);

    setTimeout(() => {
      toast.classList.add('fade-out');
      setTimeout(() => toast.remove(), 220);
    }, 2200);
  }

  // Show or hide the views dropdown
  showViewsDropdown(show) {
    const viewsDropdown = document.getElementById('views-dropdown');
    if (viewsDropdown) {
      viewsDropdown.style.display = show ? 'block' : 'none';
    }

    this.syncMobileViewVisibility(show);
  }

  // Keep mobile view section visibility aligned with desktop view control state
  syncMobileViewVisibility(show) {
    const mobileViewsSection = document.getElementById('mobile-views-section');
    if (mobileViewsSection) {
      mobileViewsSection.style.display = show ? '' : 'none';
    }
  }

  // Initialize mobile drawer menu interactions
  initializeMobileMenu() {
    const header = document.querySelector('.header');
    const toggleBtn = document.getElementById('mobile-menu-toggle');
    const closeBtn = document.getElementById('mobile-menu-close');
    const overlay = document.getElementById('mobile-menu-overlay');
    const drawer = document.getElementById('mobile-menu-drawer');

    if (!header || !toggleBtn || !closeBtn || !overlay || !drawer) {
      return;
    }

    const openMenu = () => {
      header.classList.add('mobile-menu-open');
      document.body.classList.add('mobile-menu-open');
      toggleBtn.setAttribute('aria-expanded', 'true');
    };

    const closeMenu = () => {
      header.classList.remove('mobile-menu-open');
      document.body.classList.remove('mobile-menu-open');
      toggleBtn.setAttribute('aria-expanded', 'false');
    };

    toggleBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (header.classList.contains('mobile-menu-open')) {
        closeMenu();
      } else {
        openMenu();
      }
    });

    closeBtn.addEventListener('click', closeMenu);
    overlay.addEventListener('click', closeMenu);

    // Auto-close drawer after selecting a menu option
    drawer.addEventListener('click', (e) => {
      const target = e.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }

      if (target.matches('a.mobile-menu-link, button.mobile-menu-link, a.mobile-notification-link')) {
        closeMenu();
      }
    });

    // Close on escape and when returning to desktop layout
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && header.classList.contains('mobile-menu-open')) {
        closeMenu();
      }
    });

    window.addEventListener('resize', () => {
      if (window.innerWidth > this.mobileBreakpoint) {
        closeMenu();
      }
    });

    // Handle mobile view actions
    drawer.querySelectorAll('.mobile-view-item').forEach(item => {
      item.addEventListener('click', (e) => {
        const view = e.currentTarget.dataset.view;
        if (!view) {
          return;
        }
        this.setView(view);
        closeMenu();
      });
    });

    // Hook mobile logout button into existing logout flow
    const mobileLogoutItem = document.getElementById('mobile-logout-menu-item');
    if (mobileLogoutItem) {
      mobileLogoutItem.addEventListener('click', () => {
        closeMenu();
        this.handleLogout();
      });
    }
  }

  // Initialize mobile notifications section and sync it with notifications.js state
  initializeMobileNotifications() {
    const markAllReadBtn = document.getElementById('mobile-mark-all-read-btn');

    if (markAllReadBtn) {
      markAllReadBtn.addEventListener('click', async () => {
        if (window.notifications && typeof window.notifications.markAllAsRead === 'function') {
          await window.notifications.markAllAsRead();
          this.renderMobileNotifications(window.notifications.notifications || []);
        }
      });
    }

    window.addEventListener('notificationsUpdated', (e) => {
      const notifications = e.detail?.notifications || [];
      this.renderMobileNotifications(notifications);
    });

    if (window.notifications) {
      this.renderMobileNotifications(window.notifications.notifications || []);
    }
  }

  // Toggle mobile notification card read state using shared notifications component logic
  toggleMobileNotificationRead(card, notificationId, isCurrentlyUnread) {
    if (!card || !(card instanceof HTMLElement)) {
      return;
    }

    card.classList.toggle('unread', !isCurrentlyUnread);
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.setAttribute('aria-label', isCurrentlyUnread ? 'Mark notification as unread' : 'Mark notification as read');

    if (window.notifications && typeof window.notifications.toggleRead === 'function') {
      window.notifications.toggleRead(notificationId, isCurrentlyUnread);
    } else if (isCurrentlyUnread && window.notifications && typeof window.notifications.markAsRead === 'function') {
      // Fallback for compatibility if toggleRead is unavailable.
      window.notifications.markAsRead(notificationId, true);
    }
  }

  // Build mobile notification cards and unread badge for the drawer
  renderMobileNotifications(notifications) {
    const mobileMenu = document.getElementById('mobile-notifications-menu');
    const badge = document.getElementById('mobile-notification-badge');
    const toggleDot = document.getElementById('mobile-menu-toggle-dot');
    const markAllReadBtn = document.getElementById('mobile-mark-all-read-btn');

    if (!mobileMenu || !badge || !markAllReadBtn) {
      return;
    }

    const allNotifications = Array.isArray(notifications) ? notifications : [];
    const unreadCount = allNotifications.filter(n => n.unread).length;

    if (unreadCount > 0) {
      badge.textContent = unreadCount > 9 ? '9+' : String(unreadCount);
      badge.style.display = 'inline-block';
      if (toggleDot) {
        toggleDot.style.display = 'inline-block';
      }
    } else {
      badge.style.display = 'none';
      if (toggleDot) {
        toggleDot.style.display = 'none';
      }
    }

    if (allNotifications.length > 0) {
      markAllReadBtn.style.display = '';
      markAllReadBtn.textContent = unreadCount === 0 ? 'Delete all' : 'Mark all read';
    } else {
      markAllReadBtn.style.display = 'none';
    }

    mobileMenu.innerHTML = '';

    if (allNotifications.length === 0) {
      mobileMenu.innerHTML = '<div class="mobile-menu-loading">No notifications</div>';
      return;
    }

    const sortedNotifications = [...allNotifications].sort((a, b) => {
      return new Date(b.created_at) - new Date(a.created_at);
    });

    sortedNotifications.slice(0, 10).forEach(notification => {
      const item = document.createElement('div');
      item.className = `mobile-notification-item${notification.unread ? ' unread' : ''}`;
      item.dataset.notificationId = String(notification.id);

      item.setAttribute('role', 'button');
      item.setAttribute('tabindex', '0');
      item.setAttribute('aria-label', notification.unread ? 'Mark notification as read' : 'Mark notification as unread');

      const handleCardActivate = (e) => {
        if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') {
          return;
        }
        if (e.target && e.target.closest('.mobile-notification-link')) {
          return;
        }
        if (e.type === 'keydown') {
          e.preventDefault();
        }
        const isUnread = item.classList.contains('unread');
        this.toggleMobileNotificationRead(item, notification.id, isUnread);
      };
      item.addEventListener('click', handleCardActivate);
      item.addEventListener('keydown', handleCardActivate);

      const subject = document.createElement('div');
      subject.className = 'mobile-notification-subject';
      subject.textContent = notification.subject || '';

      const message = document.createElement('div');
      message.className = 'mobile-notification-message';
      message.textContent = notification.message || '';

      const meta = document.createElement('div');
      meta.className = 'mobile-notification-meta';

      const time = document.createElement('div');
      time.className = 'mobile-notification-time';
      time.textContent = this.formatRelativeTime(notification.created_at);
      meta.appendChild(time);

      const hasAction = notification.action_title && notification.action_url && this.isSafeMobileUrl(notification.action_url);
      if (hasAction) {
        const actionLink = document.createElement('a');
        actionLink.className = 'mobile-notification-link';
        actionLink.href = notification.action_url;
        actionLink.textContent = notification.action_title;
        if (notification.unread && window.notifications && typeof window.notifications.markAsRead === 'function') {
          actionLink.addEventListener('click', () => {
            window.notifications.markAsRead(notification.id, true);
          });
        }
        meta.appendChild(actionLink);
      }

      item.appendChild(subject);
      item.appendChild(message);
      item.appendChild(meta);
      mobileMenu.appendChild(item);
    });
  }

  // Restrict actionable notification links to safe protocols
  isSafeMobileUrl(url) {
    if (!url || typeof url !== 'string') {
      return false;
    }

    const normalized = url.trim().toLowerCase();
    return normalized.startsWith('/') || normalized.startsWith('http://') || normalized.startsWith('https://');
  }

  // Format notification timestamps for compact mobile cards
  formatRelativeTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) {
      return 'Just now';
    }
    if (diffMins < 60) {
      return `${diffMins}m ago`;
    }
    if (diffHours < 24) {
      return `${diffHours}h ago`;
    }
    if (diffDays < 7) {
      return `${diffDays}d ago`;
    }
    return date.toLocaleDateString();
  }

  // Load current user info
  async loadCurrentUser() {
    try {
      const userNameEl = document.getElementById('header-user-name');
      const mobileUserNameEl = document.getElementById('mobile-header-user-name');
      const loginItem = document.getElementById('login-menu-item');
      const mobileLoginItem = document.getElementById('mobile-login-menu-item');
      const logoutItem = document.getElementById('logout-menu-item');
      const mobileLogoutItem = document.getElementById('mobile-logout-menu-item');
      
      // Check sessionStorage cache first to avoid API calls on every page load
      const cachedUser = sessionStorage.getItem('currentUser');
      if (cachedUser) {
        try {
          const userData = JSON.parse(cachedUser);
          // Use cached data
          window.currentUser = userData;
          
          const displayName = userData.display_name || userData.username || userData.email;
          if (userNameEl) userNameEl.textContent = displayName;
          if (mobileUserNameEl) mobileUserNameEl.textContent = displayName;
          if (loginItem) loginItem.style.display = 'none';
          if (mobileLoginItem) mobileLoginItem.style.display = 'none';
          if (logoutItem) {
            logoutItem.style.display = 'block';
            // Add logout handler
            logoutItem.addEventListener('click', () => this.handleLogout());
          }
          if (mobileLogoutItem) {
            mobileLogoutItem.style.display = 'block';
          }
          
          // Filter menu items based on permissions
          this.filterMenuByPermissions();
          
          // Mark user data as ready
          window.userDataReady = true;
          return; // Use cache, skip API call
        } catch (e) {
          // Invalid cache, remove it and fetch fresh
          sessionStorage.removeItem('currentUser');
        }
      }
      
      // No cache or invalid cache - fetch from API
      const response = await fetch('/api/auth/me');
      
      if (response.ok) {
        const data = await response.json();
        if (data.user) {
          // User is logged in - store globally and in cache
          window.currentUser = data.user;
          sessionStorage.setItem('currentUser', JSON.stringify(data.user));
          
          const displayName = data.user.display_name || data.user.username || data.user.email;
          if (userNameEl) userNameEl.textContent = displayName;
          if (mobileUserNameEl) mobileUserNameEl.textContent = displayName;
          if (loginItem) loginItem.style.display = 'none';
          if (mobileLoginItem) mobileLoginItem.style.display = 'none';
          if (logoutItem) {
            logoutItem.style.display = 'block';
            // Add logout handler
            logoutItem.addEventListener('click', () => this.handleLogout());
          }
          if (mobileLogoutItem) {
            mobileLogoutItem.style.display = 'block';
          }
          
          // Filter menu items based on permissions
          this.filterMenuByPermissions();
          
          // Mark user data as ready
          window.userDataReady = true;
          return;
        }
      }
      
      // User is not logged in or error occurred
      window.currentUser = null;
      sessionStorage.removeItem('currentUser');
      if (userNameEl) userNameEl.textContent = 'Guest';
      if (mobileUserNameEl) mobileUserNameEl.textContent = 'Guest';
      if (loginItem) loginItem.style.display = 'block';
      if (mobileLoginItem) mobileLoginItem.style.display = 'block';
      if (logoutItem) logoutItem.style.display = 'none';
      if (mobileLogoutItem) mobileLogoutItem.style.display = 'none';
      
      // Hide permission-protected menu items
      this.filterMenuByPermissions();
      
      // Mark user data as ready (even if not logged in)
      window.userDataReady = true;
    } catch (error) {
      console.error('Error loading current user:', error);
      // Show guest on error
      window.currentUser = null;
      sessionStorage.removeItem('currentUser');
      const userNameEl = document.getElementById('header-user-name');
      const mobileUserNameEl = document.getElementById('mobile-header-user-name');
      if (userNameEl) userNameEl.textContent = 'Guest';
      if (mobileUserNameEl) mobileUserNameEl.textContent = 'Guest';
      const loginItem = document.getElementById('login-menu-item');
      const mobileLoginItem = document.getElementById('mobile-login-menu-item');
      const logoutItem = document.getElementById('logout-menu-item');
      const mobileLogoutItem = document.getElementById('mobile-logout-menu-item');
      if (loginItem) loginItem.style.display = 'block';
      if (mobileLoginItem) mobileLoginItem.style.display = 'block';
      if (logoutItem) logoutItem.style.display = 'none';
      if (mobileLogoutItem) mobileLogoutItem.style.display = 'none';
      
      // Hide permission-protected menu items
      this.filterMenuByPermissions();
      
      // Mark user data as ready (even on error)
      window.userDataReady = true;
    }
  }

  // Filter menu items based on user permissions
  filterMenuByPermissions() {
    // Menu items and their required permissions
    const protectedItems = [
      {
        selectors: ['a[href="/backup-restore.html"]'],
        permission: 'admin.database'
      },
      {
        selectors: ['a[href="/user-management.html"]'],
        permissions: ['user.manage', 'user.role'],
        requireAny: true
      },
      {
        selectors: ['a[href="/role-management.html"]'],
        permission: 'role.manage'
      }
    ];
    
    protectedItems.forEach(item => {
      const selectors = item.selectors || (item.selector ? [item.selector] : []);
      const menuItems = selectors.flatMap(selector => Array.from(document.querySelectorAll(selector)));
      if (menuItems.length > 0) {
        let hasAccess = false;
        
        // Check if user has permission (hasPermission is defined in utils.js)
        if (item.permissions && item.requireAny) {
          // User needs ANY of the listed permissions
          hasAccess = item.permissions.some(perm => 
            typeof hasPermission === 'function' && hasPermission(perm)
          );
        } else if (item.permission) {
          // User needs the single permission
          hasAccess = typeof hasPermission === 'function' && hasPermission(item.permission);
        }
        
        menuItems.forEach(menuItem => {
          if (hasAccess) {
            menuItem.style.display = '';  // Show
          } else {
            menuItem.style.display = 'none';  // Hide
          }
        });
      }
    });
  }

  // Handle logout
  async handleLogout() {
    try {
      // Clear cached user data
      sessionStorage.removeItem('currentUser');
      window.currentUser = null;
      window.userDataReady = false;
      
      const response = await fetch('/api/auth/logout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      
      // Redirect to logout page regardless of response
      window.location.href = '/logout.html';
    } catch (error) {
      console.error('Error logging out:', error);
      // Still redirect to logout page
      window.location.href = '/logout.html';
    }
  }

  // Load working style preference
  async loadWorkingStyle() {
    const normalize = (value) => {
      if (value === 'board_task_category') {
        return 'agile';
      }
      return value === 'agile' ? 'agile' : 'kanban';
    };

    const boardId = this.getCurrentBoardId();
    this.currentBoardId = boardId;

    // Public board pages derive working style from the board payload in board.js.
    // Avoid overriding it here with user/default settings.
    if (this.isPublicBoardPage) {
      this.boardStyleEditable = false;
      this.updateViewsDropdown();
      return;
    }

    try {
      if (boardId) {
        const response = await fetch(`/api/boards/${boardId}/settings/working-style`);
        if (response.ok) {
          const data = await response.json();
          if (data.success) {
            this.workingStyle = normalize(data.value);
            this.boardStyleEditable = !!data.can_edit;
            this.updateViewsDropdown();
            return;
          }
        }

        // Board endpoint failed; default to kanban for board-scoped UI
        // (do not fall back to user default as that can misconfigure the board UI)
        this.workingStyle = 'kanban';
        this.boardStyleEditable = false;
        this.updateViewsDropdown();
        return;
      }

      const response = await fetch('/api/settings/working-style');
      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          this.workingStyle = normalize(data.value);
          this.updateViewsDropdown();
        }
      }
    } catch (error) {
      console.error('Error loading working style:', error);
      this.workingStyle = 'kanban';
      this.boardStyleEditable = false;
      this.updateViewsDropdown();
    }
  }

  getCurrentBoardId() {
    const isBoardPage = document.body.classList.contains('board-page');
    if (!isBoardPage) {
      return null;
    }

    const params = new URLSearchParams(window.location.search);
    const rawBoardId = params.get('id');
    const parsedBoardId = rawBoardId ? parseInt(rawBoardId, 10) : NaN;
    if (!Number.isFinite(parsedBoardId) || parsedBoardId <= 0) {
      return null;
    }

    return parsedBoardId;
  }

  initializeBoardStyleToggleMenu() {
    const menuItems = [
      document.getElementById('toggle-board-style-menu-item'),
      document.getElementById('mobile-toggle-board-style-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    if (!this.currentBoardId || !this.boardStyleEditable) {
      menuItems.forEach((menuItem) => {
        menuItem.style.display = 'none';
      });
      return;
    }

    menuItems.forEach((menuItem) => {
      menuItem.style.display = '';
    });
    this.updateBoardStyleMenuLabel();

    menuItems.forEach((menuItem) => {
      if (!menuItem.dataset.boundStyleToggleHandler) {
        menuItem.addEventListener('click', async (e) => {
          e.preventDefault();
          await this.toggleBoardStyle();
          closeAllMenusExcept(null);
          updateMenuHoverState();
        });
        menuItem.dataset.boundStyleToggleHandler = 'true';
      }
    });
  }

  getPublicBoardShareUrl(slug) {
    if (typeof slug !== 'string' || slug.trim().length === 0) {
      return '';
    }

    return `${window.location.origin}/public-board.html?slug=${encodeURIComponent(slug)}`;
  }

  getPublicBoardEmbedCode(slug) {
    const publicUrl = this.getPublicBoardShareUrl(slug);
    if (!publicUrl) {
      return '';
    }

    return [
      '<iframe',
      `  src="${publicUrl}"`,
      '  title="AFT Public Board"',
      '  width="100%"',
      '  height="900"',
      '  style="border:0;"',
      '  loading="lazy"',
      '  referrerpolicy="strict-origin-when-cross-origin">',
      '</iframe>'
    ].join('\n');
  }

  initializeBoardVisibilityToggleMenu() {
    const menuItems = [
      document.getElementById('toggle-board-visibility-menu-item'),
      document.getElementById('mobile-toggle-board-visibility-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    if (!this.currentBoardId || this.isPublicBoardPage) {
      menuItems.forEach((menuItem) => {
        menuItem.style.display = 'none';
      });
      return;
    }

    if (!this.boardOwnerDataListenerBound) {
      window.addEventListener('boardOwnerDataLoaded', this.boardOwnerDataLoadedHandler);
      this.boardOwnerDataListenerBound = true;
    }

    if (window.boardManager && window.boardManager.boardId === this.currentBoardId) {
      this.hydrateBoardVisibilityState({
        can_edit: window.boardManager.canEdit === true,
        is_public: window.boardManager.isBoardPublic === true,
        public_slug: window.boardManager.publicSlug || null,
      });
    }

    menuItems.forEach((menuItem) => {
      if (!menuItem.dataset.boundVisibilityToggleHandler) {
        menuItem.addEventListener('click', async (e) => {
          e.preventDefault();
          await this.toggleBoardVisibility();
          closeAllMenusExcept(null);
          updateMenuHoverState();
        });
        menuItem.dataset.boundVisibilityToggleHandler = 'true';
      }
    });

    this.updateBoardVisibilityMenuState();
  }

  initializeBoardArchiveToggleMenu() {
    const menuItems = [
      document.getElementById('archive-board-menu-item'),
      document.getElementById('mobile-archive-board-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    if (!this.currentBoardId || this.isPublicBoardPage) {
      menuItems.forEach((menuItem) => {
        menuItem.style.display = 'none';
      });
      return;
    }

    if (!this.boardOwnerDataListenerBound) {
      window.addEventListener('boardOwnerDataLoaded', this.boardOwnerDataLoadedHandler);
      this.boardOwnerDataListenerBound = true;
    }

    if (window.boardManager && window.boardManager.boardId === this.currentBoardId) {
      this.hydrateBoardArchiveState({ archived: window.boardManager.boardArchived === true });
    }

    menuItems.forEach((menuItem) => {
      if (!menuItem.dataset.boundArchiveToggleHandler) {
        menuItem.addEventListener('click', async (e) => {
          e.preventDefault();
          await this.toggleBoardArchive();
          closeAllMenusExcept(null);
          updateMenuHoverState();
        });
        menuItem.dataset.boundArchiveToggleHandler = 'true';
      }
    });

    this.updateBoardArchiveMenuState();
  }

  initializeRotatePublicLinkMenu() {
    const menuItems = [
      document.getElementById('rotate-public-link-menu-item'),
      document.getElementById('mobile-rotate-public-link-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    if (!this.currentBoardId || this.isPublicBoardPage) {
      menuItems.forEach((menuItem) => {
        menuItem.style.display = 'none';
      });
      return;
    }

    if (!this.boardOwnerDataListenerBound) {
      window.addEventListener('boardOwnerDataLoaded', this.boardOwnerDataLoadedHandler);
      this.boardOwnerDataListenerBound = true;
    }

    menuItems.forEach((menuItem) => {
      if (!menuItem.dataset.boundRotatePublicLinkHandler) {
        menuItem.addEventListener('click', async (e) => {
          e.preventDefault();
          await this.rotatePublicLink();
          closeAllMenusExcept(null);
          updateMenuHoverState();
        });
        menuItem.dataset.boundRotatePublicLinkHandler = 'true';
      }
    });

    this.updateRotatePublicLinkMenuVisibility();
  }

  initializeCopyEmbedCodeMenu() {
    const menuItems = [
      document.getElementById('copy-embed-code-menu-item'),
      document.getElementById('mobile-copy-embed-code-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    if (!this.currentBoardId || this.isPublicBoardPage) {
      menuItems.forEach((menuItem) => {
        menuItem.style.display = 'none';
      });
      return;
    }

    if (!this.boardOwnerDataListenerBound) {
      window.addEventListener('boardOwnerDataLoaded', this.boardOwnerDataLoadedHandler);
      this.boardOwnerDataListenerBound = true;
    }

    menuItems.forEach((menuItem) => {
      if (!menuItem.dataset.boundCopyEmbedCodeHandler) {
        menuItem.addEventListener('click', async (e) => {
          e.preventDefault();
          await this.copyPublicBoardEmbedCode();
          closeAllMenusExcept(null);
          updateMenuHoverState();
        });
        menuItem.dataset.boundCopyEmbedCodeHandler = 'true';
      }
    });

    this.updateCopyEmbedCodeMenuVisibility();
  }

  hydrateBoardVisibilityState(detail) {
    if (!detail) {
      return;
    }

    this.boardVisibilityEditable = detail.can_edit === true;
    this.boardIsPublic = detail.is_public === true;
    this.boardPublicSlug = typeof detail.public_slug === 'string' && detail.public_slug.length > 0
      ? detail.public_slug
      : null;

    this.updateBoardVisibilityMenuState();
    this.updateRotatePublicLinkMenuVisibility();
    this.updateCopyEmbedCodeMenuVisibility();

    this.setPublicBoardContext({
      isPublicBoard: this.boardIsPublic,
      publicUrl: this.getPublicBoardShareUrl(this.boardPublicSlug),
      isPublicPage: this.isPublicBoardPage,
      showLoginCta: this.isPublicBoardPage && !window.currentUser,
    });
  }

  hydrateBoardArchiveState(detail) {
    if (!detail) {
      return;
    }

    this.boardArchived = detail.archived === true;
    this.updateBoardArchiveMenuState();
  }

  updateBoardVisibilityMenuState() {
    const menuItems = [
      document.getElementById('toggle-board-visibility-menu-item'),
      document.getElementById('mobile-toggle-board-visibility-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    const visible = !!this.currentBoardId && !this.isPublicBoardPage && this.boardVisibilityEditable;
    const label = this.boardIsPublic ? 'Access: Public' : 'Access: Private';

    menuItems.forEach((menuItem) => {
      menuItem.style.display = visible ? '' : 'none';
      menuItem.textContent = label;
    });
  }

  updateRotatePublicLinkMenuVisibility() {
    const menuItems = [
      document.getElementById('rotate-public-link-menu-item'),
      document.getElementById('mobile-rotate-public-link-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    const visible = !!this.currentBoardId
      && !this.isPublicBoardPage
      && this.boardVisibilityEditable
      && this.boardIsPublic
      && !!this.boardPublicSlug;

    menuItems.forEach((menuItem) => {
      menuItem.style.display = visible ? '' : 'none';
    });
  }

  updateCopyEmbedCodeMenuVisibility() {
    const menuItems = [
      document.getElementById('copy-embed-code-menu-item'),
      document.getElementById('mobile-copy-embed-code-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    const visible = !!this.currentBoardId
      && !this.isPublicBoardPage
      && this.boardVisibilityEditable
      && this.boardIsPublic
      && !!this.boardPublicSlug;

    menuItems.forEach((menuItem) => {
      menuItem.style.display = visible ? '' : 'none';
    });
  }

  async copyPublicBoardEmbedCode() {
    if (!this.currentBoardId || !this.boardVisibilityEditable || !this.boardIsPublic || !this.boardPublicSlug) {
      return;
    }

    const embedCode = this.getPublicBoardEmbedCode(this.boardPublicSlug);
    if (!embedCode) {
      this.showBoardPageToast('Unable to generate embed code for this board.');
      return;
    }

    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        await navigator.clipboard.writeText(embedCode);
      } else {
        const textarea = document.createElement('textarea');
        try {
          textarea.value = embedCode;
          textarea.setAttribute('readonly', '');
          textarea.style.position = 'fixed';
          textarea.style.opacity = '0';
          document.body.appendChild(textarea);
          textarea.select();

          const copied = document.execCommand('copy');
          if (!copied) {
            throw new Error('document.execCommand(\'copy\') returned false');
          }
        } finally {
          textarea.remove();
        }
      }

      this.showHeaderToast('Embed code copied. If embedding fails, add the host origin to EMBED_ALLOWED_ORIGINS and restart nginx.');
    } catch (error) {
      console.error('Error copying embed code:', error);
      this.showBoardPageToast('Unable to copy embed code automatically.');
    }
  }

  async toggleBoardVisibility() {
    if (!this.currentBoardId || !this.boardVisibilityEditable || this.isPublicBoardPage) {
      return;
    }

    const nextPublicState = !this.boardIsPublic;

    if (nextPublicState) {
      const confirmed = await this.confirmMakeBoardPublic();
      if (!confirmed) {
        return;
      }
    } else {
      const confirmed = await this.confirmMakeBoardPrivate();
      if (!confirmed) {
        return;
      }
    }

    try {
      const response = await fetch(`/api/boards/${this.currentBoardId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ is_public: nextPublicState })
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.message || `HTTP error ${response.status}`);
      }

      const board = data.board || {};
      this.boardIsPublic = board.is_public === true;
      this.boardPublicSlug = typeof board.public_slug === 'string' && board.public_slug.length > 0
        ? board.public_slug
        : null;

      if (window.boardManager && window.boardManager.boardId === this.currentBoardId) {
        window.boardManager.isBoardPublic = this.boardIsPublic;
        window.boardManager.publicSlug = this.boardPublicSlug;
        window.boardManager.publicBoardShareUrl = this.getPublicBoardShareUrl(this.boardPublicSlug) || null;
      }

      this.updateBoardVisibilityMenuState();
      this.updateRotatePublicLinkMenuVisibility();
      this.updateCopyEmbedCodeMenuVisibility();
      this.setPublicBoardContext({
        isPublicBoard: this.boardIsPublic,
        publicUrl: this.getPublicBoardShareUrl(this.boardPublicSlug),
        isPublicPage: this.isPublicBoardPage,
        showLoginCta: this.isPublicBoardPage && !window.currentUser,
      });
      this.showHeaderToast(this.boardIsPublic ? 'Board is now public' : 'Board is now private');
    } catch (error) {
      console.error('Error toggling board visibility:', error);
      this.showBoardPageToast(error.message || 'Failed to update board visibility.');
    }
  }

  async toggleBoardArchive() {
    if (!this.currentBoardId || !this.boardVisibilityEditable || this.isPublicBoardPage) {
      return;
    }

    const targetArchived = !this.boardArchived;
    const confirmed = targetArchived
      ? await this.confirmArchiveBoard()
      : await this.confirmUnarchiveBoard();

    if (!confirmed) {
      return;
    }

    try {
      const response = await fetch(`/api/boards/${this.currentBoardId}/${targetArchived ? 'archive' : 'unarchive'}`, {
        method: 'PATCH'
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.message || `HTTP error ${response.status}`);
      }

      this.boardArchived = targetArchived;
      if (window.boardManager) {
        window.boardManager.boardArchived = targetArchived;
      }
      this.updateBoardArchiveMenuState();
      this.showHeaderToast(targetArchived ? 'Board archived' : 'Board unarchived');
    } catch (error) {
      console.error('Error updating board archive state:', error);
      this.showBoardPageToast(error.message || (targetArchived ? 'Failed to archive board.' : 'Failed to unarchive board.'));
    }
  }

  async confirmArchiveBoard() {
    return this.confirmBoardArchiveChange(
      'Archive Board?',
      'This will move the board to the archived boards view. You can unarchive it later.',
      'Archive Board'
    );
  }

  async confirmUnarchiveBoard() {
    return this.confirmBoardArchiveChange(
      'Unarchive Board?',
      'This will move the board back to the active boards view.',
      'Unarchive Board'
    );
  }

  async confirmBoardArchiveChange(titleText, descriptionText, confirmLabel) {
    const existingModal = document.getElementById('board-archive-confirm-modal');
    if (existingModal) {
      existingModal.remove();
    }

    return new Promise((resolve) => {
      const previousActiveElement = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
      const previousOverflow = document.body.style.overflow;

      const modal = document.createElement('div');
      modal.className = 'modal';
      modal.id = 'board-archive-confirm-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-labelledby', 'board-archive-confirm-title');
      modal.setAttribute('aria-describedby', 'board-archive-confirm-description');

      const modalContent = document.createElement('div');
      modalContent.className = 'modal-content board-owner-modal-content';

      const modalHeader = document.createElement('div');
      modalHeader.className = 'modal-header';

      const title = document.createElement('h2');
      title.id = 'board-archive-confirm-title';
      title.textContent = titleText;

      modalHeader.appendChild(title);

      const description = document.createElement('p');
      description.id = 'board-archive-confirm-description';
      description.className = 'modal-description';
      description.textContent = descriptionText;

      const actions = document.createElement('div');
      actions.className = 'modal-header-actions';

      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'btn btn-secondary';
      cancelBtn.textContent = 'Cancel';

      const okBtn = document.createElement('button');
      okBtn.type = 'button';
      okBtn.className = 'btn btn-primary';
      okBtn.textContent = confirmLabel;

      actions.append(okBtn, cancelBtn);
      modalContent.append(modalHeader, description, actions);
      modal.appendChild(modalContent);
      document.body.appendChild(modal);
      document.body.style.overflow = 'hidden';

      let mouseDownOnBackground = false;
      let settled = false;

      const settle = (accepted) => {
        if (settled) {
          return;
        }

        settled = true;
        modal.remove();
        document.body.style.overflow = previousOverflow;
        if (previousActiveElement) {
          previousActiveElement.focus();
        }
        resolve(accepted);
      };

      modal.addEventListener('mousedown', (event) => {
        mouseDownOnBackground = event.target === modal;
      });

      modal.addEventListener('click', (event) => {
        if (event.target === modal && mouseDownOnBackground) {
          settle(false);
        }
        mouseDownOnBackground = false;
      });

      const handleKeydown = (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          settle(false);
          return;
        }

        if (event.key !== 'Tab') {
          return;
        }

        const focusable = Array.from(modal.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        ));

        if (focusable.length === 0) {
          return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      };

      modal.addEventListener('keydown', handleKeydown);
      cancelBtn.addEventListener('click', () => settle(false));
      okBtn.addEventListener('click', () => settle(true));
      okBtn.focus();
    });
  }

  async rotatePublicLink() {
    if (!this.currentBoardId || !this.boardVisibilityEditable || !this.boardIsPublic || !this.boardPublicSlug) {
      return;
    }

    const confirmed = await this.confirmRotatePublicLink();
    if (!confirmed) {
      return;
    }

    try {
      const response = await fetch(`/api/boards/${this.currentBoardId}/public-link/rotate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.message || `HTTP error ${response.status}`);
      }

      const board = data.board || {};
      this.boardIsPublic = board.is_public === true;
      this.boardPublicSlug = typeof board.public_slug === 'string' && board.public_slug.length > 0
        ? board.public_slug
        : null;

      if (window.boardManager && window.boardManager.boardId === this.currentBoardId) {
        window.boardManager.isBoardPublic = this.boardIsPublic;
        window.boardManager.publicSlug = this.boardPublicSlug;
        window.boardManager.publicBoardShareUrl = this.getPublicBoardShareUrl(this.boardPublicSlug) || null;
      }

      this.updateBoardVisibilityMenuState();
      this.updateRotatePublicLinkMenuVisibility();
      this.updateCopyEmbedCodeMenuVisibility();
      this.setPublicBoardContext({
        isPublicBoard: this.boardIsPublic,
        publicUrl: this.getPublicBoardShareUrl(this.boardPublicSlug),
        isPublicPage: this.isPublicBoardPage,
        showLoginCta: this.isPublicBoardPage && !window.currentUser,
      });
      this.showHeaderToast('Public board link rotated');
    } catch (error) {
      console.error('Error rotating public board link:', error);
      this.showBoardPageToast(error.message || 'Failed to rotate public board link.');
    }
  }

  async confirmMakeBoardPublic() {
    const existingModal = document.getElementById('board-visibility-confirm-modal');
    if (existingModal) {
      existingModal.remove();
    }

    return new Promise((resolve) => {
      const previousActiveElement = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
      const previousOverflow = document.body.style.overflow;

      const modal = document.createElement('div');
      modal.className = 'modal';
      modal.id = 'board-visibility-confirm-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-labelledby', 'board-visibility-confirm-title');
      modal.setAttribute('aria-describedby', 'board-visibility-confirm-description');

      const modalContent = document.createElement('div');
      modalContent.className = 'modal-content board-owner-modal-content';

      const modalHeader = document.createElement('div');
      modalHeader.className = 'modal-header';

      const title = document.createElement('h2');
      title.id = 'board-visibility-confirm-title';
      title.textContent = 'Make Board Public?';

      modalHeader.appendChild(title);

      const description = document.createElement('p');
      description.id = 'board-visibility-confirm-description';
      description.className = 'modal-description';
      description.textContent = 'This will make this board publicly viewable (read-only) to anyone who can access this server, including over the internet if the server is internet-accessible.';

      const details = document.createElement('p');
      details.className = 'modal-description';
      details.textContent = 'All board content and card data will be visible. User identity details such as usernames and assignee metadata are redacted in public view. You can switch the board back to private at any time.';

      const actions = document.createElement('div');
      actions.className = 'modal-header-actions';

      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'btn btn-secondary';
      cancelBtn.textContent = 'Cancel';

      const okBtn = document.createElement('button');
      okBtn.type = 'button';
      okBtn.className = 'btn btn-primary';
      okBtn.textContent = 'Make Public';

      actions.append(okBtn, cancelBtn);
      modalContent.append(modalHeader, description, details, actions);
      modal.appendChild(modalContent);
      document.body.appendChild(modal);
      document.body.style.overflow = 'hidden';

      let mouseDownOnBackground = false;
      let settled = false;

      const settle = (accepted) => {
        if (settled) {
          return;
        }

        settled = true;
        modal.remove();
        document.body.style.overflow = previousOverflow;
        if (previousActiveElement) {
          previousActiveElement.focus();
        }
        resolve(accepted);
      };

      modal.addEventListener('mousedown', (event) => {
        mouseDownOnBackground = event.target === modal;
      });

      modal.addEventListener('click', (event) => {
        if (event.target === modal && mouseDownOnBackground) {
          settle(false);
        }
        mouseDownOnBackground = false;
      });

      const handleKeydown = (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          settle(false);
          return;
        }

        if (event.key !== 'Tab') {
          return;
        }

        const focusable = Array.from(modal.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        ));

        if (focusable.length === 0) {
          return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      };

      modal.addEventListener('keydown', handleKeydown);
      cancelBtn.addEventListener('click', () => settle(false));
      okBtn.addEventListener('click', () => settle(true));
      okBtn.focus();
    });
  }

  async confirmMakeBoardPrivate() {
    const existingModal = document.getElementById('board-visibility-confirm-modal');
    if (existingModal) {
      existingModal.remove();
    }

    return new Promise((resolve) => {
      const previousActiveElement = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
      const previousOverflow = document.body.style.overflow;

      const modal = document.createElement('div');
      modal.className = 'modal';
      modal.id = 'board-visibility-confirm-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-labelledby', 'board-visibility-confirm-title');
      modal.setAttribute('aria-describedby', 'board-visibility-confirm-description');

      const modalContent = document.createElement('div');
      modalContent.className = 'modal-content board-owner-modal-content';

      const modalHeader = document.createElement('div');
      modalHeader.className = 'modal-header';

      const title = document.createElement('h2');
      title.id = 'board-visibility-confirm-title';
      title.textContent = 'Make Board Private?';

      modalHeader.appendChild(title);

      const description = document.createElement('p');
      description.id = 'board-visibility-confirm-description';
      description.className = 'modal-description';
      description.textContent = 'This will restrict board visibility to permitted authenticated users only.';

      const details = document.createElement('p');
      details.className = 'modal-description';
      details.textContent = 'Anyone using the current public link will lose access immediately after this change.';

      const actions = document.createElement('div');
      actions.className = 'modal-header-actions';

      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'btn btn-secondary';
      cancelBtn.textContent = 'Cancel';

      const okBtn = document.createElement('button');
      okBtn.type = 'button';
      okBtn.className = 'btn btn-primary';
      okBtn.textContent = 'Make Private';

      actions.append(okBtn, cancelBtn);
      modalContent.append(modalHeader, description, details, actions);
      modal.appendChild(modalContent);
      document.body.appendChild(modal);
      document.body.style.overflow = 'hidden';

      let mouseDownOnBackground = false;
      let settled = false;

      const settle = (accepted) => {
        if (settled) {
          return;
        }

        settled = true;
        modal.remove();
        document.body.style.overflow = previousOverflow;
        if (previousActiveElement) {
          previousActiveElement.focus();
        }
        resolve(accepted);
      };

      modal.addEventListener('mousedown', (event) => {
        mouseDownOnBackground = event.target === modal;
      });

      modal.addEventListener('click', (event) => {
        if (event.target === modal && mouseDownOnBackground) {
          settle(false);
        }
        mouseDownOnBackground = false;
      });

      const handleKeydown = (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          settle(false);
          return;
        }

        if (event.key !== 'Tab') {
          return;
        }

        const focusable = Array.from(modal.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        ));

        if (focusable.length === 0) {
          return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      };

      modal.addEventListener('keydown', handleKeydown);
      cancelBtn.addEventListener('click', () => settle(false));
      okBtn.addEventListener('click', () => settle(true));
      okBtn.focus();
    });
  }

  async confirmRotatePublicLink() {
    const existingModal = document.getElementById('board-visibility-confirm-modal');
    if (existingModal) {
      existingModal.remove();
    }

    return new Promise((resolve) => {
      const previousActiveElement = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
      const previousOverflow = document.body.style.overflow;

      const modal = document.createElement('div');
      modal.className = 'modal';
      modal.id = 'board-visibility-confirm-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-labelledby', 'board-visibility-confirm-title');
      modal.setAttribute('aria-describedby', 'board-visibility-confirm-description');

      const modalContent = document.createElement('div');
      modalContent.className = 'modal-content board-owner-modal-content';

      const modalHeader = document.createElement('div');
      modalHeader.className = 'modal-header';

      const title = document.createElement('h2');
      title.id = 'board-visibility-confirm-title';
      title.textContent = 'Rotate Public Link?';

      modalHeader.appendChild(title);

      const description = document.createElement('p');
      description.id = 'board-visibility-confirm-description';
      description.className = 'modal-description';
      description.textContent = 'This will generate a new public link for this board and immediately invalidate the current link.';

      const details = document.createElement('p');
      details.className = 'modal-description';
      details.textContent = 'Anyone with the old link will lose access until they are given the new link.';

      const actions = document.createElement('div');
      actions.className = 'modal-header-actions';

      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'btn btn-secondary';
      cancelBtn.textContent = 'Cancel';

      const okBtn = document.createElement('button');
      okBtn.type = 'button';
      okBtn.className = 'btn btn-primary';
      okBtn.textContent = 'Rotate Link';

      actions.append(okBtn, cancelBtn);
      modalContent.append(modalHeader, description, details, actions);
      modal.appendChild(modalContent);
      document.body.appendChild(modal);
      document.body.style.overflow = 'hidden';

      let mouseDownOnBackground = false;
      let settled = false;

      const settle = (accepted) => {
        if (settled) {
          return;
        }

        settled = true;
        modal.remove();
        document.body.style.overflow = previousOverflow;
        if (previousActiveElement) {
          previousActiveElement.focus();
        }
        resolve(accepted);
      };

      modal.addEventListener('mousedown', (event) => {
        mouseDownOnBackground = event.target === modal;
      });

      modal.addEventListener('click', (event) => {
        if (event.target === modal && mouseDownOnBackground) {
          settle(false);
        }
        mouseDownOnBackground = false;
      });

      const handleKeydown = (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          settle(false);
          return;
        }

        if (event.key !== 'Tab') {
          return;
        }

        const focusable = Array.from(modal.querySelectorAll(
          'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        ));

        if (focusable.length === 0) {
          return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      };

      modal.addEventListener('keydown', handleKeydown);
      cancelBtn.addEventListener('click', () => settle(false));
      okBtn.addEventListener('click', () => settle(true));
      okBtn.focus();
    });
  }

  updateBoardStyleMenuLabel() {
    const menuItems = [
      document.getElementById('toggle-board-style-menu-item'),
      document.getElementById('mobile-toggle-board-style-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    const label = this.workingStyle === 'agile' ? 'Agile' : 'Kanban';
    menuItems.forEach((menuItem) => {
      menuItem.textContent = `Style: ${label}`;
    });
  }

  async toggleBoardStyle() {
    if (!this.currentBoardId || !this.boardStyleEditable) {
      return;
    }

    const nextStyle = this.workingStyle === 'agile' ? 'kanban' : 'agile';

    try {
      const response = await fetch(`/api/boards/${this.currentBoardId}/settings/working-style`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ value: nextStyle })
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.message || `HTTP error ${response.status}`);
      }

      this.workingStyle = nextStyle;
      this.updateBoardStyleMenuLabel();
      this.updateViewsDropdown();

      window.dispatchEvent(new CustomEvent('boardWorkingStyleChanged', {
        detail: { workingStyle: this.workingStyle }
      }));
    } catch (error) {
      console.error('Error toggling board style:', error);
    }
  }

  async initializeBoardReassignMenu() {
    const menuItems = [
      document.getElementById('reassign-board-menu-item'),
      document.getElementById('mobile-reassign-board-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    if (!this.currentBoardId) {
      this.updateBoardReassignMenuVisibility(false);
      return;
    }

    if (!this.boardOwnerDataListenerBound) {
      window.addEventListener('boardOwnerDataLoaded', this.boardOwnerDataLoadedHandler);
      this.boardOwnerDataListenerBound = true;
    }

    if (window.boardManager && window.boardManager.boardId === this.currentBoardId && window.boardManager.boardOwnerData) {
      this.hydrateBoardReassignmentOptions(window.boardManager.boardOwnerData);
    }

    menuItems.forEach((menuItem) => {
      if (!menuItem.dataset.boundReassignHandler) {
        menuItem.addEventListener('click', async (e) => {
          e.preventDefault();
          await this.openBoardReassignModal();
          closeAllMenusExcept(null);
          updateMenuHoverState();
        });
        menuItem.dataset.boundReassignHandler = 'true';
      }
    });

    // Always refresh from the owner endpoint so visibility does not depend on
    // board payload/event timing or metadata shape.
    const refreshedOptions = await this.fetchBoardReassignmentOptions(false);
    if (refreshedOptions) {
      this.boardReassignmentOptions = refreshedOptions;
    }

    this.refreshBoardReassignMenuState();
  }

  updateBoardReassignMenuVisibility(visible) {
    const menuItems = [
      document.getElementById('reassign-board-menu-item'),
      document.getElementById('mobile-reassign-board-menu-item')
    ].filter(Boolean);

    menuItems.forEach((menuItem) => {
      menuItem.style.display = visible ? '' : 'none';
    });
  }

  showBoardPageToast(message) {
    if (window.boardManager && typeof window.boardManager.showErrorToast === 'function') {
      window.boardManager.showErrorToast(message);
      return;
    }

    console.error(message);
  }

  hydrateBoardReassignmentOptions(detail) {
    if (!detail) {
      return;
    }

    this.boardReassignmentOptions = {
      board: {
        id: this.currentBoardId,
        owner_id: detail.owner_id,
      },
      current_owner: detail.owner || null,
      can_reassign: detail.can_reassign_owner === true,
      available_users: Array.isArray(detail.available_owner_users) ? detail.available_owner_users : [],
    };
  }

  handleBoardOwnerDataLoaded(event) {
    const detail = event?.detail;
    if (!detail || detail.boardId !== this.currentBoardId) {
      return;
    }

    this.hydrateBoardReassignmentOptions(detail);
    this.hydrateBoardVisibilityState(detail);
    this.hydrateBoardArchiveState(detail);

    this.refreshBoardReassignMenuState();
  }

  updateBoardArchiveMenuState() {
    const menuItems = [
      document.getElementById('archive-board-menu-item'),
      document.getElementById('mobile-archive-board-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    const visible = !!this.currentBoardId && !this.isPublicBoardPage && this.boardVisibilityEditable;
    const label = this.boardArchived ? 'Unarchive Board' : 'Archive Board';

    menuItems.forEach((menuItem) => {
      menuItem.style.display = visible ? '' : 'none';
      menuItem.textContent = label;
    });
  }

  async fetchBoardReassignmentOptions(showErrors = false) {
    if (!this.currentBoardId) {
      return null;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const response = await fetch(`/api/boards/${this.currentBoardId}/owner`, {
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      let data;
      try {
        data = await response.json();
      } catch (error) {
        data = {
          success: false,
          message: response.ok
            ? 'Invalid JSON response from server'
            : `HTTP error ${response.status}`
        };
      }

      if (!response.ok || !data.success) {
        throw new Error(data.message || 'Failed to load board owner options');
      }

      const board = data.board || {};
      return {
        board: {
          id: board.id || this.currentBoardId,
          owner_id: board.owner_id ?? data.owner_id,
        },
        current_owner: data.current_owner || board.owner || data.owner || null,
        can_reassign: data.can_reassign === true || board.can_reassign_owner === true || data.can_reassign_owner === true,
        available_users: Array.isArray(data.available_users)
          ? data.available_users
          : (Array.isArray(board.available_owner_users) ? board.available_owner_users : []),
      };
    } catch (error) {
      clearTimeout(timeoutId);
      if (showErrors) {
        if (error.name === 'AbortError') {
          this.showBoardPageToast('Loading board owners timed out. Please try again.');
        } else {
          this.showBoardPageToast(error.message || 'Failed to load board owner options.');
        }
      }
      return null;
    }
  }

  refreshBoardReassignMenuState() {
    if (!this.currentBoardId) {
      this.boardReassignmentOptions = null;
      this.updateBoardReassignMenuVisibility(false);
      return;
    }

    this.updateBoardReassignMenuVisibility(this.boardReassignmentOptions?.can_reassign === true);
  }

  async openBoardReassignModal() {
    const existingModal = document.getElementById('board-owner-modal');
    if (existingModal) {
      existingModal.remove();
    }

    let options = this.boardReassignmentOptions;
    if (options?.can_reassign === true && (!Array.isArray(options.available_users) || options.available_users.length === 0)) {
      options = await this.fetchBoardReassignmentOptions(true);
      if (options) {
        this.boardReassignmentOptions = options;
      }
    }

    if (!options || options.can_reassign !== true) {
      this.refreshBoardReassignMenuState();
      return;
    }

    const previousActiveElement = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousOverflow = document.body.style.overflow;

    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.id = 'board-owner-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'board-owner-modal-title');
    modal.setAttribute('aria-describedby', 'board-owner-modal-description');

    const modalContent = document.createElement('div');
    modalContent.className = 'modal-content board-owner-modal-content';

    const modalHeader = document.createElement('div');
    modalHeader.className = 'modal-header';

    const headerActions = document.createElement('div');
    headerActions.className = 'modal-header-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn btn-secondary';
    cancelBtn.textContent = 'Cancel';

    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'btn btn-primary';
    saveBtn.textContent = 'Save';

    headerActions.append(cancelBtn, saveBtn);

    const title = document.createElement('h2');
    title.id = 'board-owner-modal-title';
    title.textContent = 'Reassign Board';

    modalHeader.append(headerActions, title);

    const description = document.createElement('p');
    description.id = 'board-owner-modal-description';
    description.className = 'modal-description';
    description.textContent = 'Choose the new board owner. Owners and administrators can reassign boards from this menu.';

    const currentOwner = document.createElement('p');
    currentOwner.className = 'modal-description board-owner-current';
    const currentOwnerName = options.current_owner?.display_name || options.current_owner?.username || 'Unknown user';
    currentOwner.textContent = `Current owner: ${currentOwnerName}`;

    const ownerGroup = document.createElement('div');
    ownerGroup.className = 'form-group';

    const ownerLabel = document.createElement('label');
    ownerLabel.setAttribute('for', 'board-owner-select');
    ownerLabel.textContent = 'New Owner';

    const ownerSelect = document.createElement('select');
    ownerSelect.id = 'board-owner-select';
    ownerSelect.name = 'owner';
    ownerSelect.required = true;
    ownerSelect.setAttribute('aria-required', 'true');

    (options.available_users || []).forEach((user) => {
      const option = document.createElement('option');
      option.value = String(user.id);

      const label = user.display_name && user.username && user.display_name !== user.username
        ? `${user.display_name} (@${user.username})`
        : (user.display_name || user.username || `User ${user.id}`);

      option.textContent = label;
      ownerSelect.appendChild(option);
    });

    if (options.current_owner?.id) {
      ownerSelect.value = String(options.current_owner.id);
    }

    ownerGroup.append(ownerLabel, ownerSelect);
    modalContent.append(modalHeader, description, currentOwner, ownerGroup);
    modal.appendChild(modalContent);
    document.body.appendChild(modal);
    document.body.style.overflow = 'hidden';

    let mouseDownOnBackground = false;

    const closeModal = () => {
      modal.remove();
      document.body.style.overflow = previousOverflow;
      if (previousActiveElement) {
        previousActiveElement.focus();
      }
    };

    modal.addEventListener('mousedown', (event) => {
      mouseDownOnBackground = event.target === modal;
    });

    modal.addEventListener('click', (event) => {
      if (event.target === modal && mouseDownOnBackground) {
        closeModal();
      }
      mouseDownOnBackground = false;
    });

    const handleKeydown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeModal();
        return;
      }

      if (event.key !== 'Tab') {
        return;
      }

      const focusable = Array.from(modal.querySelectorAll(
        'button:not([disabled]), select:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ));

      if (focusable.length === 0) {
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    modal.addEventListener('keydown', handleKeydown);
    cancelBtn.addEventListener('click', closeModal);
    ownerSelect.focus();

    saveBtn.addEventListener('click', async () => {
      const selectedOwnerId = parseInt(ownerSelect.value, 10);
      if (!Number.isFinite(selectedOwnerId) || selectedOwnerId <= 0) {
        this.showBoardPageToast('Select a valid owner.');
        ownerSelect.focus();
        return;
      }

      saveBtn.disabled = true;
      cancelBtn.disabled = true;
      saveBtn.textContent = 'Saving...';

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      try {
        const response = await fetch(`/api/boards/${this.currentBoardId}/owner`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ owner_id: selectedOwnerId }),
          signal: controller.signal,
        });
        clearTimeout(timeoutId);

        let data;
        try {
          data = await response.json();
        } catch (error) {
          data = {
            success: false,
            message: response.ok
              ? 'Invalid JSON response from server'
              : `HTTP error ${response.status}`
          };
        }

        if (!response.ok || !data.success) {
          throw new Error(data.message || 'Failed to reassign board');
        }

        const updatedOptions = await this.fetchBoardReassignmentOptions(false);

        if (!updatedOptions) {
          const checkController = new AbortController();
          const checkTimeoutId = setTimeout(() => checkController.abort(), 5000);
          try {
            const checkResponse = await fetch(`/api/boards/${this.currentBoardId}/owner`, {
              signal: checkController.signal,
            });
            clearTimeout(checkTimeoutId);
            if (checkResponse.status === 403) {
              closeModal();
              window.location.href = '/index.html';
              return;
            }
          } catch (checkError) {
            clearTimeout(checkTimeoutId);
          }
          this.boardReassignmentOptions = {
            board: {
              id: this.currentBoardId,
              owner_id: data.board?.owner_id ?? data.owner_id,
            },
            current_owner: data.current_owner || data.owner || null,
            can_reassign: data.can_reassign === true || data.can_reassign_owner === true,
            available_users: Array.isArray(data.available_users)
              ? data.available_users
              : (Array.isArray(data.available_owner_users) ? data.available_owner_users : []),
          };
        } else {
          this.boardReassignmentOptions = updatedOptions;
        }
        closeModal();
        this.refreshBoardReassignMenuState();
      } catch (error) {
        clearTimeout(timeoutId);
        if (error.name === 'AbortError') {
          this.showBoardPageToast('Reassigning the board timed out. Please try again.');
        } else {
          this.showBoardPageToast(error.message || 'Failed to reassign board.');
        }
        saveBtn.disabled = false;
        cancelBtn.disabled = false;
        saveBtn.textContent = 'Save';
      }
    });
  }

  initializeBoardFilterToggleMenu() {
    const menuItems = [
      document.getElementById('toggle-board-filters-menu-item'),
      document.getElementById('mobile-toggle-board-filters-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    const isBoardPage = document.body.classList.contains('board-page');
    menuItems.forEach((menuItem) => {
      menuItem.style.display = isBoardPage ? '' : 'none';
    });
    if (!isBoardPage) {
      return;
    }

    menuItems.forEach((menuItem) => {
      if (!menuItem.dataset.boundToggleHandler) {
        menuItem.addEventListener('click', (e) => {
          e.preventDefault();

          window.dispatchEvent(new CustomEvent('boardFiltersToggleRequested'));

          closeAllMenusExcept(null);
          updateMenuHoverState();
        });
        menuItem.dataset.boundToggleHandler = 'true';
      }
    });

    // Initialize label from current board manager state when possible.
    let initialVisible = false;
    if (window.boardManager && typeof window.boardManager.assigneeFilterVisible === 'boolean') {
      initialVisible = window.boardManager.assigneeFilterVisible;
    }
    this.updateBoardFilterMenuLabel(initialVisible);
    window.addEventListener('boardFiltersVisibilityChanged', this.boardFiltersVisibilityHandler);

    // Request current state in case the initial board event happened before this listener was attached.
    window.dispatchEvent(new CustomEvent('boardFiltersStateRequest'));
    this.watchForBoardFilterState();
  }

  watchForBoardFilterState() {
    if (this.boardFilterStateWatchInterval) {
      clearInterval(this.boardFilterStateWatchInterval);
      this.boardFilterStateWatchInterval = null;
    }

    let attempts = 0;
    const maxAttempts = 50;
    this.boardFilterStateWatchInterval = setInterval(() => {
      attempts += 1;

      if (window.boardManager && typeof window.boardManager.assigneeFilterVisible === 'boolean') {
        this.updateBoardFilterMenuLabel(window.boardManager.assigneeFilterVisible);
        window.dispatchEvent(new CustomEvent('boardFiltersStateRequest'));
        clearInterval(this.boardFilterStateWatchInterval);
        this.boardFilterStateWatchInterval = null;
        return;
      }

      if (attempts >= maxAttempts) {
        clearInterval(this.boardFilterStateWatchInterval);
        this.boardFilterStateWatchInterval = null;
      }
    }, 100);
  }

  handleBoardFiltersVisibilityChanged(event) {
    const visible = !!event?.detail?.visible;
    this.updateBoardFilterMenuLabel(visible);
  }

  updateBoardFilterMenuLabel(visible) {
    const menuItems = [
      document.getElementById('toggle-board-filters-menu-item'),
      document.getElementById('mobile-toggle-board-filters-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    const label = visible ? 'Hide Filters' : 'Show Filters';
    menuItems.forEach((menuItem) => {
      menuItem.textContent = label;
    });
  }

  /**
   * Initialize the clear filters menu item
   * Sets up event listener for clearing filters and manages visibility based on filter state
   */
  initializeBoardFilterClearMenu() {
    const menuItems = [
      document.getElementById('clear-board-filters-menu-item'),
      document.getElementById('mobile-clear-board-filters-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    const isBoardPage = document.body.classList.contains('board-page');
    menuItems.forEach((menuItem) => {
      menuItem.style.display = 'none'; // Initially hidden
    });
    if (!isBoardPage) {
      return;
    }

    menuItems.forEach((menuItem) => {
      if (!menuItem.dataset.boundClearHandler) {
        menuItem.addEventListener('click', (e) => {
          e.preventDefault();

          window.dispatchEvent(new CustomEvent('boardFiltersClearRequest'));

          closeAllMenusExcept(null);
          updateMenuHoverState();
        });
        menuItem.dataset.boundClearHandler = 'true';
      }
    });

    // Listen for filter active state changes
    window.addEventListener('boardFiltersActiveStateChanged', this.boardFiltersActiveStateHandler);
  }

  /**
   * Handle board filters active state change event
   * Updates the visual indicator and clear filters menu visibility
   * @param {CustomEvent} event - Event containing filter active state in detail.active
   */
  handleBoardFiltersActiveStateChanged(event) {
    const active = !!event?.detail?.active;
    this.updateFilterActiveIndicator(active);
    this.updateClearFiltersMenuVisibility(active);
  }

  /**
   * Update the visual filter active indicator in the header
   * @param {boolean} active - Whether filters are currently active
   */
  updateFilterActiveIndicator(active) {
    const indicator = document.getElementById('filter-active-indicator');
    if (indicator) {
      // When active, clear inline style so CSS class (inline-flex) can apply
      indicator.style.display = active ? '' : 'none';
    }
  }

  /**
   * Update the visibility of the clear filters menu item
   * @param {boolean} active - Whether filters are currently active
   */
  updateClearFiltersMenuVisibility(active) {
    const menuItems = [
      document.getElementById('clear-board-filters-menu-item'),
      document.getElementById('mobile-clear-board-filters-menu-item')
    ].filter(Boolean);

    if (menuItems.length === 0) {
      return;
    }

    const isBoardPage = document.body.classList.contains('board-page');
    menuItems.forEach((menuItem) => {
      menuItem.style.display = (isBoardPage && active) ? '' : 'none';
    });
  }

  // Update views dropdown to show/hide done view based on working style
  updateViewsDropdown() {
    const dropdownMenu = document.getElementById('views-dropdown-menu');
    if (!dropdownMenu) return;

    if (this.workingStyle === 'agile') {
      // Check if done view already exists
      if (!document.querySelector('.views-dropdown-item[data-view="done"]')) {
        // Add done view option
        const doneItem = document.createElement('button');
        doneItem.className = 'views-dropdown-item';
        doneItem.setAttribute('data-view', 'done');
        doneItem.innerHTML = `
          <svg class="views-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
          <span>Done View</span>
        `;
        
        // Add click handler directly to the new item
        doneItem.addEventListener('click', (e) => {
          if (doneItem.classList.contains('active')) {
            e.preventDefault();
            e.stopPropagation();
            return;
          }
          this.setView('done');
          dropdownMenu.classList.remove('show');
        });
        
        dropdownMenu.appendChild(doneItem);
      }
    } else {
      // Remove done view if it exists
      const doneItem = document.querySelector('.views-dropdown-item[data-view="done"]');
      if (doneItem) {
        doneItem.remove();
      }
    }

    // Keep mobile views in sync with active working style
    const mobileViewsSection = document.getElementById('mobile-views-section');
    if (mobileViewsSection) {
      const mobileDoneItem = mobileViewsSection.querySelector('.mobile-view-item[data-view="done"]');
      if (this.workingStyle === 'agile') {
        if (!mobileDoneItem) {
          const doneBtn = document.createElement('button');
          doneBtn.className = 'mobile-view-item';
          doneBtn.setAttribute('data-view', 'done');
          doneBtn.textContent = 'Done View';
          doneBtn.addEventListener('click', () => {
            this.setView('done');
            const header = document.querySelector('.header');
            if (header) {
              header.classList.remove('mobile-menu-open');
            }
            document.body.classList.remove('mobile-menu-open');
            const mobileToggle = document.getElementById('mobile-menu-toggle');
            if (mobileToggle) {
              mobileToggle.setAttribute('aria-expanded', 'false');
            }
          });
          mobileViewsSection.querySelector('.mobile-tree-items')?.appendChild(doneBtn);
        }
      } else if (mobileDoneItem) {
        mobileDoneItem.remove();
      }
    }
  }

  // Initialize dropdown pin behavior for settings and user menus
  initializeDropdownPin() {
    const dropdowns = [
      {
        trigger: document.querySelector('.settings-dropdown .icon-link'),
        menu: document.getElementById('settings-dropdown-menu')
      },
      {
        trigger: document.querySelector('.user-dropdown .icon-link'),
        menu: document.getElementById('user-dropdown-menu')
      }
    ];

    // Get notifications popup for coordinated hover prevention
    const notificationsPopup = document.getElementById('notifications-popup');
    const allMenus = [...dropdowns.map(d => d.menu), notificationsPopup].filter(Boolean);

    dropdowns.forEach(({ trigger, menu }) => {
      if (!trigger || !menu) return;

      // Toggle pinned state on click
      trigger.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        const wasPinned = menu.classList.contains('pinned');
        
        if (wasPinned) {
          // Close this menu
          menu.classList.remove('pinned');
        } else {
          // Close other menus and open this one
          closeAllMenusExcept(menu);
          menu.classList.add('pinned');
        }
        
        // Update hover state for all menus
        updateMenuHoverState();
      });
    });

    // Close pinned menus when clicking outside
    document.addEventListener('click', (e) => {
      const clickedInsideAnyMenu = dropdowns.some(({ trigger, menu }) => {
        return trigger && menu && (trigger.contains(e.target) || menu.contains(e.target));
      });
      
      const clickedInNotifications = notificationsPopup && 
        (notificationsPopup.contains(e.target) || 
         document.getElementById('notifications-icon-link')?.contains(e.target));

      if (!clickedInsideAnyMenu && !clickedInNotifications) {
        closeAllMenusExcept(null); // Close all menus
        updateMenuHoverState();
      }
    });

    // Close pinned menus on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const hadPinned = allMenus.some(menu => menu && menu.classList.contains('pinned'));
        
        if (hadPinned) {
          closeAllMenusExcept(null); // Close all menus
          updateMenuHoverState();
        }
      }
    });
  }

  // Initialize views dropdown functionality
  initializeViewsDropdown() {
    const dropdownBtn = document.getElementById('views-dropdown-btn');
    const dropdownMenu = document.getElementById('views-dropdown-menu');
    const dropdownItems = document.querySelectorAll('.views-dropdown-item');

    if (!dropdownBtn || !dropdownMenu) return;

    // Toggle dropdown on button click
    dropdownBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = dropdownMenu.classList.contains('show');
      dropdownMenu.classList.toggle('show', !isOpen);
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
      if (!dropdownBtn.contains(e.target) && !dropdownMenu.contains(e.target)) {
        dropdownMenu.classList.remove('show');
      }
    });

    // Handle view selection
    dropdownItems.forEach(item => {
      item.addEventListener('click', (e) => {
        // Don't allow clicking the active view
        if (item.classList.contains('active')) {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
        const view = e.currentTarget.dataset.view;
        this.setView(view);
        dropdownMenu.classList.remove('show');
      });
    });
  }

  // Set the current view
  setView(view) {
    this.currentView = view;
    
    // Update dropdown label
    const label = document.getElementById('views-dropdown-label');
    if (label) {
      const isBoardsPage = document.body.classList.contains('boards-page');
      const viewNames = isBoardsPage
        ? {
            'task': 'Active Boards',
            'archived': 'Archived Boards',
          }
        : {
            'task': 'Task View',
            'scheduled': 'Scheduled View',
            'archived': 'Archived View',
            'done': 'Done View'
          };
      label.textContent = viewNames[view] || (isBoardsPage ? 'Active Boards' : 'Task View');
    }

    // Highlight active item
    document.querySelectorAll('.views-dropdown-item').forEach(item => {
      item.classList.toggle('active', item.dataset.view === view);
    });

    document.querySelectorAll('.mobile-view-item').forEach(item => {
      item.classList.toggle('active', item.dataset.view === view);
    });

    // Dispatch custom event for board.js to handle
    window.dispatchEvent(new CustomEvent('viewChanged', { detail: { view } }));
  }

  // Get the current view
  getView() {
    return this.currentView;
  }

  // Escape HTML to prevent XSS
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  _showServiceUnhealthyToast(services) {
    const label = services.length === 1
      ? `${services[0]} service has stopped`
      : `Services stopped: ${services.join(', ')}`;
    const toast = document.createElement('div');
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.textContent = label;
    toast.style.cssText = [
      'position:fixed',
      'bottom:20px',
      'right:20px',
      'background:#e74c3c',
      'color:white',
      'padding:12px 20px',
      'border-radius:5px',
      'box-shadow:0 4px 8px rgba(0,0,0,0.3)',
      'z-index:10000',
      'animation:slideIn 0.3s ease-out',
      'max-width:400px',
      'word-wrap:break-word',
    ].join(';');
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.animation = 'slideOut 0.3s ease-in';
      setTimeout(() => toast.remove(), 300);
    }, 6000);
  }

  /**
   * Update the status icon and text in the header.
   * 
   * Args:
   *   status: Status type ('success' or 'error')
   *   message: Status message to display
   *   count: Optional count of boards (shown in tooltip)
   *   housekeepingHealthy: Whether housekeeping scheduler is healthy
   */
  updateStatus(status, message, count = null, housekeepingHealthy = true) {
    if (!this.statusIcon || !this.statusText) return;

    // Check WebSocket health
    const { hasSocket, wsHealthy, wsConnecting } = this._getWebSocketConnectionState();
    
    // Only show error if we have a socket that's not connecting
    // If we don't have a socket yet, it's probably still initializing - don't error
    // Note: WebSocket is for real-time sync only. REST API calls still work, so don't block operations
    if (hasSocket && !wsHealthy && !wsConnecting) {
      // WebSocket exists but is down and not connecting = connection error
      this.statusIcon.className = 'status-icon error';
      this.statusText.textContent = 'Connection Error';
      this.statusText.title = 'WebSocket connection lost. Real-time updates may not work. Try force reloading the page (Ctrl+Shift+R).';
      // Note: dbConnected NOT set to false - REST API calls still work
      return;
    }
    
    // WebSocket is connected (or not required on this page), now evaluate DB status
    // Note: Housekeeping scheduler health is displayed but does NOT block database operations
    // Only critical failures (DB, WebSocket, Server) prevent card creation
    
    this.statusIcon.className = `status-icon ${status}`;
    this.dbConnected = (status === 'success');
    
    if (status === 'success') {
      this.statusText.textContent = 'Connected';
      this.statusText.title = ''; // Clear any previous error message
    } else if (status === 'error') {
      this.statusText.textContent = 'DB Error';
      this.statusText.title = message; // Show full error on hover
    } else {
      this.statusText.textContent = message;
      this.statusText.title = '';
    }
  }

  /**
   * Check system status with proper precedence:
   * 1. Server connectivity (can reach API?)
   * 2. WebSocket availability (on pages that need it)
   * 3. Database health (if server and WebSocket OK)
   * 
   * Updates header status based on first failure encountered.
   */
  async checkDatabaseStatus() {
    // First: Check if server is reachable (API responds at all)
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);
    
    let liveData = null;
    
    try {
      const response = await fetch('/api/health/live', {
        signal: controller.signal
      });
      clearTimeout(timeoutId);
      liveData = await response.json();
    } catch (error) {
      clearTimeout(timeoutId);
      // Server is not responding - network error or server is down
      this.statusIcon.className = 'status-icon error';
      this.statusText.textContent = 'Server Disconnected';
      this.statusText.title = 'Unable to connect to server. Check your connection or try refreshing the page.';
      this.dbConnected = false;
      return;
    }

    // Second: Check WebSocket status on pages that need it (board, theme-builder)
    // Do this BEFORE checking database health so we can report WebSocket issues even if DB is down
    // Detect if we're on a page that should have Socket.IO loaded
    // Check for page-specific elements rather than socket existence to handle Socket.IO load failures
    const isOnBoardPage = (window.boardManager && window.boardManager.wsManager) || 
                          (document.getElementById('theme-builder-select') !== null);
    
    if (isOnBoardPage) {
      const { hasSocket, wsHealthy, wsConnecting, ioLoaded } = this._getWebSocketConnectionState();
      
      // If we're on a board page but Socket.IO isn't loaded, that's an error
      // However: REST API calls still work without WebSocket, so don't block operations
      if (!ioLoaded) {
        this.statusIcon.className = 'status-icon error';
        this.statusText.textContent = 'WebSocket Disconnected';
        this.statusText.title = 'Real-time updates are unavailable. Socket.IO library failed to load. Try force reloading (Ctrl+Shift+R).';
        // Set dbConnected=true: We've already verified server is reachable (via /api/health/live above)
        // WebSocket failure doesn't affect REST API calls or database operations
        this.dbConnected = true;
        return;
      }
      
      // If Socket.IO is loaded but WebSocket isn't working (not connected and not trying)
      // Display error but don't block API operations since REST calls still work
      // Also consider it disconnected if it's been trying to connect for too long (>30 seconds)
      const connectionDuration = Date.now() - (this.wsConnectionStartTime || Date.now());
      const isConnectingTooLong = wsConnecting && connectionDuration > 30000;
      
      if ((!wsHealthy && !wsConnecting) || isConnectingTooLong) {
        this.statusIcon.className = 'status-icon error';
        this.statusText.textContent = 'WebSocket Disconnected';
        this.statusText.title = 'Real-time updates are unavailable. Board changes will not sync in real-time. Try force reloading (Ctrl+Shift+R).';
        // Set dbConnected=true: We've already verified server is reachable (via /api/health/live above)
        // WebSocket failure doesn't affect REST API calls or database operations
        this.dbConnected = true;
        return;
      }
      
      // Track when connection started trying
      if (wsConnecting && !this.wsConnectionStartTime) {
        this.wsConnectionStartTime = Date.now();
      } else if (!wsConnecting && this.wsConnectionStartTime) {
        // No longer connecting (whether succeeded or failed), reset the timer
        this.wsConnectionStartTime = null;
      }
    }

    if (!liveData || !liveData.ok) {
      this.statusIcon.className = 'status-icon error';
      this.statusText.textContent = 'Server Disconnected';
      this.statusText.title = 'Unable to connect to server. Check your connection or try refreshing the page.';
      this.dbConnected = false;
      return;
    }

    // Third: Check database health via authenticated version endpoint
    let versionData = null;
    const dbController = new AbortController();
    const dbTimeoutId = setTimeout(() => dbController.abort(), 5000);

    try {
      const versionResponse = await fetch('/api/version', { signal: dbController.signal });
      clearTimeout(dbTimeoutId);
      versionData = await versionResponse.json();

      if (!versionResponse.ok || !versionData.success) {
        this.statusIcon.className = 'status-icon error';
        this.statusText.textContent = 'DB Error';
        this.statusText.title = versionData?.message || 'Database error. Check database connection.';
        this.dbConnected = false;
        return;
      }
    } catch (err) {
      clearTimeout(dbTimeoutId);
      this.statusIcon.className = 'status-icon error';
      this.statusText.textContent = 'DB Error';
      this.statusText.title = err.name === 'AbortError'
        ? 'Database check timed out (5s).'
        : `Database check failed: ${err.message}`;
      this.dbConnected = false;
      return;
    }

    // All systems OK - get scheduler status
    const healthController = new AbortController();
    const healthTimeoutId = setTimeout(() => healthController.abort(), 5000);
    
    try {
      const healthResponse = await fetch('/api/scheduler/health', { signal: healthController.signal });
      
      clearTimeout(healthTimeoutId);

      // Scheduler endpoint can be permission-restricted; don't treat non-2xx as service failure.
      if (!healthResponse.ok) {
        this.updateStatus('success', 'Connected', null, true);
        this.statusText.title = `Scheduler health unavailable (${healthResponse.status}).`;
        this.dbConnected = true;
        this._prevUnhealthyServices = [];

        if (versionData.success) {
          this.updateVersion(versionData.app_version, versionData.db_version);
        }
        return;
      }
      
      let healthData = null;
      try {
        healthData = await healthResponse.json();
      } catch {
        this.updateStatus('success', 'Connected', null, true);
        this.statusText.title = 'Scheduler health unavailable (invalid response).';
        this.dbConnected = true;
        this._prevUnhealthyServices = [];

        if (versionData.success) {
          this.updateVersion(versionData.app_version, versionData.db_version);
        }
        return;
      }

      if (!healthData || typeof healthData !== 'object') {
        this.updateStatus('success', 'Connected', null, true);
        this.statusText.title = 'Scheduler health unavailable (unexpected response).';
        this.dbConnected = true;
        this._prevUnhealthyServices = [];

        if (versionData.success) {
          this.updateVersion(versionData.app_version, versionData.db_version);
        }
        return;
      }
      
      // Check all three scheduler threads
      const schedulerChecks = [
        { key: 'backup_scheduler',       label: 'Backup' },
        { key: 'card_scheduler',         label: 'Card' },
        { key: 'housekeeping_scheduler', label: 'Housekeeping' },
      ];
      const unhealthyServices = schedulerChecks
        .filter(({ key }) => {
          const s = healthData[key];
          return !(s && s.running && s.thread_alive);
        })
        .map(({ label }) => label);
      
      if (unhealthyServices.length > 0) {
        this.statusIcon.className = 'status-icon error';
        this.statusText.textContent = 'Service Unhealthy';
        this.statusText.title = `Stopped service(s): ${unhealthyServices.join(', ')}`;
        this.dbConnected = true; // Database is healthy; background services are not
      } else {
        this.updateStatus('success', 'Connected', null, true);
      }
      
      // Show toast if any services are newly unhealthy (or unhealthy on first check)
      const prevUnhealthy = this._prevUnhealthyServices;
      const newlyUnhealthy = unhealthyServices.filter(
        s => !prevUnhealthy || !prevUnhealthy.includes(s)
      );
      if (newlyUnhealthy.length > 0) {
        this._showServiceUnhealthyToast(newlyUnhealthy);
      }
      this._prevUnhealthyServices = unhealthyServices;
      
      // Update version display (DB is healthy regardless of scheduler state)
      if (versionData.success) {
        this.updateVersion(versionData.app_version, versionData.db_version);
      }
    } catch (err) {
      clearTimeout(healthTimeoutId);
      
      // Server/connection error (not a DB-specific error)
      if (err.name === 'AbortError') {
        this.statusIcon.className = 'status-icon error';
        this.statusText.textContent = 'Server Connection Error';
        this.statusText.title = 'API request timed out (5s). Check server connectivity.';
        this.dbConnected = false;
      } else {
        this.statusIcon.className = 'status-icon error';
        this.statusText.textContent = 'Server Connection Error';
        this.statusText.title = `Server connection error: ${err.message}`;
        this.dbConnected = false;
      }
    }
  }

  // Update version display
  updateVersion(appVersion, dbVersion) {
    const versionElement = this.versionInfo || document.getElementById('version-info');
    if (versionElement) {
      versionElement.textContent = `v${appVersion} | DB:${dbVersion}`;
    }
  }

  /**
   * Load version info from API.
   * 
   * Fetches app and database version information without triggering
   * WebSocket status checks. Silently fails if server is unavailable.
   */
  async loadVersionInfo() {
    try {
      const response = await fetch('/api/version', { 
        signal: AbortSignal.timeout(5000) 
      });
      const versionData = await response.json();
      
      if (versionData.success) {
        this.updateVersion(versionData.app_version, versionData.db_version);
      }
    } catch (error) {
      // Silently fail - version info is optional
      console.debug('Could not load version info:', error);
    }
  }

  // Load boards for dropdown menu
  async loadBoardsDropdown() {
    try {
      const response = await fetch('/api/boards');
      const data = await response.json();
      
      const dropdown = document.getElementById('boards-dropdown-menu');
      const mobileBoardsMenu = document.getElementById('mobile-boards-menu');
      if (!dropdown) return;
      
      if (data.success && data.boards && data.boards.length > 0) {
        // Clear loading message
        dropdown.innerHTML = '';
        if (mobileBoardsMenu) {
          mobileBoardsMenu.innerHTML = '';
        }
        
        // Add each board as a link
        data.boards.forEach(board => {
          const link = document.createElement('a');
          link.href = `/board.html?id=${board.id}`;
          link.className = 'boards-dropdown-item';
          link.textContent = board.name;
          dropdown.appendChild(link);

          if (mobileBoardsMenu) {
            const mobileLink = document.createElement('a');
            mobileLink.href = `/board.html?id=${board.id}`;
            mobileLink.className = 'mobile-menu-link';
            mobileLink.textContent = board.name;
            mobileBoardsMenu.appendChild(mobileLink);
          }
        });
      } else {
        dropdown.innerHTML = '<div class="boards-dropdown-empty">No boards yet</div>';
        if (mobileBoardsMenu) {
          mobileBoardsMenu.innerHTML = '<div class="mobile-menu-loading">No boards yet</div>';
        }
      }
    } catch (error) {
      console.error('Error loading boards dropdown:', error);
      const dropdown = document.getElementById('boards-dropdown-menu');
      const mobileBoardsMenu = document.getElementById('mobile-boards-menu');
      if (dropdown) {
        dropdown.innerHTML = '<div class="boards-dropdown-empty">Error loading boards</div>';
      }
      if (mobileBoardsMenu) {
        mobileBoardsMenu.innerHTML = '<div class="mobile-menu-loading">Error loading boards</div>';
      }
    }
  }

  // Cleanup method to prevent memory leaks
  destroy() {
    if (this.statusCheckInterval) {
      clearInterval(this.statusCheckInterval);
      this.statusCheckInterval = null;
    }
    if (this.wsCheckInterval) {
      clearInterval(this.wsCheckInterval);
      this.wsCheckInterval = null;
    }

    if (this.boardOwnerDataListenerBound) {
      window.removeEventListener('boardOwnerDataLoaded', this.boardOwnerDataLoadedHandler);
      this.boardOwnerDataListenerBound = false;
    }

    window.removeEventListener('boardFiltersVisibilityChanged', this.boardFiltersVisibilityHandler);
    if (this.boardFilterStateWatchInterval) {
      clearInterval(this.boardFilterStateWatchInterval);
      this.boardFilterStateWatchInterval = null;
    }
  }
}

// Initialize header on page load
const header = new Header();
window.header = header; // Make it globally accessible
document.addEventListener('DOMContentLoaded', async () => {
  scheduleAuthBootstrapLoading();

  if (!window.authBootstrapPromise) {
    window.authBootstrapPromise = ensureAuthenticatedForProtectedPage();
  }

  try {
    const canContinue = await window.authBootstrapPromise;
    if (!canContinue) {
      hideAuthBootstrapLoading();
      return;
    }

    await header.load();

    // Preload time format preference
    if (typeof preloadTimeFormat === 'function') {
      preloadTimeFormat();
    }

    // Preload timezone preference
    if (typeof preloadUserTimezone === 'function') {
      preloadUserTimezone();
    }
  } finally {
    hideAuthBootstrapLoading();
  }
});

// Cleanup on page unload to prevent memory leaks
window.addEventListener('beforeunload', () => {
  header.destroy();
});
