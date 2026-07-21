// Settings page functionality
class Settings {
  constructor() {
    this.globalSettingsPanel = document.getElementById('global-settings-panel');
    this.defaultBoardSelect = document.getElementById('default-board');
    this.timeFormatRadios = document.querySelectorAll('input[name="time-format"]');
    this.timezoneSelect = document.getElementById('timezone-select');
    this.themeSelect = document.getElementById('theme-select');
    this.instanceDefaultThemeSelect = document.getElementById('instance-default-theme');
    this.instanceDefaultThemeSaveBtn = document.getElementById('instance-default-theme-save-btn');
    this.promoteGlobalThemeSelect = document.getElementById('promote-global-theme');
    this.promoteGlobalThemeBtn = document.getElementById('promote-global-theme-btn');
    this.demoteGlobalThemeSelect = document.getElementById('demote-global-theme');
    this.demoteGlobalThemeBtn = document.getElementById('demote-global-theme-btn');
    this.workingStyleSelect = document.getElementById('working-style');
    this.statusElement = document.getElementById('settings-status');
    this.currentLogoPreview = document.getElementById('current-logo-preview');
    this.brandingFileInput = document.getElementById('branding-logo-file');
    this.brandingUploadBtn = document.getElementById('branding-upload-btn');
    this.brandingResetBtn = document.getElementById('branding-reset-btn');
    this.brandingStatus = document.getElementById('branding-status');
    this.defaultLogoPath = this.currentLogoPreview?.getAttribute('src') || '/images/AFT_logo.webp';
    this.appNameInput = document.getElementById('app-name-input');
    this.appNameSaveBtn = document.getElementById('app-name-save-btn');
    this.appNameResetBtn = document.getElementById('app-name-reset-btn');
    this.appNameStatus = document.getElementById('app-name-status');
    this.saveTimeout = null;
    this.canManageBranding = false;
  }

  async init() {
    // Match other permission-gated pages: wait until header.js has loaded user context.
    if (!window.userDataReady) {
      setTimeout(() => this.init(), 100);
      return;
    }

    this.initializeGlobalSettingsVisibility();

    await this.loadBoards();
    await this.loadSettings();
    await this.loadTimezoneOptions();
    await this.loadTimezoneSetting();
    await this.loadThemes();
    if (this.canManageBranding) {
      await this.loadInstanceDefaultTheme();
    }
    await this.loadWorkingStyle();
    await this.applyThemeColors(); // Ensure theme is loaded on page load
    if (this.canManageBranding) {
      await this.loadBrandingSettings();
      await this.loadAppName();
    }
    this.attachEventListeners();
  }

  initializeGlobalSettingsVisibility() {
    this.canManageBranding = typeof hasPermission === 'function' && hasPermission('branding.edit');

    if (!this.globalSettingsPanel) {
      return;
    }

    this.globalSettingsPanel.hidden = !this.canManageBranding;
  }

  async fetchWithTimeout(url, options = {}, timeoutMs = 5000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      return await fetch(url, {
        ...options,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeoutId);
    }
  }

  getBrandingPath(filename) {
    if (!filename || typeof filename !== 'string') {
      return this.defaultLogoPath;
    }

    return `/images/backgrounds/logos/${encodeURIComponent(filename)}`;
  }

  applyBrandingPreview(path) {
    if (this.currentLogoPreview) {
      this.currentLogoPreview.src = path;
    }

    if (window.header && typeof window.header.applyBrandingAssets === 'function') {
      if (path === this.defaultLogoPath) {
        window.header.applyBrandingAssets();
      } else {
        window.header.applyBrandingAssets(path, path);
      }
    }
  }

  showBrandingStatus(message, type = 'info') {
    if (!this.brandingStatus) {
      return;
    }

    this.brandingStatus.textContent = message;
    this.brandingStatus.className = `settings-status ${type}`;

    if (type === 'success') {
      setTimeout(() => {
        if (this.brandingStatus) {
          this.brandingStatus.textContent = '';
          this.brandingStatus.className = 'settings-status';
        }
      }, 2000);
    }
  }

