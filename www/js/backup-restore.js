// Backup & Restore page functionality
class BackupRestore {
  constructor() {
    this.statusElement = document.getElementById('settings-status');
    
    // Manual backup/restore elements
    this.manualBackupBtn = document.getElementById('manual-backup-btn');
    this.backupBtn = document.getElementById('backup-btn');
    this.restoreBtn = document.getElementById('restore-btn');
    this.restoreFileInput = document.getElementById('restore-file-input');
    this.backupStatus = document.getElementById('backup-status');
    
    // Automatic backup settings elements
    this.backupForm = document.getElementById('backupConfigForm');
    this.backupEnabled = document.getElementById('backupEnabled');
    this.frequencyValue = document.getElementById('frequencyValue');
    this.frequencyUnit = document.getElementById('frequencyUnit');
    this.startTime = document.getElementById('startTime');
    this.retentionCount = document.getElementById('retentionCount');
    this.minimumFreeSpace = document.getElementById('minimumFreeSpace');
    this.schedulerStatus = document.getElementById('schedulerStatus');
    this.currentFrequency = document.getElementById('currentFrequency');
    this.currentRetention = document.getElementById('currentRetention');
    this.latestBackup = document.getElementById('latestBackup');
    this.backupWindowStatus = document.getElementById('backupWindowStatus');
    this.saveBackupButton = document.getElementById('saveBackupButton');
    this.resetBackupButton = document.getElementById('resetBackupButton');
    this.backupSettingsStatus = document.getElementById('backup-settings-status');
    
    // Available backups elements
    this.backupsLoading = document.getElementById('backupsLoading');
    this.backupsEmpty = document.getElementById('backupsEmpty');
    this.backupsList = document.getElementById('backupsList');
    this.restoreStatus = document.getElementById('restoreStatus');
    this.restoreProgress = new RestoreProgressDisplay();
    this.deleteSelectedBtn = document.getElementById('deleteSelectedBtn');
    
    // Track selected backups
    this.selectedBackups = new Set();
  }

  // Helper function to escape HTML and prevent XSS
  escapeHtml(unsafe) {
    const div = document.createElement('div');
    div.textContent = unsafe;
    return div.innerHTML;
  }

  // Helper function to safely update element text content
  safeSetText(element, text) {
    if (element) {
      element.textContent = text;
    }
  }

  // Helper function to safely update element class
  safeSetClass(element, className) {
    if (element) {
      element.className = className;
    }
  }

  // Helper function to safely update element HTML
  safeSetHTML(element, html) {
    if (element) {
      element.innerHTML = html;
    }
  }

  // Helper function to safely disable/enable element
  safeSetDisabled(element, disabled) {
    if (element) {
      element.disabled = disabled;
    }
  }

  async init() {
    // Wait for user data to be ready (loaded by header.js)
    if (!window.userDataReady) {
      setTimeout(() => this.init(), 100);
      return;
    }
    
    // Check permission before loading page content
    const hasAdminDatabase = typeof hasPermission === 'function' && hasPermission('admin.database');
    
    if (!hasAdminDatabase) {
      // User doesn't have permission - show access denied
      showAccessDenied('You need the "admin.database" permission to access this page.');
      return;
    }
    
    await this.loadBackupConfig();
    await this.loadBackupStatus();
    await this.loadAvailableBackups();
    this.attachEventListeners();
    this.setupSelectAllCheckbox();
  }

  setupSelectAllCheckbox() {
    const selectAllCheckbox = document.getElementById('selectAllBackups');
    if (selectAllCheckbox) {
      selectAllCheckbox.addEventListener('change', (e) => {
        this.toggleSelectAll(e.target.checked);
      });
    }
  }

