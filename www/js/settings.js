// Instance settings page functionality

class Settings {
  constructor() {
    this.globalSettingsPanel = document.getElementById('global-settings-panel');
    this.instanceDefaultThemeSelect = document.getElementById('instance-default-theme');
    this.instanceDefaultThemeSaveBtn = document.getElementById('instance-default-theme-save-btn');
    this.promoteGlobalThemeSelect = document.getElementById('promote-global-theme');
    this.promoteGlobalThemeBtn = document.getElementById('promote-global-theme-btn');
    this.demoteGlobalThemeSelect = document.getElementById('demote-global-theme');
    this.demoteGlobalThemeBtn = document.getElementById('demote-global-theme-btn');
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
    this.canManageBranding = false;
    this.tabs = Array.from(document.querySelectorAll('.settings-tab'));
    this.instancePanel = document.getElementById('settings-panel-instance');
    this.globalBoardPanel = document.getElementById('settings-panel-global-board');
    this.globalBoardList = document.getElementById('global-board-settings-list');
    this.canManageGlobalBoard = false;
    this.framesPanel = document.getElementById('settings-panel-frames');
    this.tabFrames = new Map();
  }

  async init() {
    // Match other permission-gated pages: wait until header.js has loaded user context.
    if (!window.userDataReady) {
      setTimeout(() => this.init(), 100);
      return;
    }

    this.initializeGlobalSettingsVisibility();

    // Personal preferences live on the profile page, so old links land there
    const hasAccess = typeof hasPermission === 'function'
      && window.INSTANCE_SETTINGS_PERMISSIONS.some(permission => hasPermission(permission));
    if (!hasAccess) {
      window.location.replace('/profile.html#preferences');
      return;
    }

    this.initializeTabs();

    if (this.canManageBranding) {
      await this.loadInstanceDefaultTheme();
      await this.loadBrandingSettings();
      await this.loadAppName();
    }
    if (this.canManageGlobalBoard) {
      await this.loadGlobalBoards();
    }
    this.attachEventListeners();
  }

  initializeGlobalSettingsVisibility() {
    this.canManageBranding = typeof hasPermission === 'function' && hasPermission('branding.edit');
    this.canManageGlobalBoard = typeof hasPermission === 'function'
      && hasPermission('global_board.manage');

    if (!this.globalSettingsPanel) {
      return;
    }

    this.globalSettingsPanel.hidden = !this.canManageBranding;
  }

  getVisibleTabs() {
    return this.tabs.filter(tab => tab.style.display !== 'none');
  }