  async loadBrandingSettings() {
    if (!this.canManageBranding) {
      return;
    }

    try {
      const response = await this.fetchWithTimeout('/api/branding/logo', {
        cache: 'no-store'
      });

      if (!response.ok) {
        this.applyBrandingPreview(this.defaultLogoPath);
        return;
      }

      const data = await response.json();
      const brandingPath = this.getBrandingPath(data.filename);
      this.applyBrandingPreview(brandingPath);
    } catch (error) {
      if (error.name !== 'AbortError') {
        console.error('Error loading branding settings:', error);
      }
      this.applyBrandingPreview(this.defaultLogoPath);
    }
  }

  async uploadBrandingLogo() {
    if (!this.canManageBranding || !this.brandingFileInput) {
      return;
    }

    const file = this.brandingFileInput.files && this.brandingFileInput.files[0];
    if (!file) {
      this.showBrandingStatus('Please choose a logo file first.', 'error');
      return;
    }

    if (file.size > 100 * 1024) {
      this.showBrandingStatus('File too large. Maximum allowed size is 100 KB.', 'error');
      return;
    }

    const formData = new FormData();
    formData.append('image', file);

    try {
      this.showBrandingStatus('Uploading...', 'info');

      const response = await this.fetchWithTimeout('/api/branding/logo', {
        method: 'POST',
        body: formData
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.message || 'Failed to upload logo');
      }

      this.applyBrandingPreview(this.getBrandingPath(data.filename));
      this.brandingFileInput.value = '';
      this.showBrandingStatus('Logo uploaded successfully.', 'success');
    } catch (error) {
      if (error.name === 'AbortError') {
        this.showBrandingStatus('Upload timed out. Please try again.', 'error');
      } else {
        this.showBrandingStatus(`Error uploading logo: ${error.message}`, 'error');
      }
    }
  }

