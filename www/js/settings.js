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
  }

  async init() {
    // Match other permission-gated pages: wait until header.js has loaded user context.
    if (!window.userDataReady) {
      setTimeout(() => this.init(), 100);
      return;
    }

    this.initializeGlobalSettingsVisibility();

    // Personal preferences live on the profile page, so old links land there
    if (!this.canManageBranding) {
      window.location.replace('/profile.html#preferences');
      return;
    }

    await this.loadInstanceDefaultTheme();
    await this.loadBrandingSettings();
    await this.loadAppName();
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
