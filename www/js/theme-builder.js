// Theme Builder functionality - Database-backed version

class ThemeBuilder {
  constructor() {
    this.themeSelect = null;
    this.saveBtn = null;
    this.statusDiv = null;
    this.colorInputs = {};
    this.themes = {}; // Will be loaded from API
    this.currentTheme = null;
    this.currentThemeData = null;
    this.permissions = {
      canViewThemes: true,
      canCreateTheme: true,
      canEditTheme: true,
      canRenameTheme: true,
      canDeleteTheme: true
    };
  }
  
  /**
   * Safely parse JSON response, handling non-JSON errors
   * @param {Response} response - Fetch response object
   * @returns {Promise<Object>} Parsed JSON data or error object
   */
  async parseResponse(response) {
    try {
      const data = await response.json();
      if (!response.ok) {
        // Response parsed successfully but HTTP status indicates error
        return data;
      }
      return data;
    } catch (error) {
      // JSON parsing failed
      return {
        success: false,
        message: response.ok 
          ? `Invalid JSON response from server` 
          : `HTTP error! status: ${response.status}`
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

  getRequestTimeoutMs(baseTimeoutMs = 5000, maxTimeoutMs = 25000) {
    return Math.min(baseTimeoutMs * this.getNetworkTimeoutMultiplier(), maxTimeoutMs);
  }

  createTimeoutController(baseTimeoutMs = 5000, maxTimeoutMs = 25000) {
    const timeoutMs = this.getRequestTimeoutMs(baseTimeoutMs, maxTimeoutMs);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    return { controller, timeoutId, timeoutMs };
  }
  
  /**
   * Escape HTML special characters to prevent XSS
   * @param {string} unsafe - Unsafe string to escape
   * @returns {string} Escaped string
   */
  escapeHtml(unsafe) {
    if (typeof unsafe !== 'string') {
      return '';
    }
    return unsafe
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
  
  /**
   * Show error toast notification
   */
  showErrorToast(message) {
    if (window.header && typeof window.header.showErrorToast === 'function') {
      window.header.showErrorToast(message);
    } else {
      this.showStatus(message, 'error');
    }
  }
  
  /**
   * Show success toast notification
   */
  showSuccessToast(message) {
    if (window.header && typeof window.header.showSuccessToast === 'function') {
      window.header.showSuccessToast(message);
    } else {
      this.showStatus(message, 'success');
    }
  }
  
  async init() {
    this.themeSelect = document.getElementById('theme-builder-select');
    this.saveBtn = document.getElementById('save-theme-btn');
    this.applyBtn = document.getElementById('apply-theme-btn');
    this.statusDiv = document.getElementById('theme-status');
    this.backgroundSelect = document.getElementById('background-image-select');

    // Initialize endpoint permission mapping so theme controls can be gated by
    // exact API actions (edit, rename, create, delete).
    if (window.PermissionManager) {
      const permissionInitSuccess = await PermissionManager.init();
      if (!permissionInitSuccess) {
        console.warn('Failed to initialize PermissionManager for theme builder page');
      }
    }

    this.refreshPermissionCapabilities();

    if (!this.permissions.canViewThemes) {
      if (typeof showAccessDenied === 'function') {
        showAccessDenied('You need the "theme.view" permission to access this page.');
      } else {
        this.showStatus('You do not have permission to access this page.', 'error');
      }
      return;
    }
    
    // Initialize all color inputs
    this.initColorInputs();
    
    // Load themes and background images from API
    await Promise.all([
      this.loadThemes(),
      this.loadBackgroundImages()
    ]);
    
    // Set up event listeners
    this.themeSelect.addEventListener('change', () => this.onThemeChange());
    this.saveBtn.addEventListener('click', () => this.saveTheme());
    this.applyBtn.addEventListener('click', () => this.applyTheme());
    this.backgroundSelect.addEventListener('change', () => this.onBackgroundChange());
    
    // Copy theme functionality
    document.getElementById('copy-theme-btn').addEventListener('click', () => this.showCopyModal());
    document.getElementById('copy-theme-close').addEventListener('click', () => this.hideCopyModal());
    document.getElementById('copy-theme-cancel').addEventListener('click', () => this.hideCopyModal());
    document.getElementById('copy-theme-confirm').addEventListener('click', () => this.confirmCopyTheme());
    
    // Rename theme functionality
    document.getElementById('rename-theme-btn').addEventListener('click', () => this.showRenameModal());
    document.getElementById('rename-theme-close').addEventListener('click', () => this.hideRenameModal());
    document.getElementById('rename-theme-cancel').addEventListener('click', () => this.hideRenameModal());
    document.getElementById('rename-theme-confirm').addEventListener('click', () => this.confirmRenameTheme());
    
    // Delete theme functionality
    document.getElementById('delete-theme-btn').addEventListener('click', () => this.showDeleteModal());
    document.getElementById('delete-theme-close').addEventListener('click', () => this.hideDeleteModal());
    document.getElementById('delete-theme-cancel').addEventListener('click', () => this.hideDeleteModal());
    document.getElementById('delete-theme-confirm').addEventListener('click', () => this.confirmDeleteTheme());
    
    // Import/Export
    document.getElementById('import-theme-btn').addEventListener('click', () => this.importTheme());
    document.getElementById('export-theme-btn').addEventListener('click', () => this.exportTheme());
    
    // Background image
    document.getElementById('upload-bg-btn').addEventListener('click', () => this.uploadBackground());
    document.getElementById('download-bg-btn').addEventListener('click', () => this.downloadBackground());
    document.getElementById('bg-image-input').addEventListener('change', (e) => this.handleBackgroundUpload(e));
    document.getElementById('import-theme-input').addEventListener('change', (e) => this.handleThemeImport(e));

    // Apply global permission-based button states not tied to system/user theme type.
    this.applyPermissionBasedRendering();
    
    // Check for theme parameter in URL
    const urlParams = new URLSearchParams(window.location.search);
    const themeParam = urlParams.get('theme');
    if (themeParam && this.themes[themeParam]) {
      this.themeSelect.value = themeParam;
    }
    
    // Load initial theme
    if (this.themeSelect.value) {
      await this.onThemeChange();
    }
  }

  refreshPermissionCapabilities() {
    if (!window.PermissionManager || !PermissionManager.initialized) {
      this.permissions = {
        canViewThemes: true,
        canCreateTheme: true,
        canEditTheme: true,
        canRenameTheme: true,
        canDeleteTheme: true
      };
      return;
    }

    this.permissions = {
      canViewThemes: PermissionManager.canCallEndpoint('GET', '/api/themes'),
      canCreateTheme: PermissionManager.canCallEndpoint('POST', '/api/themes'),
      canEditTheme: PermissionManager.canCallEndpoint('PUT', '/api/themes/:id'),
      canRenameTheme: PermissionManager.canCallEndpoint('PUT', '/api/themes/:id/rename'),
      canDeleteTheme: PermissionManager.canCallEndpoint('DELETE', '/api/themes/:id')
    };
  }

  applyPermissionBasedRendering() {
    const copyBtn = document.getElementById('copy-theme-btn');
    const importBtn = document.getElementById('import-theme-btn');

    if (copyBtn && !this.permissions.canCreateTheme) {
      copyBtn.disabled = true;
      copyBtn.title = 'You do not have permission to create themes.';
    }

    if (importBtn && !this.permissions.canCreateTheme) {
      importBtn.disabled = true;
      importBtn.title = 'You do not have permission to import themes.';
    }
  }
  
  initColorInputs() {
    // Get all color inputs
    const colorInputs = document.querySelectorAll('input[type="color"]');
    
    colorInputs.forEach(input => {
      const variableName = input.id;
      const textInput = input.nextElementSibling;
      
      this.colorInputs[variableName] = { colorInput: input, textInput };
      
      // Sync color picker with text input
      input.addEventListener('input', (e) => {
        textInput.value = e.target.value.toUpperCase();
        this.applyThemePreview();
      });
      
      // Sync text input with color picker
      textInput.addEventListener('input', (e) => {
        const value = e.target.value;
        if (/^#[0-9A-F]{6}$/i.test(value)) {
          input.value = value;
          this.applyThemePreview();
        }
      });
    });
  }
  
  /**
   * Get or create the User Themes optgroup and add a theme option to it
   * @param {string} themeId - The theme ID
   * @param {string} themeName - The theme display name
   * @returns {HTMLOptionElement} The created option element
   */
  addThemeToUserGroup(themeId, themeName) {
    // Find or create User Themes optgroup
    let userGroup = this.themeSelect.querySelector('optgroup[label="User Themes"]');
    if (!userGroup) {
      userGroup = document.createElement('optgroup');
      userGroup.label = 'User Themes';
      // Insert before System Themes if it exists, otherwise append
      const systemGroup = this.themeSelect.querySelector('optgroup[label="System Themes"]');
      if (systemGroup) {
        this.themeSelect.insertBefore(userGroup, systemGroup);
      } else {
        this.themeSelect.appendChild(userGroup);
      }
    }
    
    // Create and append the option
    const option = document.createElement('option');
    option.value = themeId;
    option.textContent = themeName;
    userGroup.appendChild(option);
    
    return option;
  }

  addThemeGroup(label, themes) {
    if (!themes || themes.length === 0) {
      return;
    }

    const group = document.createElement('optgroup');
    group.label = label;
    themes.forEach(theme => {
      this.themes[theme.id] = theme;
      const option = document.createElement('option');
      option.value = theme.id;
      option.textContent = theme.name;
      group.appendChild(option);
    });
    this.themeSelect.appendChild(group);
  }
  
  async loadThemes(preserveSelection = false) {
    // Store current selection if preserving
    const currentSelection = preserveSelection ? this.themeSelect.value : null;
    const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
    
    try {
      const response = await fetch('/api/themes', {
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const themes = await this.parseResponse(response);
      
      if (!response.ok || (themes.success === false)) {
        throw new Error(themes.message || themes.error || 'Failed to load themes');
      }
      this.themes = {};
      
      // Split into user, global, and system themes
      const userThemes = themes.filter(t => !t.system_theme && !t.global_theme).sort((a, b) => a.name.localeCompare(b.name));
      const globalThemes = themes.filter(t => !t.system_theme && t.global_theme).sort((a, b) => a.name.localeCompare(b.name));
      const systemThemes = themes.filter(t => t.system_theme).sort((a, b) => a.name.localeCompare(b.name));
      
      // Clear existing options
      this.themeSelect.innerHTML = '';
      this.addThemeGroup('User Themes', userThemes);
      this.addThemeGroup('Global Themes', globalThemes);
      this.addThemeGroup('System Themes', systemThemes);
      
      // Restore preserved selection if requested and it exists in the loaded themes
      if (preserveSelection && currentSelection && this.themes[currentSelection]) {
        this.themeSelect.value = currentSelection;
      } else {
        // Only load current theme selection if no URL parameter and not preserving
        const urlParams = new URLSearchParams(window.location.search);
        const themeParam = urlParams.get('theme');
        
        if (!themeParam) {
          // Load current theme selection from settings
          const {
            controller: settingsController,
            timeoutId: settingsTimeoutId,
            timeoutMs: settingsTimeoutMs
          } = this.createTimeoutController();
          
          try {
            const settingsResponse = await fetch('/api/settings/theme', {
              signal: settingsController.signal
            });
            
            clearTimeout(settingsTimeoutId);
            
            if (settingsResponse.ok) {
              const currentTheme = await this.parseResponse(settingsResponse);
              if (currentTheme.id) {
                this.themeSelect.value = currentTheme.id;
              }
            }
          } catch (err) {
            clearTimeout(settingsTimeoutId);
            if (err.name === 'AbortError') {
              console.error(`Settings fetch timed out after ${Math.round(settingsTimeoutMs / 1000)} seconds`);
            } else {
              console.error('Error fetching settings:', err);
            }
          }
        }
      }
    } catch (error) {
      clearTimeout(timeoutId);
      
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        console.error(`Themes fetch timed out after ${timeoutSeconds} seconds`);
        this.showErrorToast(`Request timed out after ${timeoutSeconds}s. Check your connection.`);
      } else {
        console.error('Error loading themes:', error);
        this.showErrorToast('Error loading themes: ' + error.message);
      }
    }
  }
  
  async loadBackgroundImages() {
    const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
    
    try {
      const response = await fetch('/api/themes/images', {
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const data = await this.parseResponse(response);
      
      if (!response.ok || (data.success === false)) {
        throw new Error(data.message || data.error || 'Failed to load background images');
      }
      const images = data.images || [];
      
      // Clear existing options except "None"
      this.backgroundSelect.innerHTML = '<option value="none">None (Use Colors)</option>';
      
      // Add image options
      images.forEach(filename => {
        const option = document.createElement('option');
        option.value = filename;
        option.textContent = filename;
        this.backgroundSelect.appendChild(option);
      });
    } catch (error) {
      clearTimeout(timeoutId);
      
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        console.error(`Background images fetch timed out after ${timeoutSeconds} seconds`);
        this.showErrorToast(`Request timed out after ${timeoutSeconds}s. Check your connection.`);
      } else {
        console.error('Error loading background images:', error);
        this.showErrorToast('Error loading background images: ' + error.message);
      }
    }
  }
  
  onBackgroundChange() {
    const selectedValue = this.backgroundSelect.value;
    
    // Don't update currentThemeData - keep original for comparison
    // The change will be saved when user clicks Save
    
    // Apply the background change immediately to preview
    this.applyThemePreview();
    
    // Update download button state
    const downloadBtn = document.getElementById('download-bg-btn');
    downloadBtn.disabled = selectedValue === 'none';
  }
  
  async onThemeChange() {
    const themeId = parseInt(this.themeSelect.value);
    const theme = this.themes[themeId];
    
    if (!theme) {
      console.error('Theme not found:', themeId);
      return;
    }
    
    this.currentTheme = themeId;
    this.currentThemeData = theme;
    
    // Load theme colors into inputs
    this.loadThemeColors(theme.settings);
    
    // Update background image display
    this.updateBackgroundDisplay(theme.background_image);
    
    // Apply theme preview
    this.applyThemePreview();
    
    // Update save button state
    this.updateSaveButtonState(theme.system_theme || theme.global_theme);
  }
  
  loadThemeColors(settings) {
    for (const [key, value] of Object.entries(settings)) {
      if (this.colorInputs[key]) {
        this.colorInputs[key].colorInput.value = value;
        this.colorInputs[key].textInput.value = value.toUpperCase();
      }
    }
  }
  
  updateBackgroundDisplay(filename) {
    // Set background selector value
    if (filename) {
      this.backgroundSelect.value = filename;
    } else {
      this.backgroundSelect.value = 'none';
    }
    
    // Update download button state
    const downloadBtn = document.getElementById('download-bg-btn');
    downloadBtn.disabled = !filename;
  }
  
  updateSaveButtonState(isReadOnlyTheme) {
    const renameBtn = document.getElementById('rename-theme-btn');
    const deleteBtn = document.getElementById('delete-theme-btn');
    const canEditTheme = this.permissions.canEditTheme;
    const canRenameTheme = this.permissions.canRenameTheme;
    const canDeleteTheme = this.permissions.canDeleteTheme;
    
    if (isReadOnlyTheme || !canEditTheme) {
      this.saveBtn.disabled = true;
      this.saveBtn.title = isReadOnlyTheme
        ? 'System and global themes cannot be modified directly. Create a copy to edit it.'
        : 'You do not have permission to edit themes.';
    } else {
      this.saveBtn.disabled = false;
      this.saveBtn.title = 'Save changes to this theme';
    }

    if (isReadOnlyTheme || !canRenameTheme) {
      renameBtn.disabled = true;
      renameBtn.title = isReadOnlyTheme
        ? 'System and global themes cannot be renamed directly.'
        : 'You do not have permission to rename themes.';
    } else {
      renameBtn.disabled = false;
      renameBtn.title = 'Rename the selected theme';
    }

    if (isReadOnlyTheme || !canDeleteTheme) {
      deleteBtn.disabled = true;
      deleteBtn.title = isReadOnlyTheme
        ? 'System and global themes cannot be deleted directly.'
        : 'You do not have permission to delete themes.';
    } else {
      deleteBtn.disabled = false;
      deleteBtn.title = 'Delete this custom theme permanently';
    }

    const disableThemeEditingFields = isReadOnlyTheme || !canEditTheme;

    // Disable or enable all color inputs.
    for (const inputs of Object.values(this.colorInputs)) {
      inputs.colorInput.disabled = disableThemeEditingFields;
      inputs.textInput.disabled = disableThemeEditingFields;
    }

    // Disable or enable background selector and upload.
    this.backgroundSelect.disabled = disableThemeEditingFields;
    document.getElementById('upload-bg-btn').disabled = disableThemeEditingFields;
  }
  
  applyThemePreview() {
    // Apply current color values to CSS variables for live preview
    const root = document.documentElement;
    
    for (const [variableName, inputs] of Object.entries(this.colorInputs)) {
      root.style.setProperty(`--${variableName}`, inputs.colorInput.value);
    }
    
    // Apply background image
    const bgValue = this.backgroundSelect.value;
    if (bgValue && bgValue !== 'none') {
      root.style.setProperty('--background-image', `url('/images/backgrounds/${bgValue}')`);
    } else {
      root.style.setProperty('--background-image', 'none');
    }
  }
  
  async applyTheme() {
    if (!this.currentTheme || !this.currentThemeData) {
      this.showStatus('No theme selected', 'error');
      return;
    }
    
    // System themes can't have changes (inputs are disabled), so apply directly
    if (this.currentThemeData.system_theme || this.currentThemeData.global_theme) {
      await this.doApplyTheme();
      return;
    }
    
    // For user themes, check if there are unsaved changes
    if (this.hasUnsavedChanges()) {
      this.showUnsavedChangesModal();
      return;
    }
    
    // No unsaved changes, apply the theme from database
    await this.doApplyTheme();
  }
  
  hasUnsavedChanges() {
    // Check if any color has changed
    for (const [key, value] of Object.entries(this.currentThemeData.settings)) {
      if (this.colorInputs[key]) {
        const currentValue = this.colorInputs[key].colorInput.value.toUpperCase();
        const savedValue = value.toUpperCase();
        if (currentValue !== savedValue) {
          return true;
        }
      }
    }
    
    // Check if background image has changed
    const currentBg = this.backgroundSelect.value === 'none' ? null : this.backgroundSelect.value;
    const savedBg = this.currentThemeData.background_image || null;
    if (currentBg !== savedBg) {
      return true;
    }
    
    return false;
  }
  
  showUnsavedChangesModal() {
    const modal = document.getElementById('unsaved-changes-modal');
    modal.style.display = 'flex';
    
    // Set up event listeners (remove old ones first)
    const closeBtn = document.getElementById('unsaved-changes-close');
    const discardBtn = document.getElementById('unsaved-discard');
    const saveBtn = document.getElementById('unsaved-save');
    const cancelBtn = document.getElementById('unsaved-cancel');
    
    const close = () => { modal.style.display = 'none'; };
    const discard = async () => {
      modal.style.display = 'none';
      await this.doApplyTheme();
    };
    const save = async () => {
      modal.style.display = 'none';
      await this.saveTheme();
      if (!this.lastSaveError) {
        await this.doApplyTheme();
      }
    };

    setupModalEscapeClose(modal, close);
    
    closeBtn.onclick = close;
    discardBtn.onclick = discard;
    saveBtn.onclick = save;
    cancelBtn.onclick = close;
  }
  
  async doApplyTheme() {
    // Note: We don't check dbConnected here because REST API calls work independently
    // of the periodic database status checks. The dbConnected flag is primarily for
    // blocking card creation, not for theme changes.
    
    const applyBtn = this.applyBtn;
    const originalText = applyBtn.textContent;
    
    // Add loading state with delay
    const loadingTimeout = setTimeout(() => {
      applyBtn.textContent = 'Applying...';
      applyBtn.disabled = true;
    }, 500);
    
    const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
    
    try {
      // Save theme selection to settings (apply to session)
      const response = await fetch('/api/settings/theme', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme_id: this.currentTheme }),
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const result = await this.parseResponse(response);
      
      if (!response.ok || (result.success === false)) {
        throw new Error(result.message || result.error || 'Failed to apply theme');
      }
      
      // Fetch and apply theme from database
      await this.loadAndApplyTheme();
      
      // Reload the theme data into currentThemeData
      const {
        controller: themeController,
        timeoutId: themeTimeoutId,
        timeoutMs: themeTimeoutMs
      } = this.createTimeoutController();
      
      try {
        const themeResponse = await fetch('/api/settings/theme', {
          signal: themeController.signal
        });
        
        clearTimeout(themeTimeoutId);
        
        if (themeResponse.ok) {
          const theme = await this.parseResponse(themeResponse);
          
          if (theme && theme.settings) {
            this.currentThemeData = theme;
            
            // Reload theme colors into inputs to discard any unsaved changes
            this.loadThemeColors(theme.settings);
            this.updateBackgroundDisplay(theme.background_image);
          }
        }
      } catch (err) {
        clearTimeout(themeTimeoutId);
        if (err.name === 'AbortError') {
          console.error(`Error reloading theme data: timed out after ${Math.round(themeTimeoutMs / 1000)} seconds`);
        } else {
          console.error('Error reloading theme data:', err);
        }
      }
      
      clearTimeout(loadingTimeout);
      applyBtn.textContent = originalText;
      applyBtn.disabled = false;
      
      this.showSuccessToast('Theme applied to session successfully');
    } catch (error) {
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      
      applyBtn.textContent = originalText;
      applyBtn.disabled = false;
      
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        console.error(`Apply theme request timed out after ${timeoutSeconds} seconds`);
        this.showErrorToast(`Request timed out after ${timeoutSeconds}s. Check your connection.`);
      } else {
        console.error('Error applying theme:', error);
        this.showErrorToast('Error applying theme: ' + error.message);
      }
    }
  }
  
  async loadAndApplyTheme() {
    const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
    
    try {
      // Fetch the current theme from settings
      const response = await fetch('/api/settings/theme', {
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const theme = await this.parseResponse(response);
      
      if (!response.ok || (theme.success === false)) {
        throw new Error(theme.message || theme.error || 'Failed to load theme');
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
      clearTimeout(timeoutId);
      
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        console.error(`Load theme request timed out after ${timeoutSeconds} seconds`);
        throw new Error(`Request timed out after ${timeoutSeconds}s. Check your connection.`);
      }
      
      console.error('Error loading and applying theme:', error);
      throw error;
    }
  }
  
  async saveTheme() {
    if (!this.currentTheme || !this.currentThemeData) {
      this.showErrorToast('No theme selected');
      this.lastSaveError = true;
      return;
    }
    
    if (this.currentThemeData.system_theme || this.currentThemeData.global_theme) {
      this.showErrorToast('Cannot save system or global themes');
      this.lastSaveError = true;
      return;
    }

    if (!this.permissions.canEditTheme) {
      this.showErrorToast('You do not have permission to edit themes');
      this.lastSaveError = true;
      return;
    }
    
    // Note: We don't check dbConnected here because REST API calls work independently
    // of the periodic database status checks. The dbConnected flag is primarily for
    // blocking card creation, not for theme changes. The API call itself will fail
    // gracefully if there's an actual connectivity issue.
    
    const saveBtn = this.saveBtn;
    const originalText = saveBtn.textContent;
    
    // Add loading state with delay
    const loadingTimeout = setTimeout(() => {
      saveBtn.textContent = 'Saving...';
      saveBtn.disabled = true;
    }, 500);
    
    const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
    
    try {
      this.lastSaveError = false;
      
      // Collect current color values
      const settings = {};
      for (const [variableName, inputs] of Object.entries(this.colorInputs)) {
        settings[variableName] = inputs.colorInput.value;
      }
      
      // Get background image
      const bgValue = this.backgroundSelect.value;
      const background_image = bgValue === 'none' ? null : bgValue;
      
      // Save to API
      const response = await fetch(`/api/themes/${this.currentTheme}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          settings,
          background_image
        }),
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const updatedTheme = await this.parseResponse(response);
      
      if (!response.ok || (updatedTheme.success === false)) {
        throw new Error(updatedTheme.message || updatedTheme.error || 'Failed to save theme');
      }
      this.themes[this.currentTheme] = updatedTheme;
      this.currentThemeData = updatedTheme;
      
      clearTimeout(loadingTimeout);
      saveBtn.textContent = originalText;
      saveBtn.disabled = false;
      
      this.showSuccessToast('Theme saved successfully');
      
      // If this is the currently active theme, apply the changes to the session
      await this.applyIfCurrentTheme();
    } catch (error) {
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      
      saveBtn.textContent = originalText;
      saveBtn.disabled = false;
      
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        console.error(`Save theme request timed out after ${timeoutSeconds} seconds`);
        this.showErrorToast(`Request timed out after ${timeoutSeconds}s. Check your connection.`);
      } else {
        console.error('Error saving theme:', error);
        this.showErrorToast('Error saving theme: ' + error.message);
      }
      this.lastSaveError = true;
    }
  }
  
  async applyIfCurrentTheme() {
    let requestTimeoutMs = 5000;
    try {
      // Fetch the current active theme
      const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
      requestTimeoutMs = timeoutMs;
      
      const response = await fetch('/api/settings/theme', {
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const activeTheme = await this.parseResponse(response);
      
      if (response.ok && activeTheme.id === this.currentTheme) {
        // The saved theme is the currently active theme, apply the changes
        await this.loadAndApplyTheme();
      }
    } catch (error) {
      // Silent fail - this is a bonus feature, don't interrupt the save flow
      if (error.name === 'AbortError') {
        console.log(`Could not check/apply current theme: timed out after ${Math.round(requestTimeoutMs / 1000)} seconds`);
      } else {
        console.log('Could not check/apply current theme:', error);
      }
    }
  }
  
  showCopyModal() {
    if (!this.permissions.canCreateTheme) {
      this.showErrorToast('You do not have permission to create themes');
      return;
    }

    // Note: We don't check dbConnected here because REST API calls work independently
    // of the periodic database status checks. The dbConnected flag is primarily for
    // blocking card creation, not for theme changes. The API call itself will fail
    // gracefully if there's an actual connectivity issue.
    
    const modal = document.getElementById('copy-theme-modal');
    const nameInput = document.getElementById('copy-theme-name');
    const errorDiv = document.getElementById('copy-theme-error');
    
    nameInput.value = this.currentThemeData ? `${this.currentThemeData.name} Copy` : '';
    errorDiv.style.display = 'none';
    modal.style.display = 'flex';
    setupModalEscapeClose(modal, () => this.hideCopyModal());
    nameInput.focus();
  }
  
  hideCopyModal() {
    document.getElementById('copy-theme-modal').style.display = 'none';
  }
  
  async confirmCopyTheme() {
    const nameInput = document.getElementById('copy-theme-name');
    const errorDiv = document.getElementById('copy-theme-error');
    const confirmBtn = document.getElementById('copy-theme-confirm');
    const newName = nameInput.value.trim();
    
    if (!newName) {
      errorDiv.textContent = 'Theme name is required';
      errorDiv.style.display = 'block';
      return;
    }
    
    const originalText = confirmBtn.textContent;
    
    // Add loading state with delay
    const loadingTimeout = setTimeout(() => {
      confirmBtn.textContent = 'Copying...';
      confirmBtn.disabled = true;
    }, 500);
    
    const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
    
    try {
      const response = await fetch('/api/themes/copy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_theme_id: this.currentTheme,
          new_name: newName
        }),
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const newTheme = await this.parseResponse(response);
      
      if (!response.ok || (newTheme.success === false)) {
        throw new Error(newTheme.message || newTheme.error || 'Failed to copy theme');
      }
      
      // Add to themes list
      this.themes[newTheme.id] = newTheme;
      
      // Add to User Themes optgroup (new themes are always user themes)
      this.addThemeToUserGroup(newTheme.id, newTheme.name);
      
      // Select the new theme
      this.themeSelect.value = newTheme.id;
      await this.onThemeChange();
      
      clearTimeout(loadingTimeout);
      confirmBtn.textContent = originalText;
      confirmBtn.disabled = false;
      
      this.hideCopyModal();
      this.showSuccessToast('Theme copied successfully');
    } catch (error) {
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      
      confirmBtn.textContent = originalText;
      confirmBtn.disabled = false;
      
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        console.error(`Copy theme request timed out after ${timeoutSeconds} seconds`);
        errorDiv.textContent = `Request timed out after ${timeoutSeconds}s. Check your connection.`;
      } else {
        console.error('Error copying theme:', error);
        errorDiv.textContent = error.message;
      }
      errorDiv.style.display = 'block';
    }
  }
  
  showRenameModal() {
    if (!this.currentThemeData) {
      this.showErrorToast('No theme selected');
      return;
    }
    
    if (this.currentThemeData.system_theme || this.currentThemeData.global_theme) {
      this.showErrorToast('Cannot rename system or global themes');
      return;
    }

    if (!this.permissions.canRenameTheme) {
      this.showErrorToast('You do not have permission to rename themes');
      return;
    }
    
    // Note: We don't check dbConnected here because REST API calls work independently
    // of the periodic database status checks. The dbConnected flag is primarily for
    // blocking card creation, not for theme changes. The API call itself will fail
    // gracefully if there's an actual connectivity issue.
    
    const modal = document.getElementById('rename-theme-modal');
    const nameInput = document.getElementById('rename-theme-name');
    const errorDiv = document.getElementById('rename-theme-error');
    
    nameInput.value = this.currentThemeData.name;
    errorDiv.style.display = 'none';
    modal.style.display = 'flex';
    setupModalEscapeClose(modal, () => this.hideRenameModal());
    nameInput.focus();
    nameInput.select();
  }
  
  hideRenameModal() {
    document.getElementById('rename-theme-modal').style.display = 'none';
  }
  
  async confirmRenameTheme() {
    const nameInput = document.getElementById('rename-theme-name');
    const errorDiv = document.getElementById('rename-theme-error');
    const confirmBtn = document.getElementById('rename-theme-confirm');
    const newName = nameInput.value.trim();
    
    if (!newName) {
      errorDiv.textContent = 'Theme name is required';
      errorDiv.style.display = 'block';
      return;
    }
    
    if (newName === this.currentThemeData.name) {
      this.hideRenameModal();
      return;
    }

    if (!this.permissions.canRenameTheme) {
      errorDiv.textContent = 'You do not have permission to rename themes';
      errorDiv.style.display = 'block';
      return;
    }
    
    const originalText = confirmBtn.textContent;
    
    // Add loading state with delay
    const loadingTimeout = setTimeout(() => {
      confirmBtn.textContent = 'Renaming...';
      confirmBtn.disabled = true;
    }, 500);
    
    const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
    
    try {
      const response = await fetch(`/api/themes/${this.currentTheme}/rename`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const updatedTheme = await this.parseResponse(response);
      
      if (!response.ok || (updatedTheme.success === false)) {
        throw new Error(updatedTheme.message || updatedTheme.error || 'Failed to rename theme');
      }
      
      // Update themes list
      this.themes[this.currentTheme] = updatedTheme;
      this.currentThemeData = updatedTheme;
      
      // Update select option
      const option = this.themeSelect.querySelector(`option[value="${this.currentTheme}"]`);
      if (option) {
        option.textContent = updatedTheme.name;
      }
      
      clearTimeout(loadingTimeout);
      confirmBtn.textContent = originalText;
      confirmBtn.disabled = false;
      
      this.hideRenameModal();
      this.showSuccessToast('Theme renamed successfully');
    } catch (error) {
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      
      confirmBtn.textContent = originalText;
      confirmBtn.disabled = false;
      
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        console.error(`Rename theme request timed out after ${timeoutSeconds} seconds`);
        errorDiv.textContent = `Request timed out after ${timeoutSeconds}s. Check your connection.`;
      } else {
        console.error('Error renaming theme:', error);
        errorDiv.textContent = error.message;
      }
      errorDiv.style.display = 'block';
    }
  }
  
  showDeleteModal() {
    if (!this.currentTheme || !this.currentThemeData) {
      this.showErrorToast('No theme selected');
      return;
    }
    
    if (this.currentThemeData.system_theme || this.currentThemeData.global_theme) {
      this.showErrorToast('Cannot delete system or global themes');
      return;
    }

    if (!this.permissions.canDeleteTheme) {
      this.showErrorToast('You do not have permission to delete themes');
      return;
    }
    
    const modal = document.getElementById('delete-theme-modal');
    const nameSpan = document.getElementById('delete-theme-name');
    
    nameSpan.textContent = this.currentThemeData.name;
    modal.style.display = 'flex';
    setupModalEscapeClose(modal, () => this.hideDeleteModal());
  }
  
  hideDeleteModal() {
    document.getElementById('delete-theme-modal').style.display = 'none';
  }
  
  async confirmDeleteTheme() {
    if (!this.currentTheme || !this.currentThemeData) {
      this.showErrorToast('No theme selected');
      this.hideDeleteModal();
      return;
    }
    
    const confirmBtn = document.getElementById('delete-theme-confirm');
    const originalText = confirmBtn.textContent;
    
    // Add loading state with delay
    const loadingTimeout = setTimeout(() => {
      confirmBtn.textContent = 'Deleting...';
      confirmBtn.disabled = true;
    }, 500);
    
    const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
    
    try {
      const response = await fetch(`/api/themes/${this.currentTheme}`, {
        method: 'DELETE',
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const result = await this.parseResponse(response);
      
      if (!response.ok || (result.success === false)) {
        throw new Error(result.message || result.error || 'Failed to delete theme');
      }
      
      clearTimeout(loadingTimeout);
      confirmBtn.textContent = originalText;
      confirmBtn.disabled = false;
      
      this.hideDeleteModal();
      this.showSuccessToast('Theme deleted successfully');
      
      // Reload themes list and select the first available theme
      await this.loadThemes();
      if (this.themeSelect.options.length > 0) {
        this.themeSelect.value = this.themeSelect.options[0].value;
        await this.onThemeChange();
      }
    } catch (error) {
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      
      confirmBtn.textContent = originalText;
      confirmBtn.disabled = false;
      
      this.hideDeleteModal();
      
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        console.error(`Delete theme request timed out after ${timeoutSeconds} seconds`);
        this.showErrorToast(`Request timed out after ${timeoutSeconds}s. Check your connection.`);
      } else {
        console.error('Error deleting theme:', error);
        this.showErrorToast('Error deleting theme: ' + error.message);
      }
    }
  }
  
  showImportWarning(message) {
    const modal = document.getElementById('import-warning-modal');
    const messageDiv = document.getElementById('import-warning-message');
    const closeBtn = document.getElementById('import-warning-close');
    const okBtn = document.getElementById('import-warning-ok');
    const header = modal.querySelector('.modal-header');
    
    messageDiv.textContent = message;
    header.classList.add('error');
    modal.style.display = 'flex';
    
    const close = () => {
      modal.style.display = 'none';
      header.classList.remove('error');
    };
    setupModalEscapeClose(modal, close);
    closeBtn.onclick = close;
    okBtn.onclick = close;
  }
  
  importTheme() {
    document.getElementById('import-theme-input').click();
  }
  
  async handleThemeImport(event) {
    const file = event.target.files[0];
    if (!file) return;
    let timeoutId = null;
    let requestTimeoutMs = 5000;
    
    try {
      const text = await file.text();
      const themeData = JSON.parse(text);
      
      // Validate theme data
      if (!themeData.name || !themeData.settings) {
        throw new Error('Invalid theme file format');
      }
      
      // Note: We don't check dbConnected here because REST API calls work independently
      // of the periodic database status checks. The dbConnected flag is primarily for
      // blocking card creation, not for theme changes. The API call itself will fail
      // gracefully if there's an actual connectivity issue.
      
      // Import via API
      const { controller, timeoutId: importTimeoutId, timeoutMs } = this.createTimeoutController();
      timeoutId = importTimeoutId;
      requestTimeoutMs = timeoutMs;
      
      const response = await fetch('/api/themes/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(themeData),
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const newTheme = await this.parseResponse(response);
      
      if (!response.ok || (newTheme.success === false)) {
        const errorMessage = newTheme.message || newTheme.error || 'Failed to import theme';
        console.log('Import error:', errorMessage);
        this.showImportWarning(errorMessage);
        return;
      }
      
      // Add to themes list
      this.themes[newTheme.id] = newTheme;
      
      // Add to User Themes optgroup (imported themes are always user themes)
      this.addThemeToUserGroup(newTheme.id, newTheme.name);
      
      // Select the new theme
      this.themeSelect.value = newTheme.id;
      await this.onThemeChange();
      
      this.showSuccessToast('Theme imported successfully');
    } catch (error) {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(requestTimeoutMs / 1000);
        console.error(`Import theme request timed out after ${timeoutSeconds} seconds`);
        this.showImportWarning(`Request timed out after ${timeoutSeconds}s. Check your connection.`);
      } else {
        console.error('Error importing theme:', error);
        this.showImportWarning(error.message || 'Failed to import theme');
      }
    }
    
    // Reset file input
    event.target.value = '';
  }
  
  async exportTheme() {
    if (!this.currentTheme) {
      this.showErrorToast('No theme selected');
      return;
    }
    
    const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
    
    try {
      const response = await fetch(`/api/themes/${this.currentTheme}/export`, {
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const themeData = await this.parseResponse(response);
      
      if (!response.ok || (themeData.success === false)) {
        throw new Error(themeData.message || themeData.error || 'Failed to export theme');
      }
      
      // Create download link with sanitized filename to prevent XSS
      const blob = new Blob([JSON.stringify(themeData, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const sanitizedName = this.escapeHtml(themeData.name || 'theme').replace(/\s+/g, '_');
      a.download = `${sanitizedName}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      
      this.showSuccessToast('Theme exported successfully');
    } catch (error) {
      clearTimeout(timeoutId);
      
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        console.error(`Export theme request timed out after ${timeoutSeconds} seconds`);
        this.showErrorToast(`Request timed out after ${timeoutSeconds}s. Check your connection.`);
      } else {
        console.error('Error exporting theme:', error);
        this.showErrorToast('Error exporting theme: ' + error.message);
      }
    }
  }
  
  uploadBackground() {
    document.getElementById('bg-image-input').click();
  }
  
  async handleBackgroundUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    // Note: We don't check dbConnected here because REST API calls work independently
    // of the periodic database status checks. The dbConnected flag is primarily for
    // blocking card creation, not for theme changes. The API call itself will fail
    // gracefully if there's an actual connectivity issue.
    
    const uploadBtn = document.getElementById('upload-bg-btn');
    const originalText = uploadBtn.textContent;
    
    // Add loading state with delay
    const loadingTimeout = setTimeout(() => {
      uploadBtn.textContent = 'Uploading...';
      uploadBtn.disabled = true;
    }, 500);
    
    const { controller, timeoutId, timeoutMs } = this.createTimeoutController();
    
    try {
      const formData = new FormData();
      formData.append('image', file);
      
      const response = await fetch('/api/themes/upload-image', {
        method: 'POST',
        body: formData,
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      const result = await this.parseResponse(response);
      
      if (!response.ok || (result.success === false)) {
        throw new Error(result.message || result.error || 'Failed to upload image');
      }
      
      // Reload background images list
      await this.loadBackgroundImages();
      
      // Update the selector to the new image
      this.backgroundSelect.value = result.filename;
      
      // Update current theme data
      if (this.currentThemeData) {
        this.currentThemeData.background_image = result.filename;
      }
      
      // Apply the background change immediately
      this.applyThemePreview();
      
      clearTimeout(loadingTimeout);
      uploadBtn.textContent = originalText;
      uploadBtn.disabled = false;
      
      this.showSuccessToast('Background image uploaded successfully');
    } catch (error) {
      clearTimeout(timeoutId);
      clearTimeout(loadingTimeout);
      
      uploadBtn.textContent = originalText;
      uploadBtn.disabled = false;
      
      let errorMessage;
      if (error.name === 'AbortError') {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        console.error(`Upload background request timed out after ${timeoutSeconds} seconds`);
        errorMessage = `Request timed out after ${timeoutSeconds}s. Check your connection.`;
      } else {
        console.error('Error uploading background:', error);
        errorMessage = error.message;
      }
      
      // Show error modal instead of toast
      this.showImportWarning(errorMessage);
    }
    
    // Reset file input
    event.target.value = '';
  }
  
  async downloadBackground() {
    const bgValue = this.backgroundSelect.value;
    
    if (!bgValue || bgValue === 'none') {
      this.showErrorToast('No background image selected');
      return;
    }
    
    try {
      // Sanitize background value to prevent path traversal and XSS
      const sanitizedBgValue = bgValue.replace(/[\\/\.\s]/g, '_');
      const url = `/images/backgrounds/${sanitizedBgValue}`;
      
      // Create download link
      const a = document.createElement('a');
      a.href = url;
      a.download = sanitizedBgValue;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      
      this.showSuccessToast('Background image downloaded');
    } catch (error) {
      console.error('Error downloading background:', error);
      this.showErrorToast('Error downloading background: ' + error.message);
    }
  }
  
  showStatus(message, type) {
    this.statusDiv.textContent = message;
    this.statusDiv.className = `settings-status ${type}`;
    this.statusDiv.style.display = 'block';
    
    setTimeout(() => {
      this.statusDiv.style.display = 'none';
    }, 5000);
  }
}

/**
 * Initialize WebSocket connection for the theme builder page.
 * 
 * Sets up Socket.IO client for theme synchronization across multiple clients
 * editing themes simultaneously.
 * 
 * Returns:
 *   Socket instance if Socket.IO is available, undefined otherwise
 */
function initializeWebSocketForThemeBuilder() {
  if (typeof io !== 'undefined') {
    const socket = io({
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: 5,
      transports: ['websocket', 'polling']
    });

    socket.on('connect', () => {
      socket.emit('join_theme');
    });

    socket.on('disconnect', () => {
      // Silently handle disconnection
    });

    // Listen for theme changes from other clients
    socket.on('theme_changed', (data) => {
      // Refresh themes list if we're on the theme builder
      if (window.AFT?.themeBuilder && typeof window.AFT.themeBuilder.loadThemes === 'function') {
        window.AFT.themeBuilder.loadThemes(true); // Preserve selection when reloading
      }
    });

    socket.on('theme_updated', (data) => {
      if (window.AFT?.themeBuilder && typeof window.AFT.themeBuilder.loadThemes === 'function') {
        window.AFT.themeBuilder.loadThemes(true); // Preserve selection when reloading
      }
    });

    return socket;
  }
  // Socket.IO unavailable: return undefined so callers can check for a truthy socket before use
  return undefined;
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  // Create namespace for theme builder to avoid global namespace pollution
  if (!window.AFT) {
    window.AFT = {};
  }
  window.AFT.themeBuilderSocket = initializeWebSocketForThemeBuilder();
  
  window.AFT.themeBuilder = new ThemeBuilder();
  window.AFT.themeBuilder.init();
  
  // Keep legacy global references for backward compatibility
  window.themeBuilderSocket = window.AFT.themeBuilderSocket;
  window.themeBuilder = window.AFT.themeBuilder;
});