  async resetBrandingLogo() {
    if (!this.canManageBranding) {
      return;
    }

    try {
      this.showBrandingStatus('Resetting...', 'info');

      const response = await this.fetchWithTimeout('/api/branding/logo', {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json'
        }
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.message || 'Failed to reset logo');
      }

      this.applyBrandingPreview(this.defaultLogoPath);
      if (this.brandingFileInput) {
        this.brandingFileInput.value = '';
      }
      this.showBrandingStatus('Logo reset to default.', 'success');
    } catch (error) {
      if (error.name === 'AbortError') {
        this.showBrandingStatus('Reset timed out. Please try again.', 'error');
      } else {
        this.showBrandingStatus(`Error resetting logo: ${error.message}`, 'error');
      }
    }
  }

  showAppNameStatus(message, type = 'info') {
    if (!this.appNameStatus) {
      return;
    }

    this.appNameStatus.textContent = message;
    this.appNameStatus.className = `settings-status ${type}`;

    if (type === 'success') {
      setTimeout(() => {
        if (this.appNameStatus) {
          this.appNameStatus.textContent = '';
          this.appNameStatus.className = 'settings-status';
        }
      }, 2000);
    }
  }

  async loadAppName() {
    if (!this.canManageBranding || !this.appNameInput) {
      return;
    }

    try {
      const response = await this.fetchWithTimeout('/api/branding/app-name', {
        cache: 'no-store'
      });

      if (!response.ok) {
        return;
      }

      const data = await response.json();
      this.appNameInput.value = data.name || '';
    } catch (error) {
      if (error.name !== 'AbortError') {
        console.error('Error loading app name:', error);
      }
    }
  }

  async saveAppName() {
    if (!this.canManageBranding || !this.appNameInput) {
      return;
    }

    const name = this.appNameInput.value.trim();
    if (!name) {
      this.showAppNameStatus('Please enter a name.', 'error');
      return;
    }

    try {
      this.showAppNameStatus('Saving...', 'info');

      const response = await this.fetchWithTimeout('/api/branding/app-name', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name })
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.message || 'Failed to save app name');
      }

      this.appNameInput.value = data.name;
      this.showAppNameStatus('App name saved. Reinstall the app to see the new name/icon label.', 'success');
    } catch (error) {
      if (error.name === 'AbortError') {
        this.showAppNameStatus('Save timed out. Please try again.', 'error');
      } else {
        this.showAppNameStatus(`Error saving app name: ${error.message}`, 'error');
      }
    }
  }

  async resetAppName() {
    if (!this.canManageBranding) {
      return;
    }

    try {
      this.showAppNameStatus('Resetting...', 'info');

      const response = await this.fetchWithTimeout('/api/branding/app-name', {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json'
        }
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.message || 'Failed to reset app name');
      }

      await this.loadAppName();
      this.showAppNameStatus('App name reset to default.', 'success');
    } catch (error) {
      if (error.name === 'AbortError') {
        this.showAppNameStatus('Reset timed out. Please try again.', 'error');
      } else {
        this.showAppNameStatus(`Error resetting app name: ${error.message}`, 'error');
      }
    }
  }

  getSupportedTimezones() {
    if (typeof Intl !== 'undefined' && typeof Intl.supportedValuesOf === 'function') {
      try {
        const supported = Intl.supportedValuesOf('timeZone');
        if (Array.isArray(supported) && supported.length > 0) {
          return ['UTC', ...supported.filter(tz => tz !== 'UTC')];
        }
      } catch (error) {
        console.warn('Failed to read supported browser timezones:', error);
      }
    }

    return [
      'UTC',
      'Europe/London',
      'Europe/Paris',
      'America/New_York',
      'America/Chicago',
      'America/Denver',
      'America/Los_Angeles',
      'Asia/Tokyo',
      'Asia/Kolkata',
      'Australia/Sydney'
    ];
  }

  async loadTimezoneOptions() {
    if (!this.timezoneSelect) {
      return;
    }

    const timezones = this.getSupportedTimezones();
    this.timezoneSelect.innerHTML = '';

    timezones.forEach(timezone => {
      const option = document.createElement('option');
      option.value = timezone;
      option.textContent = timezone;
      this.timezoneSelect.appendChild(option);
    });
  }

  async loadTimezoneSetting() {
    if (!this.timezoneSelect) {
      return;
    }

    try {
      const response = await fetch('/api/settings/timezone');
      if (!response.ok) {
        this.timezoneSelect.value = 'UTC';
        return;
      }

      const data = await response.json();
      const timezone = (data && data.success && typeof data.value === 'string' && data.value) ? data.value : 'UTC';

      if ([...this.timezoneSelect.options].some(option => option.value === timezone)) {
        this.timezoneSelect.value = timezone;
      } else {
        this.timezoneSelect.value = 'UTC';
      }

      sessionStorage.setItem('timezone', this.timezoneSelect.value || 'UTC');
    } catch (error) {
      console.error('Error loading timezone setting:', error);
      this.timezoneSelect.value = 'UTC';
    }
  }

  async loadBoards() {
    try {
      const response = await fetch('/api/boards');
      const data = await response.json();

      if (data.success) {
        this.renderBoardOptions(data.boards);
      } else {
        this.showStatus('Failed to load boards: ' + data.message, 'error');
      }
    } catch (err) {
      this.showStatus('Error loading boards: ' + err.message, 'error');
    }
  }

  renderBoardOptions(boards) {
    // Clear existing options
    this.defaultBoardSelect.innerHTML = '';

    // Add "None" option
    const noneOption = document.createElement('option');
    noneOption.value = '';
    noneOption.textContent = 'None (Boards page)';
    this.defaultBoardSelect.appendChild(noneOption);

    // Add board options
    boards.forEach(board => {
      const option = document.createElement('option');
      option.value = board.id;
      option.textContent = board.name;
      this.defaultBoardSelect.appendChild(option);
    });
  }

  async loadSettings() {
    try {
      // Load default board
      const boardResponse = await fetch('/api/settings/default_board');
      
      if (boardResponse.ok) {
        const data = await boardResponse.json();
        if (data.success) {
          const defaultBoardId = data.value || '';
          this.defaultBoardSelect.value = defaultBoardId;
        }
      } else if (boardResponse.status === 404) {
        // Setting doesn't exist yet, will be created on save
        this.defaultBoardSelect.value = '';
      } else {
        console.error('Error loading default board:', boardResponse.statusText);
      }

      // Load time format
      const timeResponse = await fetch('/api/settings/time_format');
      
      if (timeResponse.ok) {
        const data = await timeResponse.json();
        if (data.success) {
          const value = data.value || '24';
          const timeFormat = (value === '12' || value === '24') ? value : '24';
          const radio = document.querySelector(`input[name="time-format"][value="${timeFormat}"]`);
          if (radio) {
            radio.checked = true;
          }
        }
      } else if (timeResponse.status === 404) {
        // Setting doesn't exist yet, will be created on save
        const defaultRadio = document.querySelector('input[name="time-format"][value="24"]');
        if (defaultRadio) {
          defaultRadio.checked = true;
        }
      } else {
        console.error('Error loading time format:', timeResponse.statusText);
      }
    } catch (err) {
      console.error('Error loading settings:', err);
    }
  }

  groupThemesByScope(themes) {
    return {
      userThemes: themes.filter(t => !t.system_theme && !t.global_theme).sort((a, b) => a.name.localeCompare(b.name)),
      globalThemes: themes.filter(t => !t.system_theme && t.global_theme).sort((a, b) => a.name.localeCompare(b.name)),
      systemThemes: themes.filter(t => t.system_theme).sort((a, b) => a.name.localeCompare(b.name))
    };
  }

  async loadThemes() {
    try {
      const response = await fetch('/api/themes');
      if (!response.ok) throw new Error('Failed to load themes');
      
      const themes = await response.json();
      const { userThemes, globalThemes, systemThemes } = this.groupThemesByScope(themes);
      
      // Populate theme select
      this.themeSelect.innerHTML = '';
      
      // Add user themes first
      if (userThemes.length > 0) {
        const userGroup = document.createElement('optgroup');
        userGroup.label = 'User Themes';
        userThemes.forEach(theme => {
          const option = document.createElement('option');
          option.value = theme.id;
          option.textContent = theme.name;
          userGroup.appendChild(option);
        });
        this.themeSelect.appendChild(userGroup);
      }

      if (globalThemes.length > 0) {
        const globalGroup = document.createElement('optgroup');
        globalGroup.label = 'Global Themes';
        globalThemes.forEach(theme => {
          const option = document.createElement('option');
          option.value = theme.id;
          option.textContent = theme.name;
          globalGroup.appendChild(option);
        });
        this.themeSelect.appendChild(globalGroup);
      }
      
      // Add system themes
      if (systemThemes.length > 0) {
        const systemGroup = document.createElement('optgroup');
        systemGroup.label = 'System Themes';
        systemThemes.forEach(theme => {
          const option = document.createElement('option');
          option.value = theme.id;
          option.textContent = theme.name;
          systemGroup.appendChild(option);
        });
        this.themeSelect.appendChild(systemGroup);
      }
      
      // Load current theme selection
      const settingsResponse = await fetch('/api/settings/theme');
      if (settingsResponse.ok) {
        const currentTheme = await settingsResponse.json();
        this.themeSelect.value = currentTheme.id;
      }
    } catch (error) {
      console.error('Error loading themes:', error);
    }
  }

  populateThemeOptions(selectElement, themes) {
    if (!selectElement) {
      return;
    }

    const { userThemes, globalThemes, systemThemes } = this.groupThemesByScope(themes);

    selectElement.innerHTML = '';

    if (userThemes.length > 0) {
      const userGroup = document.createElement('optgroup');
      userGroup.label = 'User Themes';
      userThemes.forEach(theme => {
        const option = document.createElement('option');
        option.value = theme.id;
        option.textContent = theme.name;
        userGroup.appendChild(option);
      });
      selectElement.appendChild(userGroup);
    }

    if (globalThemes.length > 0) {
      const globalGroup = document.createElement('optgroup');
      globalGroup.label = 'Global Themes';
      globalThemes.forEach(theme => {
        const option = document.createElement('option');
        option.value = theme.id;
        option.textContent = theme.name;
        globalGroup.appendChild(option);
      });
      selectElement.appendChild(globalGroup);
    }

    if (systemThemes.length > 0) {
      const systemGroup = document.createElement('optgroup');
      systemGroup.label = 'System Themes';
      systemThemes.forEach(theme => {
        const option = document.createElement('option');
        option.value = theme.id;
        option.textContent = theme.name;
        systemGroup.appendChild(option);
      });
      selectElement.appendChild(systemGroup);
    }
  }

  async loadInstanceDefaultTheme() {
    if (!this.instanceDefaultThemeSelect || !this.canManageBranding) {
      return;
    }

    try {
      const response = await fetch('/api/settings/default-theme');
      if (!response.ok) {
        throw new Error('Failed to load instance default theme');
      }

      const payload = await response.json();
      if (!payload.success) {
        throw new Error(payload.message || 'Failed to load instance default theme');
      }

      const availableThemes = Array.isArray(payload.available_themes) ? payload.available_themes : [];
      const promotableThemes = Array.isArray(payload.promotable_themes) ? payload.promotable_themes : [];
      const demotableThemes = Array.isArray(payload.demotable_themes) ? payload.demotable_themes : [];

      this.populateThemeOptions(this.instanceDefaultThemeSelect, availableThemes);
      this.populateThemeOptions(this.promoteGlobalThemeSelect, promotableThemes);
      this.populateThemeOptions(this.demoteGlobalThemeSelect, demotableThemes);

      if (payload.value) {
        this.instanceDefaultThemeSelect.value = String(payload.value);
      }

      this.setEmptyThemeSelectMessage(this.promoteGlobalThemeSelect, 'No user themes available to promote');
      this.setEmptyThemeSelectMessage(this.demoteGlobalThemeSelect, 'No global themes available to demote');
    } catch (error) {
      console.error('Error loading instance default theme:', error);
      this.showStatus('Error loading default theme: ' + error.message, 'error');
    }
  }

  setEmptyThemeSelectMessage(selectElement, message) {
    if (!selectElement) {
      return;
    }

    if (selectElement.options.length === 0) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = message;
      selectElement.appendChild(option);
    }
  }

  async saveInstanceDefaultTheme() {
    if (!this.canManageBranding || !this.instanceDefaultThemeSelect) {
      return;
    }

    try {
      this.showStatus('Saving...', 'info');

      const selectedThemeId = parseInt(this.instanceDefaultThemeSelect.value, 10);
      if (!Number.isInteger(selectedThemeId) || selectedThemeId <= 0) {
        throw new Error('Please select a valid theme');
      }

      const response = await fetch('/api/settings/default-theme', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ theme_id: selectedThemeId })
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.message || 'Failed to save default theme');
      }

      this.showStatus('Saved', 'success');
      setTimeout(() => {
        this.statusElement.textContent = '';
        this.statusElement.className = 'settings-status';
      }, 2000);
    } catch (error) {
      this.showStatus('Error: ' + error.message, 'error');
    }
  }

  async promoteThemeToGlobal() {
    if (!this.canManageBranding || !this.promoteGlobalThemeSelect) {
      return;
    }

    try {
      this.showStatus('Saving...', 'info');
      const themeId = parseInt(this.promoteGlobalThemeSelect.value, 10);
      if (!Number.isInteger(themeId) || themeId <= 0) {
        throw new Error('Please select a valid theme to promote');
      }

      const response = await fetch(`/api/themes/${themeId}/promote-global`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.message || 'Failed to promote theme');
      }

      await this.loadThemes();
      await this.loadInstanceDefaultTheme();
      this.showStatus('Saved', 'success');
    } catch (error) {
      this.showStatus('Error: ' + error.message, 'error');
    }
  }

  async demoteThemeFromGlobal() {
    if (!this.canManageBranding || !this.demoteGlobalThemeSelect) {
      return;
    }

    try {
      this.showStatus('Saving...', 'info');
      const themeId = parseInt(this.demoteGlobalThemeSelect.value, 10);
      if (!Number.isInteger(themeId) || themeId <= 0) {
        throw new Error('Please select a valid theme to demote');
      }

      const response = await fetch(`/api/themes/${themeId}/demote-global`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.message || 'Failed to demote theme');
      }

      await this.loadThemes();
      await this.loadInstanceDefaultTheme();
      this.showStatus('Saved', 'success');
    } catch (error) {
      this.showStatus('Error: ' + error.message, 'error');
    }
  }

  async loadWorkingStyle() {
    try {
      // Populate working style options
      this.workingStyleSelect.innerHTML = '';
      
      const options = [
        { value: 'kanban', label: 'Kanban' },
        { value: 'agile', label: 'Agile' }
      ];
      
      options.forEach(opt => {
        const option = document.createElement('option');
        option.value = opt.value;
        option.textContent = opt.label;
        this.workingStyleSelect.appendChild(option);
      });
      
      // Load current working style setting
      const response = await fetch('/api/settings/working-style');
      if (response.ok) {
        const data = await response.json();
        if (data.success) {
          this.workingStyleSelect.value = data.value || 'kanban';
        }
      } else if (response.status === 404) {
        // Setting doesn't exist yet, default to kanban
        this.workingStyleSelect.value = 'kanban';
      } else {
        console.error('Error loading working style:', response.statusText);
      }
    } catch (error) {
      console.error('Error loading working style:', error);
    }
  }
  
  async onThemeChange() {
    try {
      const themeId = parseInt(this.themeSelect.value);
      
      // Save theme selection
      const response = await fetch('/api/settings/theme', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme_id: themeId })
      });
      
      if (!response.ok) throw new Error('Failed to save theme selection');
      
      // Apply the theme colors
      await this.applyThemeColors();
      
      this.showStatus('Theme changed successfully', 'success');
    } catch (error) {
      console.error('Error changing theme:', error);
      this.showStatus('Error changing theme: ' + error.message, 'error');
    }
  }
  
  editTheme() {
    const themeId = this.themeSelect.value;
    // Navigate to theme builder with selected theme
    window.location.href = `/theme-builder.html?theme=${themeId}`;
  }

  async applyThemeColors() {
    // Fetch and apply theme from API
    try {
      const response = await fetch('/api/settings/theme');
      const theme = await response.json();
      const root = document.documentElement;
      const settings = theme.settings;
      
      // Apply all CSS variables
      for (const [key, value] of Object.entries(settings)) {
        root.style.setProperty(`--${key}`, value);
      }
      
      // Apply background image if present
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
      console.error('Error loading theme:', error);
    }
  }

  async saveSettings() {
    try {
      // Show saving status
      this.showStatus('Saving...', 'info');
      
      const defaultBoardId = this.defaultBoardSelect.value;
      
      // Convert empty string to null for JSON
      const value = defaultBoardId === '' ? null : parseInt(defaultBoardId, 10);

      const response = await fetch('/api/settings/default_board', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ value })
      });

      const data = await response.json();

      if (!response.ok) {
        // Extract error message from API response if available
        const errorMessage = data.message || `HTTP error! status: ${response.status}`;
        throw new Error(errorMessage);
      }

      if (data.success) {
        this.showStatus('Saved', 'success');

        // Clear status after 2 seconds
        setTimeout(() => {
          this.statusElement.textContent = '';
          this.statusElement.className = 'settings-status';
        }, 2000);
      } else {
        this.showStatus('Error: ' + data.message, 'error');
      }

    } catch (err) {
      this.showStatus('Error: ' + err.message, 'error');
    }
  }

  async saveTimeFormat() {
    try {
      // Show saving status
      this.showStatus('Saving...', 'info');
      
      const selectedRadio = document.querySelector('input[name="time-format"]:checked');
      const timeFormat = selectedRadio ? selectedRadio.value : '24';

      const response = await fetch('/api/settings/time_format', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ value: timeFormat })
      });

      const data = await response.json();

      if (!response.ok) {
        const errorMessage = data.message || `HTTP error! status: ${response.status}`;
        throw new Error(errorMessage);
      }

      if (data.success) {
        // Update session storage to invalidate cache
        sessionStorage.setItem('timeFormat', timeFormat);
        
        this.showStatus('Saved', 'success');

        // Clear status after 2 seconds
        setTimeout(() => {
          this.statusElement.textContent = '';
          this.statusElement.className = 'settings-status';
        }, 2000);
      } else {
        this.showStatus('Error: ' + data.message, 'error');
      }

    } catch (err) {
      this.showStatus('Error: ' + err.message, 'error');
    }
  }

  async saveTimezone() {
    if (!this.timezoneSelect) {
      return;
    }

    try {
      this.showStatus('Saving...', 'info');

      const timezone = this.timezoneSelect.value || 'UTC';
      const response = await fetch('/api/settings/timezone', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ value: timezone })
      });

      const data = await response.json();
      if (!response.ok) {
        const errorMessage = data.message || `HTTP error! status: ${response.status}`;
        throw new Error(errorMessage);
      }

      if (data.success) {
        sessionStorage.setItem('timezone', timezone);
        this.showStatus('Saved', 'success');

        setTimeout(() => {
          this.statusElement.textContent = '';
          this.statusElement.className = 'settings-status';
        }, 2000);
      } else {
        this.showStatus('Error: ' + data.message, 'error');
      }
    } catch (err) {
      this.showStatus('Error: ' + err.message, 'error');
    }
  }

  async saveWorkingStyle() {
    try {
      // Show saving status
      this.showStatus('Saving...', 'info');
      
      const workingStyle = this.workingStyleSelect.value;

      const response = await fetch('/api/settings/working-style', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ value: workingStyle })
      });

      const data = await response.json();

      if (!response.ok) {
        const errorMessage = data.message || `HTTP error! status: ${response.status}`;
        throw new Error(errorMessage);
      }

      if (data.success) {
        // Update session storage
        sessionStorage.setItem('workingStyle', workingStyle);
        
        this.showStatus('Saved', 'success');

        // Clear status after 2 seconds
        setTimeout(() => {
          this.statusElement.textContent = '';
          this.statusElement.className = 'settings-status';
        }, 2000);
      } else {
        this.showStatus('Error: ' + data.message, 'error');
      }

    } catch (err) {
      this.showStatus('Error: ' + err.message, 'error');
    }
  }

  attachEventListeners() {
    this.defaultBoardSelect.addEventListener('change', () => {
      // Clear any pending save
      if (this.saveTimeout) {
        clearTimeout(this.saveTimeout);
      }
      
      // Show pending status immediately
      this.showStatus('Pending...', 'info');
      
      // Debounce save by 500ms
      this.saveTimeout = setTimeout(() => {
        this.saveSettings();
      }, 500);
    });

    // Time format radio buttons
    this.timeFormatRadios.forEach(radio => {
      radio.addEventListener('change', () => {
        // Clear any pending save
        if (this.saveTimeout) {
          clearTimeout(this.saveTimeout);
        }
        
        // Show pending status immediately
        this.showStatus('Pending...', 'info');
        
        // Debounce save by 500ms
        this.saveTimeout = setTimeout(() => {
          this.saveTimeFormat();
        }, 500);
      });
    });

    if (this.timezoneSelect) {
      this.timezoneSelect.addEventListener('change', () => {
        if (this.saveTimeout) {
          clearTimeout(this.saveTimeout);
        }

        this.showStatus('Pending...', 'info');

        this.saveTimeout = setTimeout(() => {
          this.saveTimezone();
        }, 500);
      });
    }

    // Theme selector
    if (this.themeSelect) {
      this.themeSelect.addEventListener('change', () => {
        this.onThemeChange();
      });
    }
    
    // Working style selector
    if (this.workingStyleSelect) {
      this.workingStyleSelect.addEventListener('change', () => {
        // Clear any pending save
        if (this.saveTimeout) {
          clearTimeout(this.saveTimeout);
        }
        
        // Show pending status immediately
        this.showStatus('Pending...', 'info');
        
        // Debounce save by 500ms
        this.saveTimeout = setTimeout(() => {
          this.saveWorkingStyle();
        }, 500);
      });
    }
    
    // Edit theme button
    const editThemeBtn = document.getElementById('edit-theme-btn');
    if (editThemeBtn) {
      editThemeBtn.addEventListener('click', () => {
        this.editTheme();
      });
    }

    if (this.canManageBranding && this.brandingUploadBtn) {
      this.brandingUploadBtn.addEventListener('click', () => {
        this.uploadBrandingLogo();
      });
    }

    if (this.canManageBranding && this.brandingResetBtn) {
      this.brandingResetBtn.addEventListener('click', () => {
        this.resetBrandingLogo();
      });
    }

    if (this.canManageBranding && this.appNameSaveBtn) {
      this.appNameSaveBtn.addEventListener('click', () => {
        this.saveAppName();
      });
    }

    if (this.canManageBranding && this.appNameResetBtn) {
      this.appNameResetBtn.addEventListener('click', () => {
        this.resetAppName();
      });
    }

    if (this.canManageBranding && this.instanceDefaultThemeSaveBtn) {
      this.instanceDefaultThemeSaveBtn.addEventListener('click', () => {
        this.saveInstanceDefaultTheme();
      });
    }

    if (this.canManageBranding && this.promoteGlobalThemeBtn) {
      this.promoteGlobalThemeBtn.addEventListener('click', () => {
        this.promoteThemeToGlobal();
      });
    }

    if (this.canManageBranding && this.demoteGlobalThemeBtn) {
      this.demoteGlobalThemeBtn.addEventListener('click', () => {
        this.demoteThemeFromGlobal();
      });
    }
  }

  showStatus(message, type = 'info') {
    this.statusElement.textContent = message;
    this.statusElement.className = `settings-status ${type}`;
  }
}

// Initialize settings when page loads
document.addEventListener('DOMContentLoaded', () => {
  const settings = new Settings();
  settings.init();
});