  attachEventListeners() {
    // Manual backup to server button
    if (this.manualBackupBtn) {
      this.manualBackupBtn.addEventListener('click', () => {
        this.createManualBackup();
      });
    }

    // Download backup button
    if (this.backupBtn) {
      this.backupBtn.addEventListener('click', () => {
        this.downloadBackup();
      });
    }

    // Restore button opens file picker
    if (this.restoreBtn) {
      this.restoreBtn.addEventListener('click', () => {
        this.restoreFileInput.click();
      });
    }

    // File input change triggers restore
    if (this.restoreFileInput) {
      this.restoreFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
          this.restoreFromFile(e.target.files[0]);
        }
      });
    }

    // Delete selected backups button
    if (this.deleteSelectedBtn) {
      this.deleteSelectedBtn.addEventListener('click', () => {
        this.deleteSelectedBackups();
      });
    }

    // Automatic backup settings event listeners
    if (this.backupForm) {
      this.backupForm.addEventListener('submit', (e) => {
        e.preventDefault();
        this.saveBackupConfig();
      });
    }

    if (this.resetBackupButton) {
      this.resetBackupButton.addEventListener('click', () => {
        this.loadBackupConfig();
      });
    }

    // Backup enabled toggle
    if (this.backupEnabled) {
      this.backupEnabled.addEventListener('change', async (e) => {
        // Auto-save only the enabled state (like system-info toggle)
        await this.toggleBackupEnabled(e.target.checked);
      });
    }

    // Frequency unit change - disable frequency value input for daily
    if (this.frequencyUnit) {
      this.frequencyUnit.addEventListener('change', (e) => {
        if (this.frequencyValue) {
          if (e.target.value === 'daily') {
            this.frequencyValue.disabled = true;
            this.frequencyValue.value = 1;
            this.frequencyValue.style.opacity = '0.5';
            this.frequencyValue.style.cursor = 'not-allowed';
          } else {
            this.frequencyValue.disabled = false;
            this.frequencyValue.style.opacity = '1';
            this.frequencyValue.style.cursor = 'auto';
          }
        }
      });
      // Trigger change event on init to set initial state
      this.frequencyUnit.dispatchEvent(new Event('change'));
    }
  }

  async downloadBackup() {
    try {
      this.safeSetText(this.backupStatus, 'Creating backup...');
      this.safeSetClass(this.backupStatus, 'backup-status info');
      this.safeSetDisabled(this.backupBtn, true);

      const response = await fetch('/api/database/backup');
      
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.message || 'Failed to create backup');
      }

      // Get filename from Content-Disposition header or create default
      const contentDisposition = response.headers.get('Content-Disposition');
      let filename = 'aft_backup.sql';
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
        if (filenameMatch) {
          // Sanitize filename from header to prevent XSS
          filename = this.escapeHtml(filenameMatch[1]);
        }
      }

      // Download the file
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      this.safeSetText(this.backupStatus, 'Backup downloaded successfully!');
      this.safeSetClass(this.backupStatus, 'backup-status success');
      
      setTimeout(() => {
        this.safeSetText(this.backupStatus, '');
        this.safeSetClass(this.backupStatus, 'backup-status');
      }, 5000);

    } catch (error) {
      console.error('Error creating backup:', error);
      this.safeSetText(this.backupStatus, `Error: ${error.message}`);
      this.safeSetClass(this.backupStatus, 'backup-status error');
    } finally {
      this.safeSetDisabled(this.backupBtn, false);
    }
  }

  async createManualBackup() {
    try {
      this.safeSetText(this.backupStatus, 'Creating backup...');
      this.safeSetClass(this.backupStatus, 'backup-status info');
      this.safeSetDisabled(this.manualBackupBtn, true);

      const response = await fetch('/api/database/backup/manual', {
        method: 'POST'
      });
      
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.message || `HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      
      if (!data.success) {
        throw new Error(data.message || 'Failed to create backup');
      }

      this.safeSetText(this.backupStatus, data.message);
      this.safeSetClass(this.backupStatus, 'backup-status success');
      
      // Reload the available backups list
      await this.loadAvailableBackups();
      
      setTimeout(() => {
        this.safeSetText(this.backupStatus, '');
        this.safeSetClass(this.backupStatus, 'backup-status');
      }, 5000);

    } catch (error) {
      console.error('Error creating manual backup:', error);
      this.safeSetText(this.backupStatus, `Error: ${error.message}`);
      this.safeSetClass(this.backupStatus, 'backup-status error');
    } finally {
      this.safeSetDisabled(this.manualBackupBtn, false);
    }
  }

  async restoreFromFile(file) {
    // Show confirmation modal
    this.showManualRestoreConfirmModal(file);
  }

  showManualRestoreConfirmModal(file) {
    const modal = document.getElementById('restoreModal');
    const titleElement = document.getElementById('restoreModalTitle');
    const messageElement = document.getElementById('restoreModalMessage');
    const confirmBtn = document.getElementById('restoreModalConfirmBtn');
    const cancelBtn = document.getElementById('restoreModalCancelBtn');

    // Set confirmation content
    titleElement.textContent = 'Confirm Restore';
    titleElement.style.color = 'var(--warning-color, #f59e0b)';
    messageElement.innerHTML = `Are you sure you want to restore from <strong>"${this.escapeHtml(file.name)}"</strong>?<br><br>This will replace all current data with the backup. This action cannot be undone.`;
    
    confirmBtn.textContent = 'Restore';
    confirmBtn.style.display = 'inline-block';
    cancelBtn.style.display = 'inline-block';

    modal.classList.add('active');

    // Handle cancel
    const handleCancel = () => {
      modal.classList.remove('active');
      confirmBtn.removeEventListener('click', handleConfirm);
      cancelBtn.removeEventListener('click', handleCancel);
      this.restoreFileInput.value = '';
    };

    // Handle confirm
    const handleConfirm = async () => {
      // Remove event listeners
      confirmBtn.removeEventListener('click', handleConfirm);
      cancelBtn.removeEventListener('click', handleCancel);
      
      // Update modal to show progress
      titleElement.textContent = 'Restoring Database';
      titleElement.style.color = 'var(--primary-color)';
      messageElement.textContent = 'This may take several minutes for large databases. Please wait.';
      confirmBtn.style.display = 'none';
      cancelBtn.style.display = 'none';

      this.restoreBtn.disabled = true;

      try {
        const progressId = this.startRestoreProgress('Uploading the backup file');
        const formData = new FormData();
        formData.append('file', file);

        // Set up timeout for 25 minutes (slightly less than backend 30 min timeout)
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 25 * 60 * 1000);

        const response = await fetch('/api/database/restore', {
          method: 'POST',
          headers: { 'X-Restore-Progress-Id': progressId },
          body: formData,
          signal: controller.signal
        });

        clearTimeout(timeoutId);

        // Check if response is JSON
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          throw new Error('Server returned an invalid response. The operation may have timed out. Please check if the restore completed successfully by refreshing the page.');
        }

        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.message || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        if (data.success) {
          // Show success in modal
          this.showRestoreResultInModal('Restore Successful', data.message, true);
        } else {
          // Show error in modal
          this.showRestoreResultInModal('Restore Failed', data.message, false);
          this.restoreBtn.disabled = false;
        }

      } catch (error) {
        console.error('Error restoring database:', error);
        
        let errorMessage = error.message;
        if (error.name === 'AbortError') {
          errorMessage = 'The restore operation timed out after 25 minutes. For very large databases, this may still be processing. Please wait a few minutes and refresh the page to check if the restore completed.';
        } else if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
          errorMessage = 'Network connection lost during restore. The restore may still be processing on the server. Please wait a few minutes and refresh the page to check the status.';
        }
        
        // Show error in modal
        this.showRestoreResultInModal('Restore Failed', errorMessage, false);
        this.restoreBtn.disabled = false;
      } finally {
        this.restoreFileInput.value = '';
      }
    };

    confirmBtn.addEventListener('click', handleConfirm);
    setupModalEscapeClose(modal, handleCancel);
    cancelBtn.addEventListener('click', handleCancel);
  }

  async loadBackupConfig() {
    try {
      const response = await fetch('/api/settings/backup/config');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      if (data.success && data.config) {
        const config = data.config;
        if (this.backupEnabled) this.backupEnabled.checked = config.enabled || false;
        if (this.frequencyValue) this.frequencyValue.value = config.frequency_value ?? '';
        if (this.frequencyUnit) this.frequencyUnit.value = config.frequency_unit ?? '';
        if (this.startTime) this.startTime.value = config.start_time ?? '';
        if (this.retentionCount) this.retentionCount.value = config.retention_count ?? '';
        if (this.minimumFreeSpace) this.minimumFreeSpace.value = config.minimum_free_space_mb ?? '';
      }
    } catch (err) {
      console.error('Error loading backup config:', err);
      this.showStatus('Error loading backup settings: ' + err.message, 'error');
    }
  }

  async saveBackupConfig() {
    try {
      this.safeSetDisabled(this.saveBackupButton, true);
      this.safeSetText(this.backupSettingsStatus, 'Saving backup settings...');
      this.safeSetClass(this.backupSettingsStatus, 'backup-status info');

      const config = {
        enabled: this.backupEnabled ? this.backupEnabled.checked : false,
        frequency_value: this.frequencyValue ? parseInt(this.frequencyValue.value, 10) : 24,
        frequency_unit: this.frequencyUnit ? this.frequencyUnit.value : 'hours',
        start_time: this.startTime ? this.startTime.value : '02:00',
        retention_count: this.retentionCount ? parseInt(this.retentionCount.value, 10) : 7,
        minimum_free_space_mb: this.minimumFreeSpace ? parseInt(this.minimumFreeSpace.value, 10) : 100
      };

      const response = await fetch('/api/settings/backup/config', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(config)
      });

      if (!response.ok) {
        const data = await response.json();
        const errorMessage = data.message || `HTTP error! status: ${response.status}`;
        throw new Error(errorMessage);
      }

      const data = await response.json();

      if (data.success) {
        this.safeSetText(this.backupSettingsStatus, 'Backup settings saved successfully!');
        this.safeSetClass(this.backupSettingsStatus, 'backup-status success');
        
        // Reload status to show updated info
        await this.loadBackupStatus();

        // Clear status after 3 seconds
        setTimeout(() => {
          this.safeSetText(this.backupSettingsStatus, '');
          this.safeSetClass(this.backupSettingsStatus, 'backup-status');
        }, 3000);
      } else {
        this.safeSetText(this.backupSettingsStatus, 'Error: ' + data.message);
        this.safeSetClass(this.backupSettingsStatus, 'backup-status error');
      }
    } catch (err) {
      this.safeSetText(this.backupSettingsStatus, 'Error: ' + err.message);
      this.safeSetClass(this.backupSettingsStatus, 'backup-status error');
    } finally {
      this.safeSetDisabled(this.saveBackupButton, false);
    }
  }

  async loadBackupStatus() {
    try {
      const response = await fetch('/api/settings/backup/status');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      if (data.success && data.status) {
        const status = data.status;
        
        // Update status badge - use healthy/unhealthy instead of running/stopped
        if (status.running) {
          this.safeSetText(this.schedulerStatus, 'Healthy');
          this.safeSetClass(this.schedulerStatus, 'status-badge status-healthy');
        } else {
          this.safeSetText(this.schedulerStatus, 'Unhealthy');
          this.safeSetClass(this.schedulerStatus, 'status-badge status-unhealthy');
        }
        
        // Update frequency display
        this.safeSetText(this.currentFrequency, status.enabled 
          ? status.frequency 
          : 'Disabled');
        
        // Update retention display
        this.safeSetText(this.currentRetention, `${status.retention_count} backup${status.retention_count !== 1 ? 's' : ''}`);
        
        // Update latest backup info
        if (status.latest_backup_date) {
          const backupDate = new Date(status.latest_backup_date);
          const now = new Date();
          const diffMs = now - backupDate;
          const diffMins = Math.floor(diffMs / 60000);
          const diffHours = Math.floor(diffMs / 3600000);
          const diffDays = Math.floor(diffMs / 86400000);
          
          let timeAgo;
          if (diffMins < 60) {
            timeAgo = `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`;
          } else if (diffHours < 24) {
            timeAgo = `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
          } else {
            timeAgo = `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
          }
          
          if (this.latestBackup) {
            const tooltipText = formatTooltipDateTime(backupDate);
            this.latestBackup.setAttribute('data-tooltip', tooltipText);
            this.latestBackup.setAttribute('aria-label', `Latest backup on ${tooltipText}`);
            this.latestBackup.setAttribute('tabindex', '0');
            this.latestBackup.textContent = timeAgo;
          }
        } else {
          this.safeSetText(this.latestBackup, 'No backups found');
        }
        
        // Update backup window status
        if (status.enabled) {
          if (status.latest_backup_date && status.backup_within_window) {
            this.safeSetHTML(this.backupWindowStatus, '<span class="status-badge status-healthy">Current</span>');
          } else {
            // Overdue if enabled but either no backup exists or backup is outside window
            this.safeSetHTML(this.backupWindowStatus, '<span class="status-badge status-unhealthy">Overdue</span>');
          }
        } else {
          this.safeSetText(this.backupWindowStatus, 'Disabled');
        }
        
        // Display permission error if present
        const errorDiv = document.getElementById('backupPermissionError');
        if (errorDiv) {
          if (status.permission_error) {
            errorDiv.textContent = status.permission_error;
            errorDiv.style.display = 'block';
          } else {
            errorDiv.style.display = 'none';
          }
        }
      }
    } catch (err) {
      console.error('Error loading backup status:', err);
      this.safeSetText(this.schedulerStatus, 'Error');
      this.safeSetClass(this.schedulerStatus, 'status-badge');
    }
  }

  async loadAvailableBackups() {
    // Save current scroll position
    const scrollElement = this.backupsList.parentElement;
    const savedScrollTop = scrollElement ? scrollElement.scrollTop : 0;
    
    try {
      if (this.backupsLoading) this.backupsLoading.style.display = 'block';
      if (this.backupsEmpty) this.backupsEmpty.style.display = 'none';
      this.backupsList.style.display = 'none';
      
      const response = await fetch('/api/database/backups/list');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      if (data.success && data.backups) {
        this.backupsLoading.style.display = 'none';
        
        if (data.backups.length === 0) {
          this.backupsEmpty.style.display = 'block';
        } else {
          this.backupsList.style.display = 'flex';
          this.renderBackupsList(data.backups);
          
          // Restore scroll position after DOM update
          if (scrollElement && savedScrollTop > 0) {
            requestAnimationFrame(() => {
              scrollElement.scrollTop = savedScrollTop;
            });
          }
        }
      }
    } catch (err) {
      console.error('Error loading available backups:', err);
      this.backupsLoading.textContent = 'Error loading backups';
    }
  }

  renderBackupsList(backups) {
    this.backupsList.innerHTML = '';
    this.selectedBackups.clear();
    
    backups.forEach(backup => {
      const backupItem = document.createElement('div');
      backupItem.className = 'backup-item';
      backupItem.dataset.filename = backup.filename;
      
      // Add manual backup class for highlighting
      if (backup.is_manual) {
        backupItem.classList.add('backup-manual');
      }
      
      // Format date
      const date = new Date(backup.created);
      const datePart = date.toLocaleDateString('en-GB', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      });
      const timePart = formatTimeSync(date, true);
      const formattedDate = `${datePart}, ${timePart}`;
      
      // Format size
      const size = backup.size;
      let formattedSize;
      if (size < 1024) {
        formattedSize = `${size} B`;
      } else if (size < 1024 * 1024) {
        formattedSize = `${(size / 1024).toFixed(2)} KB`;
      } else {
        formattedSize = `${(size / (1024 * 1024)).toFixed(2)} MB`;
      }
      
      // Create filename with escaped content to prevent XSS
      const escapedFilename = this.escapeHtml(backup.filename);
      const manualBadge = backup.is_manual ? '<span class="backup-manual-badge">Manual</span>' : '';
      
      backupItem.innerHTML = `
        <div class="backup-checkbox">
          <input type="checkbox" class="backup-select-checkbox" data-filename="${escapedFilename}" aria-label="Select ${escapedFilename}">
        </div>
        <div class="backup-info">
          <div class="backup-filename">${escapedFilename} ${manualBadge}</div>
          <div class="backup-date">${formattedDate}</div>
        </div>
        <div class="backup-size">${formattedSize}</div>
        <div class="backup-actions">
          <button class="backup-restore-btn" data-filename="${escapedFilename}">
            Restore
          </button>
          <button class="backup-delete-btn" data-filename="${escapedFilename}">
            Delete
          </button>
        </div>
      `;
      
      // Add checkbox event listener
      const checkbox = backupItem.querySelector('.backup-select-checkbox');
      checkbox.addEventListener('change', (e) => {
        this.toggleBackupSelection(backup.filename, e.target.checked);
      });
      
      const restoreBtn = backupItem.querySelector('.backup-restore-btn');
      restoreBtn.addEventListener('click', () => {
        this.restoreFromAutoBackup(backup.filename);
      });
      
      const deleteBtn = backupItem.querySelector('.backup-delete-btn');
      deleteBtn.addEventListener('click', () => {
        this.deleteBackup(backup.filename);
      });
      
      this.backupsList.appendChild(backupItem);
    });
    
    this.updateDeleteSelectedButton();
    this.updateSelectAllCheckbox();
  }

  toggleBackupSelection(filename, isSelected) {
    if (isSelected) {
      this.selectedBackups.add(filename);
    } else {
      this.selectedBackups.delete(filename);
    }
    this.updateDeleteSelectedButton();
    this.updateSelectAllCheckbox();
  }

  toggleSelectAll(isSelected) {
    const checkboxes = this.backupsList.querySelectorAll('.backup-select-checkbox');
    checkboxes.forEach(checkbox => {
      checkbox.checked = isSelected;
      const filename = checkbox.dataset.filename;
      if (isSelected) {
        this.selectedBackups.add(filename);
      } else {
        this.selectedBackups.delete(filename);
      }
    });
    this.updateDeleteSelectedButton();
    this.updateSelectAllCheckbox();
  }

  updateSelectAllCheckbox() {
    const selectAllCheckbox = document.getElementById('selectAllBackups');
    if (!selectAllCheckbox) return;
    
    const checkboxes = this.backupsList.querySelectorAll('.backup-select-checkbox');
    const checkedCount = Array.from(checkboxes).filter(cb => cb.checked).length;
    
    selectAllCheckbox.checked = checkboxes.length > 0 && checkedCount === checkboxes.length;
    selectAllCheckbox.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
  }

  updateDeleteSelectedButton() {
    if (this.deleteSelectedBtn) {
      if (this.selectedBackups.size > 0) {
        this.deleteSelectedBtn.disabled = false;
        this.deleteSelectedBtn.textContent = `Delete Selected (${this.selectedBackups.size})`;
      } else {
        this.deleteSelectedBtn.disabled = true;
        this.deleteSelectedBtn.textContent = 'Delete Selected';
      }
    }
  }

  async deleteSelectedBackups() {
    const count = this.selectedBackups.size;
    if (count === 0) return;
    
    // Show confirmation modal
    const confirmed = await showConfirm(
      `Are you sure you want to delete ${count} backup${count > 1 ? 's' : ''}? This action cannot be undone.`,
      'Confirm Bulk Delete'
    );
    
    if (!confirmed) return;
    
    try {
      const filenames = Array.from(this.selectedBackups);
      
      const response = await fetch('/api/database/backups/delete-multiple', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ filenames })
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.message || 'Failed to delete backups');
      }
      
      // Show success message
      let message = `Successfully deleted ${data.deleted} backup${data.deleted > 1 ? 's' : ''}`;
      if (data.failed > 0) {
        message += `. ${data.failed} failed to delete.`;
        if (data.errors && data.errors.length > 0) {
          console.error('Bulk delete errors:', data.errors);
        }
      }
      
      await showAlert(message, data.failed > 0 ? 'Warning' : 'Success');
      
      // Reload the backups list
      await this.loadAvailableBackups();
      
    } catch (error) {
      console.error('Error deleting backups:', error);
      await showAlert(`Error deleting backups: ${error.message}`, 'Error');
    }
  }

  async restoreFromAutoBackup(filename) {
    // Show confirmation modal
    this.showRestoreConfirmModal(filename);
  }

  showRestoreConfirmModal(filename) {
    const modal = document.getElementById('restoreModal');
    const titleElement = document.getElementById('restoreModalTitle');
    const messageElement = document.getElementById('restoreModalMessage');
    const confirmBtn = document.getElementById('restoreModalConfirmBtn');
    const cancelBtn = document.getElementById('restoreModalCancelBtn');

    // Set confirmation content
    titleElement.textContent = 'Confirm Restore';
    titleElement.style.color = 'var(--warning-color, #f59e0b)';
    messageElement.innerHTML = `Are you sure you want to restore from <strong>"${this.escapeHtml(filename)}"</strong>?<br><br>This will replace all current data with the backup. This action cannot be undone.`;
    
    confirmBtn.textContent = 'Restore';
    confirmBtn.style.display = 'inline-block';
    cancelBtn.style.display = 'inline-block';

    modal.classList.add('active');

    // Handle cancel
    const handleCancel = () => {
      modal.classList.remove('active');
      confirmBtn.removeEventListener('click', handleConfirm);
      cancelBtn.removeEventListener('click', handleCancel);
    };

    // Handle confirm
    const handleConfirm = async () => {
      // Remove event listeners
      confirmBtn.removeEventListener('click', handleConfirm);
      cancelBtn.removeEventListener('click', handleCancel);
      
      // Update modal to show progress
      titleElement.textContent = 'Restoring Database';
      titleElement.style.color = 'var(--primary-color)';
      messageElement.textContent = 'This may take several minutes for large databases. Please wait.';
      confirmBtn.style.display = 'none';
      cancelBtn.style.display = 'none';

      // Disable all restore buttons
      const restoreButtons = document.querySelectorAll('.backup-restore-btn');
      restoreButtons.forEach(btn => btn.disabled = true);

      try {
        const progressId = this.startRestoreProgress('Starting the restore');

        // Set up timeout for 25 minutes (slightly less than backend 30 min timeout)
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 25 * 60 * 1000);

        const response = await fetch(`/api/database/backups/restore/${filename}`, {
          method: 'POST',
          headers: { 'X-Restore-Progress-Id': progressId },
          signal: controller.signal
        });

        clearTimeout(timeoutId);

        // Check if response is JSON
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          throw new Error('Server returned an invalid response. The operation may have timed out. Please check if the restore completed successfully by refreshing the page.');
        }

        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.message || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        if (data.success) {
          // Show success in modal
          this.showRestoreResultInModal('Restore Successful', data.message, true);
        } else {
          // Show error in modal and re-enable buttons
          this.showRestoreResultInModal('Restore Failed', data.message, false);
          restoreButtons.forEach(btn => btn.disabled = false);
        }

      } catch (error) {
        console.error('Error restoring from automatic backup:', error);
        
        let errorMessage = error.message;
        if (error.name === 'AbortError') {
          errorMessage = 'The restore operation timed out after 25 minutes. For very large databases, this may still be processing. Please wait a few minutes and refresh the page to check if the restore completed.';
        } else if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
          errorMessage = 'Network connection lost during restore. The restore may still be processing on the server. Please wait a few minutes and refresh the page to check the status.';
        }
        
        // Show error in modal
        this.showRestoreResultInModal('Restore Failed', errorMessage, false);
        
        // Re-enable buttons on error
        restoreButtons.forEach(btn => btn.disabled = false);
      }
    };

    confirmBtn.addEventListener('click', handleConfirm);
    setupModalEscapeClose(modal, handleCancel);
    cancelBtn.addEventListener('click', handleCancel);
  }

  // Returns the id to send with the restore request.
  startRestoreProgress(initialText) {
    // A restore can't be cancelled, so Escape must not hide it
    setupModalEscapeClose(document.getElementById('restoreModal'), () => {});

    return this.restoreProgress.start(initialText);
  }

  showRestoreResultInModal(title, message, success) {
    this.restoreProgress.stop();

    const modal = document.getElementById('restoreModal');
    const titleElement = document.getElementById('restoreModalTitle');
    const messageElement = document.getElementById('restoreModalMessage');
    const confirmBtn = document.getElementById('restoreModalConfirmBtn');
    const cancelBtn = document.getElementById('restoreModalCancelBtn');

    titleElement.textContent = title;
    titleElement.style.color = success ? 'var(--success-color)' : 'var(--error-color)';
    messageElement.textContent = message;

    confirmBtn.textContent = 'OK';
    confirmBtn.style.display = 'inline-block';
    cancelBtn.style.display = 'none';

    // OK button handler
    const handleOk = () => {
      modal.classList.remove('active');
      confirmBtn.removeEventListener('click', handleOk);
      
      // Reload page after successful restore
      if (success) {
        window.location.reload();
      }
    };

    setupModalEscapeClose(modal, handleOk);
    confirmBtn.addEventListener('click', handleOk);
  }

  async deleteBackup(filename) {
    // Show confirmation dialog
    const confirmed = await showConfirm(
      `Are you sure you want to delete "${filename}"?\n\nThis action cannot be undone.`,
      'Confirm Delete'
    );
    
    if (!confirmed) {
      return;
    }

    try {
      const response = await fetch(`/api/database/backups/delete/${filename}`, {
        method: 'DELETE'
      });

      const contentType = response.headers.get('content-type');
      if (!contentType || !contentType.includes('application/json')) {
        throw new Error('Server returned an invalid response.');
      }

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.message || `HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      if (data.success) {
        await showAlert('Backup deleted successfully!', 'Delete Successful');
        // Refresh backup list
        await this.loadAvailableBackups();
      } else {
        throw new Error(data.message || 'Failed to delete backup.');
      }

    } catch (error) {
      console.error('Error deleting backup:', error);
      await showAlert(`Failed to delete backup:\n\n${error.message}`, 'Error');
    }
  }

  async toggleBackupEnabled(enabled) {
    try {
      const response = await fetch('/api/settings/backup/config', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ enabled })
      });

      if (!response.ok) {
        const data = await response.json();
        if (this.backupEnabled) this.backupEnabled.checked = !enabled;
        
        // Check if error is about missing configuration
        if (data.message && data.message.includes('must be set before enabling')) {
          await showAlert(
            'Please configure all backup settings below before enabling automatic backups.',
            'Configuration Required'
          );
        } else {
          await showAlert(data.message || 'Failed to update backup settings', 'Error');
        }
        return;
      }

      const data = await response.json();

      if (!data.success) {
        // Revert toggle on error
        if (this.backupEnabled) this.backupEnabled.checked = !enabled;
        
        // Check if error is about missing configuration
        if (data.message && data.message.includes('must be set before enabling')) {
          await showAlert(
            'Please configure all backup settings below before enabling automatic backups.',
            'Configuration Required'
          );
        } else {
          await showAlert(data.message, 'Error');
        }
      } else {
        // Reload status to show updated info
        await this.loadBackupStatus();
      }
    } catch (error) {
      console.error('Error toggling backup:', error);
      // Revert toggle on error
      if (this.backupEnabled) this.backupEnabled.checked = !enabled;
      await showAlert(error.message, 'Error');
    }
  }

  showStatus(message, type = 'info') {
    this.safeSetText(this.statusElement, message);
    this.safeSetClass(this.statusElement, `settings-status ${type}`);
  }
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
  // Save initial scroll position (browser may have restored it)
  const savedScrollY = window.scrollY;
  const savedScrollX = window.scrollX;
  
  const backupRestore = new BackupRestore();
  backupRestore.init().then(() => {
    // Restore scroll position after initialization
    // This prevents form updates from scrolling the page
    requestAnimationFrame(() => {
      window.scrollTo(savedScrollX, savedScrollY);
    });
  });
});
