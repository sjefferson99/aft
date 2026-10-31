// Personal preferences, shown on the profile page
const DEFAULT_CARD_ACTIONS = { desktop: ['done', 'archive', 'delete'], mobile: ['done', 'move'] };
const MAX_CARD_ACTIONS_PER_SCREEN = 3;

class Preferences {
  constructor() {
    this.defaultBoardSelect = document.getElementById('default-board');
    this.timeFormatRadios = document.querySelectorAll('input[name="time-format"]');
    this.timezoneSelect = document.getElementById('timezone-select');
    this.touchscreenModeCheckbox = document.getElementById('touchscreen-mode');
    this.cardActionCheckboxes = Array.from(document.querySelectorAll('[data-card-action]'));
    this.themeSelect = document.getElementById('theme-select');
    this.workingStyleSelect = document.getElementById('working-style');
    this.statusElement = document.getElementById('settings-status');
    this.saveTimeout = null;
  }

  async init() {
    // Wait until header.js has loaded user context.
    if (!window.userDataReady) {
      setTimeout(() => this.init(), 100);
      return;
    }

    await this.loadBoards();
    await this.loadSettings();
    await this.loadTimezoneOptions();
    await this.loadTimezoneSetting();
    await this.loadThemes();
    await this.loadWorkingStyle();
    this.attachEventListeners();

    // Sections above can appear after the browser has followed the link
    if (window.location.hash === '#preferences') {
      document.getElementById('preferences').scrollIntoView();
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

      if (this.touchscreenModeCheckbox) {
        const touchscreenResponse = await fetch('/api/settings/touchscreen_mode');
        if (touchscreenResponse.ok) {
          const data = await touchscreenResponse.json();
          this.touchscreenModeCheckbox.checked = data.success && data.value === true;
        } else if (touchscreenResponse.status !== 404) {
          console.error('Error loading touchscreen mode:', touchscreenResponse.statusText);
        }
      }

      if (this.cardActionCheckboxes.length > 0) {
        const cardActionsResponse = await fetch('/api/settings/card_actions');
        if (cardActionsResponse.ok) {
          const data = await cardActionsResponse.json();
          this.showCardActions((data.success && data.value) || DEFAULT_CARD_ACTIONS);
        } else if (cardActionsResponse.status === 404) {
          this.showCardActions(DEFAULT_CARD_ACTIONS);
        } else {
          console.error('Error loading card actions:', cardActionsResponse.statusText);
        }
      }
    } catch (err) {
      console.error('Error loading settings:', err);
    }
  }

  async loadThemes() {
    try {
      const response = await fetch('/api/themes');
      if (!response.ok) throw new Error('Failed to load themes');

      populateThemeOptions(this.themeSelect, await response.json());

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

  showCardActions(cardActions) {
    this.cardActionCheckboxes.forEach((checkbox) => {
      checkbox.checked = cardActions[checkbox.dataset.cardActionScreen].includes(checkbox.dataset.cardAction);
    });
    this.limitCardActions();
  }

  // Unchecked boxes are disabled once a screen has its maximum.
  limitCardActions() {
    const chosen = this.getChosenCardActions();
    this.cardActionCheckboxes.forEach((checkbox) => {
      const atLimit = chosen[checkbox.dataset.cardActionScreen].length >= MAX_CARD_ACTIONS_PER_SCREEN;
      checkbox.disabled = atLimit && !checkbox.checked;
    });
  }

  getChosenCardActions() {
    const chosen = { desktop: [], mobile: [] };
    this.cardActionCheckboxes.forEach((checkbox) => {
      if (checkbox.checked) {
        chosen[checkbox.dataset.cardActionScreen].push(checkbox.dataset.cardAction);
      }
    });
    return chosen;
  }

  async saveCardActions(changedCheckbox) {
    const cardActions = this.getChosenCardActions();
    this.limitCardActions();

    try {
      this.showStatus('Saving...', 'info');

      const response = await fetch('/api/settings/card_actions', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ value: cardActions })
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.message || `HTTP error! status: ${response.status}`);
      }

      applyCardActions(cardActions);
      this.showStatus('Saved', 'success');

      setTimeout(() => {
        this.statusElement.textContent = '';
        this.statusElement.className = 'settings-status';
      }, 2000);
    } catch (err) {
      changedCheckbox.checked = !changedCheckbox.checked;
      this.limitCardActions();
      this.showStatus('Error: ' + err.message, 'error');
    }
  }

  async saveTouchscreenMode() {
    const enabled = this.touchscreenModeCheckbox.checked;

    try {
      this.showStatus('Saving...', 'info');

      const response = await fetch('/api/settings/touchscreen_mode', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ value: enabled })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || `HTTP error! status: ${response.status}`);
      }

      if (data.success) {
        applyTouchscreenMode(enabled);
        this.showStatus('Saved', 'success');

        setTimeout(() => {
          this.statusElement.textContent = '';
          this.statusElement.className = 'settings-status';
        }, 2000);
      } else {
        this.touchscreenModeCheckbox.checked = !enabled;
        this.showStatus('Error: ' + data.message, 'error');
      }
    } catch (err) {
      this.touchscreenModeCheckbox.checked = !enabled;
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

    if (this.touchscreenModeCheckbox) {
      this.touchscreenModeCheckbox.addEventListener('change', () => this.saveTouchscreenMode());
    }

    this.cardActionCheckboxes.forEach((checkbox) => {
      checkbox.addEventListener('change', () => this.saveCardActions(checkbox));
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
  }

  showStatus(message, type = 'info') {
    this.statusElement.textContent = message;
    this.statusElement.className = `settings-status ${type}`;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const preferences = new Preferences();
  preferences.init();
});
