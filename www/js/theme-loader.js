// Global theme loader - applies saved theme to all pages
// This must run IMMEDIATELY in the HEAD to prevent style flash

(function() {
  const THEME_COLOR_STORAGE_KEY = 'aftThemeColor';

  // Installed/standalone PWAs (notably Android Chrome) paint the OS status
  // bar from the theme-color meta tag once, very early - updating the tag
  // later via JS after an async API call reliably updates the in-page value
  // but the already-painted system status bar does not repaint to match.
  // localStorage (unlike sessionStorage) survives a full app close, so this
  // applies the last-known-correct color synchronously, before anything
  // else runs, closing the gap for first-launch/first-navigation-of-session.
  (function applyStoredThemeColorImmediately() {
    try {
      const stored = localStorage.getItem(THEME_COLOR_STORAGE_KEY);
      if (stored) {
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) {
          meta.setAttribute('content', stored);
        }
      }
    } catch (e) {
      // localStorage unavailable (private browsing etc.) - static fallback in the HTML stands.
    }
  })();

  const SAFE_THEME_SETTING_NAME = /^[A-Za-z0-9-]+$/;
  const colorValidationElement = document.createElement('span');
  // Expose as a shared constant so other scripts (e.g. header.js) can reuse
  // the same list rather than maintaining a separate copy.
  const PUBLIC_PAGE_PATHS = window.__aftPublicPagePaths = ['/login.html', '/register.html', '/logout.html', '/setup.html', '/about.html', '/docs.html', '/public-board.html'];

  function isPublicPagePath(pathname) {
    return PUBLIC_PAGE_PATHS.some((pagePath) => pathname.includes(pagePath));
  }

  function getNetworkTimeoutMultiplier() {
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

  function getThemeRequestTimeoutMs() {
    const baseTimeoutMs = 6000;
    return Math.min(baseTimeoutMs * getNetworkTimeoutMultiplier(), 24000);
  }

  function getSafeBackgroundImage(filename) {
    if (typeof filename !== 'string') {
      return null;
    }

    const trimmedFilename = filename.trim();
    if (!trimmedFilename || trimmedFilename === 'none') {
      return null;
    }

    return /^[A-Za-z0-9_.-]+$/.test(trimmedFilename) ? trimmedFilename : null;
  }

  function applyBackgroundImage(root, filename) {
    const safeFilename = getSafeBackgroundImage(filename);

    if (safeFilename) {
      root.style.setProperty('--background-image', `url('/images/backgrounds/${safeFilename}')`);
      return safeFilename;
    }

    root.style.setProperty('--background-image', 'none');
    return null;
  }

  function isSafeThemeSettingValue(value) {
    if (typeof value !== 'string') {
      return false;
    }

    const trimmedValue = value.trim();
    if (!trimmedValue) {
      return false;
    }

    if (typeof CSS !== 'undefined' && typeof CSS.supports === 'function') {
      return CSS.supports('color', trimmedValue);
    }

    colorValidationElement.style.color = '';
    colorValidationElement.style.color = trimmedValue;
    return colorValidationElement.style.color !== '';
  }

  function getSafeThemeSettings(settings) {
    if (!settings || typeof settings !== 'object' || Array.isArray(settings)) {
      return null;
    }

    const safeSettings = {};

    Object.entries(settings).forEach(([key, value]) => {
      if (!SAFE_THEME_SETTING_NAME.test(key) || !isSafeThemeSettingValue(value)) {
        return;
      }

      safeSettings[key] = value.trim();
    });

    return Object.keys(safeSettings).length > 0 ? safeSettings : null;
  }

  // Keeps the browser/OS chrome color (address bar, status bar, task
  // switcher) in sync with the app's own header, instead of a static value
  // that would only ever match the default theme.
  function applyThemeColorMeta(headerBackground) {
    if (!headerBackground) {
      return;
    }

    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute('content', headerBackground);
    }

    try {
      localStorage.setItem(THEME_COLOR_STORAGE_KEY, headerBackground);
    } catch (e) {
      // localStorage unavailable (private browsing etc.) - in-page value above still applies.
    }
  }

  function applyThemeSettings(root, settings) {
    const safeSettings = getSafeThemeSettings(settings);

    if (!safeSettings) {
      return null;
    }

    Object.entries(safeSettings).forEach(([key, value]) => {
      root.style.setProperty(`--${key}`, value);
    });

    applyThemeColorMeta(safeSettings['header-background']);

    return safeSettings;
  }

  // Helper to apply theme colors and background
  function applyThemeToDOM(theme) {
    const root = document.documentElement;
    
    const safeThemeSettings = theme && theme.settings ? applyThemeSettings(root, theme.settings) : null;
    
    // Apply background image
    const safeBackgroundImage = applyBackgroundImage(root, theme && theme.background_image);
    if (typeof sessionStorage !== 'undefined') {
      if (safeThemeSettings) {
        sessionStorage.setItem('currentTheme', JSON.stringify(safeThemeSettings));
      }

      if (safeBackgroundImage) {
        sessionStorage.setItem('backgroundImage', safeBackgroundImage);
      } else {
        sessionStorage.setItem('backgroundImage', 'none');
      }
    }

    return !!safeThemeSettings;
  }

  // Try to load theme from sessionStorage first (fast path for same-session navigation)
  function applyFromSessionStorage(options = {}) {
    const includeBackgroundImage = options.includeBackgroundImage !== false;
    const savedTheme = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('currentTheme') : null;
    const savedBgImage = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('backgroundImage') : null;
    
    if (savedTheme) {
      try {
        // Note: savedTheme is already the settings object (not wrapped in .settings)
        // because sessionStorage stores JSON.stringify(theme.settings) directly
        const theme = JSON.parse(savedTheme);
        const root = document.documentElement;
        const safeThemeSettings = applyThemeSettings(root, theme);

        if (!safeThemeSettings) {
          if (includeBackgroundImage) {
            applyBackgroundImage(root, savedBgImage);
          } else {
            applyBackgroundImage(root, null);
          }
          return false;
        }
        
        // Also apply the cached background image when allowed
        if (includeBackgroundImage) {
          applyBackgroundImage(root, savedBgImage);
        } else {
          applyBackgroundImage(root, null);
        }
        
        return true; // Successfully applied cached theme
      } catch (e) {
        console.warn('Error parsing cached theme:', e);
      }
    }
    
    // Apply cached background if no theme cache and background usage is allowed
    if (includeBackgroundImage) {
      applyBackgroundImage(document.documentElement, savedBgImage);
    } else {
      applyBackgroundImage(document.documentElement, null);
    }
    
    return false; // No cached theme available
  }

  // Load theme from backend API - will override any cached theme
  async function loadThemeFromAPI() {
    const controller = new AbortController();
    const timeoutMs = getThemeRequestTimeoutMs();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch('/api/settings/theme', {
        signal: controller.signal
      });
      
      if (response.ok) {
        const theme = await response.json();
        
        // Apply theme from API
        applyThemeToDOM(theme);
        
        return true; // Successfully loaded from API
      }
    } catch (error) {
      if (error.name !== 'AbortError') {
        console.warn('Failed to load theme from API:', error.message);
      } else {
        console.warn('Theme API request timed out during page startup');
      }
    } finally {
      clearTimeout(timeoutId);
    }
    
    return false; // API call failed
  }

  // Initialize theme loading
  function init() {
    const currentPath = window.location.pathname || '';
    const isPublicPage = isPublicPagePath(currentPath);
    const isPublicBoardPage = currentPath.includes('/public-board.html');

    // Public boards apply instance default theme from board payload; avoid cached
    // user themes and avoid auth-only theme API calls on anonymous pages.
    if (isPublicBoardPage) {
      return;
    }

    // First, apply cached theme if available (prevents flash)
    const hasCachedTheme = applyFromSessionStorage({ includeBackgroundImage: isPublicPage });

    // For protected pages, always revalidate via API before applying background image.
    // This avoids showing cached protected-page visuals before auth redirect completes.
    if (!isPublicPage) {
      loadThemeFromAPI().catch(error => {
        console.debug('Background theme API update failed:', error.message);
      });
      return;
    }

    // On public pages, only load from API if we don't have cached theme settings.
    if (!hasCachedTheme) {
      loadThemeFromAPI().catch(error => {
        // Silently handle API errors - cached theme or defaults are already applied
        console.debug('Background theme API update failed:', error.message);
      });
    }
  }

  // Run initialization
  init();
})();