  // header.js has already hidden the tabs this user's permissions don't allow.
  initializeTabs() {
    if (!this.canManageBranding) {
      document.getElementById('settings-tab-instance').style.display = 'none';
    }
    const globalBoardTab = document.getElementById('settings-tab-global-board');
    if (globalBoardTab) {
      globalBoardTab.style.display = this.canManageGlobalBoard ? '' : 'none';
    }

    this.getVisibleTabs().forEach((tab) => {
      tab.addEventListener('click', (e) => {
        e.preventDefault();
        this.selectTab(tab);
      });

      tab.addEventListener('keydown', (e) => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') {
          return;
        }

        e.preventDefault();
        const visibleTabs = this.getVisibleTabs();
        const step = e.key === 'ArrowRight' ? 1 : -1;
        const next = visibleTabs[(visibleTabs.indexOf(tab) + step + visibleTabs.length) % visibleTabs.length];
        this.selectTab(next);
        next.focus();
      });
    });

    const requested = this.getTabForHash();
    this.selectTab(requested || this.getVisibleTabs()[0]);

    window.addEventListener('hashchange', () => {
      const tab = this.getTabForHash();
      if (tab) {
        this.selectTab(tab);
      }
    });
  }

  getTabForHash() {
    return this.getVisibleTabs().find(tab => `#${tab.dataset.tab}` === window.location.hash);
  }

  selectTab(selectedTab) {
    this.tabs.forEach((tab) => {
      const selected = tab === selectedTab;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });

    // Tabs linking to a #hash are panels on this page; the rest load in a frame.
    const isPageTab = selectedTab.getAttribute('href').startsWith('#');
    this.instancePanel.hidden = selectedTab.dataset.tab !== 'instance';
    if (this.globalBoardPanel) {
      this.globalBoardPanel.hidden = selectedTab.dataset.tab !== 'global-board';
    }
    this.framesPanel.hidden = isPageTab;

    this.tabFrames.forEach((frame) => {
      frame.hidden = true;
    });
    if (!isPageTab) {
      this.framesPanel.setAttribute('aria-labelledby', selectedTab.id);
      this.showTabFrame(selectedTab);
    }

    history.replaceState(null, '', `#${selectedTab.dataset.tab}`);
  }

  // Frames are kept after the first visit so unsaved work survives changing tabs.
  showTabFrame(tab) {
    let frame = this.tabFrames.get(tab);
    if (!frame) {
      frame = document.createElement('iframe');
      frame.className = 'settings-tab-frame';
      frame.title = tab.textContent;
      frame.src = `${tab.getAttribute('href')}?embedded=1`;
      this.tabFrames.set(tab, frame);
      this.framesPanel.appendChild(frame);
    }
    frame.hidden = false;
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

      populateThemeOptions(this.instanceDefaultThemeSelect, availableThemes);
      populateThemeOptions(this.promoteGlobalThemeSelect, promotableThemes);
      populateThemeOptions(this.demoteGlobalThemeSelect, demotableThemes);

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

      await this.loadInstanceDefaultTheme();
      this.showStatus('Saved', 'success');
    } catch (error) {
      this.showStatus('Error: ' + error.message, 'error');
    }
  }

  async loadGlobalBoards() {
    if (!this.canManageGlobalBoard || !this.globalBoardList) {
      return;
    }

    try {
      const response = await this.fetchWithTimeout('/api/global-boards', { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.message || 'Failed to load global boards');
      }

      const boards = (Array.isArray(data.global_boards) ? data.global_boards : [])
        .filter(board => board.can_manage);
      this.globalBoardList.replaceChildren();
      if (boards.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'setting-help';
        empty.textContent = 'There are no global boards you can manage.';
        this.globalBoardList.appendChild(empty);
        return;
      }
      boards.forEach(board => this.globalBoardList.appendChild(this.buildGlobalBoardForm(board)));
    } catch (error) {
      if (error.name !== 'AbortError') {
        console.error('Error loading global boards:', error);
      }
      this.globalBoardList.replaceChildren();
      const message = document.createElement('p');
      message.className = 'settings-status error';
      message.setAttribute('role', 'alert');
      message.textContent = 'Could not load global board settings. Please reload the page.';
      this.globalBoardList.appendChild(message);
    }
  }

  // One form per global board, built from DOM nodes because the name is user text.
  buildGlobalBoardForm(board) {
    const prefix = `global-board-${board.id}`;
    const form = document.createElement('form');
    form.className = 'global-board-settings-form';
    form.dataset.globalBoardId = String(board.id);
    form.noValidate = true;

    const nameItem = document.createElement('div');
    nameItem.className = 'setting-item';
    const nameLabel = document.createElement('label');
    nameLabel.htmlFor = `${prefix}-name`;
    nameLabel.textContent = 'Name';
    const nameHelp = document.createElement('p');
    nameHelp.className = 'setting-help';
    nameHelp.id = `${prefix}-name-help`;
    nameHelp.textContent = 'Shown in the view menu and as the global board page title. Up to 100 characters.';
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.id = `${prefix}-name`;
    nameInput.className = 'setting-select global-board-name-input';
    nameInput.maxLength = 100;
    nameInput.required = true;
    nameInput.value = board.name || '';
    nameInput.setAttribute('aria-describedby', nameHelp.id);
    nameItem.append(nameLabel, nameHelp, nameInput);

    const daysItem = document.createElement('div');
    daysItem.className = 'setting-item';
    const daysLabel = document.createElement('label');
    daysLabel.htmlFor = `${prefix}-done-mode`;
    daysLabel.textContent = 'Show done cards for';
    const daysHelp = document.createElement('p');
    daysHelp.className = 'setting-help';
    daysHelp.id = `${prefix}-done-help`;
    daysHelp.textContent = 'Done cards older than this are hidden from the global board but stay promoted. '
      + 'Unticking done on a hidden card brings it back.';
    const daysRow = document.createElement('div');
    daysRow.className = 'global-board-done-row';
    const modeSelect = document.createElement('select');
    modeSelect.id = `${prefix}-done-mode`;
    modeSelect.className = 'setting-select global-board-done-mode';
    modeSelect.setAttribute('aria-describedby', daysHelp.id);
    [['days', 'A number of days'], ['always', 'None (always show)']].forEach(([value, text]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      modeSelect.appendChild(option);
    });
    const daysInput = document.createElement('input');
    daysInput.type = 'number';
    daysInput.id = `${prefix}-done-days`;
    daysInput.className = 'setting-select global-board-done-days';
    daysInput.min = '1';
    daysInput.max = '3650';
    daysInput.step = '1';
    daysInput.inputMode = 'numeric';
    daysInput.setAttribute('aria-label', 'Days done cards show');
    const daysSuffix = document.createElement('span');
    daysSuffix.className = 'global-board-done-suffix';
    daysSuffix.textContent = 'days';
    daysRow.append(modeSelect, daysInput, daysSuffix);
    daysItem.append(daysLabel, daysHelp, daysRow);

    const alwaysShow = board.done_visible_days === null || board.done_visible_days === undefined;
    modeSelect.value = alwaysShow ? 'always' : 'days';
    daysInput.value = alwaysShow ? '14' : String(board.done_visible_days);
    const syncDaysInput = () => {
      const hidden = modeSelect.value === 'always';
      daysInput.hidden = hidden;
      daysSuffix.hidden = hidden;
    };
    syncDaysInput();
    modeSelect.addEventListener('change', syncDaysInput);

    const actions = document.createElement('div');
    actions.className = 'branding-actions';
    const saveBtn = document.createElement('button');
    saveBtn.type = 'submit';
    saveBtn.className = 'btn btn-primary global-board-save-btn';
    saveBtn.textContent = 'Save';
    actions.appendChild(saveBtn);

    const status = document.createElement('div');
    status.className = 'settings-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');

    form.append(nameItem, daysItem, actions, status);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.saveGlobalBoard(board.id, { nameInput, modeSelect, daysInput, saveBtn, status });
    });
    return form;
  }

  showGlobalBoardStatus(status, message, type) {
    status.textContent = message;
    status.className = `settings-status ${type}`;
  }

  async saveGlobalBoard(globalBoardId, { nameInput, modeSelect, daysInput, saveBtn, status }) {
    const name = nameInput.value.trim();
    if (!name) {
      this.showGlobalBoardStatus(status, 'Please enter a name.', 'error');
      nameInput.focus();
      return;
    }

    let doneVisibleDays = null;
    if (modeSelect.value === 'days') {
      const raw = daysInput.value.trim();
      doneVisibleDays = Number(raw);
      if (!/^\d+$/.test(raw) || doneVisibleDays < 1 || doneVisibleDays > 3650) {
        this.showGlobalBoardStatus(status, 'Enter a whole number of days from 1 to 3650.', 'error');
        daysInput.focus();
        return;
      }
    }

    saveBtn.disabled = true;
    this.showGlobalBoardStatus(status, 'Saving...', 'info');
    try {
      const response = await this.fetchWithTimeout(`/api/global-boards/${encodeURIComponent(globalBoardId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, done_visible_days: doneVisibleDays })
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.message || 'Failed to save global board settings');
      }

      nameInput.value = data.global_board.name;
      this.showGlobalBoardStatus(status, 'Saved', 'success');
      setTimeout(() => {
        if (status.classList.contains('success')) {
          this.showGlobalBoardStatus(status, '', '');
        }
      }, 2000);
    } catch (error) {
      if (error.name === 'AbortError') {
        this.showGlobalBoardStatus(status, 'Save timed out. Please try again.', 'error');
      } else {
        this.showGlobalBoardStatus(status, `Error saving: ${error.message}`, 'error');
      }
    } finally {
      saveBtn.disabled = false;
    }
  }

  attachEventListeners() {
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
