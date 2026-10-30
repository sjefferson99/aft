// Profile page functionality

class ProfileManager {
  constructor() {
    this.profileForm = null;
    this.passwordForm = null;
    this.currentUser = null;
  }

  async init() {
    // Wait for header to load
    await this.waitForHeader();

    // Get form elements
    this.profileForm = document.getElementById('profile-form');
    this.passwordForm = document.getElementById('password-form');

    // Load current user data
    await this.loadUserData();

    // Setup form handlers
    this.setupFormHandlers();
  }

  async waitForHeader() {
    // Wait for header to initialize
    while (!window.header) {
      await new Promise(resolve => setTimeout(resolve, 100));
    }
  }

  async loadUserData() {
    try {
      const response = await fetch('/api/auth/me');
      
      if (!response.ok) {
        this.showMessage('profile-status', 'Failed to load user data', 'error');
        return;
      }

      const data = await response.json();
      if (data.user) {
        this.currentUser = data.user;
        this.populateForm();
      } else {
        this.showMessage('profile-status', 'User not logged in', 'error');
        // Redirect to login after 2 seconds
        setTimeout(() => {
          window.location.href = '/login.html';
        }, 2000);
      }
    } catch (error) {
      console.error('Error loading user data:', error);
      this.showMessage('profile-status', 'Error loading user data', 'error');
    }
  }

  populateForm() {
    if (!this.currentUser) return;

    // Populate form fields
    document.getElementById('display-name').value = this.currentUser.display_name || '';
    document.getElementById('username').value = this.currentUser.username || '';
    document.getElementById('email').value = this.currentUser.email || '';

    // Highlight the current profile colour swatch
    const currentColour = (this.currentUser.profile_colour || '').toLowerCase();
    document.querySelectorAll('.colour-swatch').forEach(swatch => {
      const isSelected = swatch.dataset.colour.toLowerCase() === currentColour;
      swatch.classList.toggle('selected', isSelected);
      swatch.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
    });

    // Disable email if OAuth user
    if (this.currentUser.oauth_provider) {
      const emailInput = document.getElementById('email');
      emailInput.disabled = true;
      const emailHelp = emailInput.previousElementSibling;
      if (emailHelp && emailHelp.classList.contains('field-help')) {
        emailHelp.textContent = 'Email cannot be changed for OAuth accounts.';
      }

      // Also disable password form for OAuth users
      const passwordSection = this.passwordForm.closest('.profile-section');
      if (passwordSection) {
        const passwordHelp = passwordSection.querySelector('h3');
        if (passwordHelp) {
          passwordHelp.innerHTML = 'Change Password <span style="color: var(--text-muted); font-size: 14px; font-weight: normal;">(Not available for OAuth accounts)</span>';
        }
        this.passwordForm.querySelectorAll('input').forEach(input => {
          input.disabled = true;
        });
        this.passwordForm.querySelector('button').disabled = true;
      }
    }
  }

  setupFormHandlers() {
    // Profile form submission
    this.profileForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.handleProfileUpdate();
    });

    // Password form submission
    this.passwordForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.handlePasswordChange();
    });

    // Colour swatch selection
    document.querySelectorAll('.colour-swatch').forEach(swatch => {
      swatch.addEventListener('click', async () => {
        await this.handleColourSelection(swatch.dataset.colour);
      });
    });
  }

  async handleColourSelection(colour) {
    try {
      const response = await fetch('/api/users/me/profile-colour', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_colour: colour })
      });
      const data = await response.json();
      if (response.ok && data.success) {
        if (this.currentUser) this.currentUser.profile_colour = colour;
        document.querySelectorAll('.colour-swatch').forEach(s => {
          const isSelected = s.dataset.colour.toLowerCase() === colour.toLowerCase();
          s.classList.toggle('selected', isSelected);
          s.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
        });
        this.showMessage('colour-status', 'Colour updated', 'success');
      } else {
        this.showMessage('colour-status', data.error || 'Failed to update colour', 'error');
      }
    } catch (error) {
      console.error('Error updating profile colour:', error);
      this.showMessage('colour-status', 'Error updating colour', 'error');
    }
  }


  async handleProfileUpdate() {
    const saveBtn = document.getElementById('save-profile-btn');
    const statusEl = document.getElementById('profile-status');

    // Get form values
    const displayName = document.getElementById('display-name').value.trim();
    const username = document.getElementById('username').value.trim();
    const email = document.getElementById('email').value.trim();

    // Basic validation
    if (!username) {
      this.showMessage('profile-status', 'Username is required', 'error');
      return;
    }

    if (!email) {
      this.showMessage('profile-status', 'Email is required', 'error');
      return;
    }

    // Email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      this.showMessage('profile-status', 'Please enter a valid email address', 'error');
      return;
    }

    // Disable button during submission
    saveBtn.disabled = true;
    this.showMessage('profile-status', 'Saving...', 'info');

    try {
      const response = await fetch('/api/auth/profile', {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          display_name: displayName,
          username: username,
          email: email
        })
      });

      const data = await response.json();

      if (response.ok && data.success) {
        this.showMessage('profile-status', 'Profile updated successfully', 'success');
        
        // Update cached user data
        sessionStorage.removeItem('currentUser');
        
        // Reload user data and update header
        await this.loadUserData();
        if (window.header) {
          await window.header.loadCurrentUser();
        }
      } else {
        this.showMessage('profile-status', data.error || 'Failed to update profile', 'error');
      }
    } catch (error) {
      console.error('Error updating profile:', error);
      this.showMessage('profile-status', 'Error updating profile', 'error');
    } finally {
      saveBtn.disabled = false;
    }
  }

  async handlePasswordChange() {
    const changeBtn = document.getElementById('change-password-btn');
    const statusEl = document.getElementById('password-status');

    // Get form values
    const currentPassword = document.getElementById('current-password').value;
    const newPassword = document.getElementById('new-password').value;
    const confirmPassword = document.getElementById('confirm-password').value;

    // Validation
    if (!currentPassword) {
      this.showMessage('password-status', 'Current password is required', 'error');
      return;
    }

    if (!newPassword) {
      this.showMessage('password-status', 'New password is required', 'error');
      return;
    }

    if (newPassword.length < 8) {
      this.showMessage('password-status', 'Password must be at least 8 characters', 'error');
      return;
    }

    if (newPassword !== confirmPassword) {
      this.showMessage('password-status', 'Passwords do not match', 'error');
      return;
    }

    // Disable button during submission
    changeBtn.disabled = true;
    this.showMessage('password-status', 'Changing password...', 'info');

    try {
      const response = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword
        })
      });

      const data = await response.json();

      if (response.ok && data.success) {
        this.showMessage('password-status', 'Password changed successfully', 'success');
        
        // Clear form
        this.passwordForm.reset();
      } else {
        this.showMessage('password-status', data.error || 'Failed to change password', 'error');
      }
    } catch (error) {
      console.error('Error changing password:', error);
      this.showMessage('password-status', 'Error changing password', 'error');
    } finally {
      changeBtn.disabled = false;
    }
  }

  showMessage(elementId, message, type) {
    const statusEl = document.getElementById(elementId);
    if (!statusEl) return;

    statusEl.textContent = message;
    statusEl.className = `status-message ${type} show`;

    // Auto-hide success messages after 5 seconds
    if (type === 'success') {
      setTimeout(() => {
        statusEl.classList.remove('show');
      }, 5000);
    }
  }
}

// Passkeys section: list, add, rename and remove the user's passkeys.
class ProfilePasskeys {
  constructor() {
    this.section = document.getElementById('passkeys-section');
    this.list = document.getElementById('passkey-list');
    this.empty = document.getElementById('passkey-empty');
    this.addButton = document.getElementById('add-passkey-btn');
    this.addModal = document.getElementById('add-passkey-modal');
    this.renameModal = document.getElementById('rename-passkey-modal');
    this.removeModal = document.getElementById('remove-passkey-modal');
    this.selected = null;
    this.returnFocusTo = null;
  }

  async init() {
    if (!window.Passkeys || !(await window.Passkeys.isEnabled())) {
      return;
    }
    this.section.hidden = false;

    if (!window.Passkeys.isSupported()) {
      document.getElementById('passkeys-unsupported').hidden = false;
      this.addButton.disabled = true;
    }

    this.addButton.addEventListener('click', () => this.openAddModal());
    document.getElementById('add-passkey-form').addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleAdd();
    });
    document.getElementById('add-passkey-cancel-btn').addEventListener('click', () => this.closeModal(this.addModal));

    document.getElementById('rename-passkey-form').addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleRename();
    });
    document.getElementById('rename-passkey-cancel-btn').addEventListener('click', () => this.closeModal(this.renameModal));

    document.getElementById('remove-passkey-ok-btn').addEventListener('click', () => this.handleRemove());
    document.getElementById('remove-passkey-cancel-btn').addEventListener('click', () => this.closeModal(this.removeModal));

    [this.addModal, this.renameModal, this.removeModal].forEach((modal) => {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) {
          this.closeModal(modal);
        }
      });
    });

    await this.loadPasskeys();
  }

  async request(url, options = {}) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(url, {
        ...options,
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal
      });
      let data = {};
      try {
        data = await response.json();
      } catch (e) {
        // Non-JSON error response
      }
      if (!response.ok || !data.success) {
        throw new Error(data.message || 'Request failed. Please try again.');
      }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') {
        throw new Error('The request timed out. Please check your connection and try again.');
      }
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async loadPasskeys() {
    try {
      const data = await this.request('/api/auth/passkeys');
      this.render(data.passkeys || []);
    } catch (error) {
      console.error('Error loading passkeys:', error);
      this.showStatus(`Could not load passkeys: ${error.message}`, 'error');
    }
  }

  formatDate(value) {
    return value ? new Date(value).toLocaleDateString() : null;
  }

  render(passkeys) {
    this.list.replaceChildren();
    this.empty.hidden = passkeys.length > 0;

    passkeys.forEach((passkey) => {
      const item = document.createElement('li');
      item.className = 'passkey-item';
      item.dataset.passkeyId = passkey.id;

      const info = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'passkey-name';
      name.textContent = passkey.name;
      if (passkey.synced) {
        const badge = document.createElement('span');
        badge.className = 'passkey-badge';
        badge.textContent = 'Synced';
        badge.title = 'Backed up and available on your other devices';
        name.appendChild(badge);
      }
      const meta = document.createElement('div');
      meta.className = 'passkey-meta';
      const added = this.formatDate(passkey.created_at) || 'Unknown';
      const used = this.formatDate(passkey.last_used_at) || 'Never';
      meta.textContent = `Added ${added} · Last used ${used}`;
      info.append(name, meta);

      const actions = document.createElement('div');
      actions.className = 'passkey-actions';
      const renameBtn = document.createElement('button');
      renameBtn.type = 'button';
      renameBtn.className = 'btn btn-secondary btn-sm';
      renameBtn.textContent = 'Rename';
      renameBtn.setAttribute('aria-label', `Rename passkey ${passkey.name}`);
      renameBtn.addEventListener('click', () => this.openRenameModal(passkey, renameBtn));
      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'btn btn-danger btn-sm';
      removeBtn.textContent = 'Remove';
      removeBtn.setAttribute('aria-label', `Remove passkey ${passkey.name}`);
      removeBtn.addEventListener('click', () => this.openRemoveModal(passkey, removeBtn));
      actions.append(renameBtn, removeBtn);

      item.append(info, actions);
      this.list.appendChild(item);
    });
  }

  openModal(modal, focusEl, trigger) {
    this.returnFocusTo = trigger || document.activeElement;
    modal.querySelectorAll('.status-message').forEach((el) => {
      el.textContent = '';
      el.classList.remove('show');
    });
    modal.classList.add('show');
    setupModalEscapeClose(modal, () => this.closeModal(modal));
    focusEl.focus();
  }

  closeModal(modal) {
    modal.classList.remove('show');
    this.selected = null;
    if (this.returnFocusTo && document.body.contains(this.returnFocusTo)) {
      this.returnFocusTo.focus();
    }
    this.returnFocusTo = null;
  }

  showModalError(id, message) {
    const el = document.getElementById(id);
    el.textContent = message;
    el.classList.add('show');
  }

  setBusy(modal, busy) {
    modal.querySelectorAll('button, input').forEach((el) => {
      el.disabled = busy;
    });
  }

  openAddModal() {
    document.getElementById('add-passkey-password').value = '';
    document.getElementById('add-passkey-name').value = '';
    this.openModal(this.addModal, document.getElementById('add-passkey-password'), this.addButton);
  }

  async handleAdd() {
    const password = document.getElementById('add-passkey-password').value;
    const name = document.getElementById('add-passkey-name').value.trim();
    if (!password) {
      this.showModalError('add-passkey-error', 'Enter your current password.');
      return;
    }

    this.setBusy(this.addModal, true);
    document.getElementById('add-passkey-error').classList.remove('show');
    try {
      await window.Passkeys.register(password, name);
      this.closeModal(this.addModal);
      this.showStatus('Passkey added', 'success');
      await this.loadPasskeys();
    } catch (error) {
      console.error('Error adding passkey:', error);
      this.showModalError('add-passkey-error', window.Passkeys.describeError(error));
    } finally {
      this.setBusy(this.addModal, false);
    }
  }

  openRenameModal(passkey, trigger) {
    this.selected = passkey;
    const input = document.getElementById('rename-passkey-name');
    input.value = passkey.name;
    this.openModal(this.renameModal, input, trigger);
    input.select();
  }

  async handleRename() {
    const passkey = this.selected;
    const name = document.getElementById('rename-passkey-name').value.trim();
    if (!passkey) {
      return;
    }
    if (!name) {
      this.showModalError('rename-passkey-error', 'Enter a name.');
      return;
    }

    this.setBusy(this.renameModal, true);
    try {
      await this.request(`/api/auth/passkeys/${encodeURIComponent(passkey.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ name })
      });
      this.closeModal(this.renameModal);
      this.showStatus('Passkey renamed', 'success');
      await this.loadPasskeys();
    } catch (error) {
      console.error('Error renaming passkey:', error);
      this.showModalError('rename-passkey-error', error.message);
    } finally {
      this.setBusy(this.renameModal, false);
    }
  }

  openRemoveModal(passkey, trigger) {
    this.selected = passkey;
    document.getElementById('remove-passkey-message').textContent =
      `Remove "${passkey.name}"? You won't be able to sign in with it any more. ` +
      'You may also want to delete it from your device or password manager.';
    this.openModal(this.removeModal, document.getElementById('remove-passkey-cancel-btn'), trigger);
  }

  async handleRemove() {
    const passkey = this.selected;
    if (!passkey) {
      return;
    }

    this.setBusy(this.removeModal, true);
    try {
      const data = await this.request(`/api/auth/passkeys/${encodeURIComponent(passkey.id)}`, {
        method: 'DELETE'
      });
      this.closeModal(this.removeModal);
      if (data.signed_out) {
        // This session was signed in with the removed passkey, so it has ended.
        sessionStorage.removeItem('currentUser');
        window.location.href = '/login.html';
        return;
      }
      this.showStatus('Passkey removed', 'success');
      await this.loadPasskeys();
    } catch (error) {
      console.error('Error removing passkey:', error);
      this.showModalError('remove-passkey-error', error.message);
    } finally {
      this.setBusy(this.removeModal, false);
    }
  }

  showStatus(message, type) {
    const statusEl = document.getElementById('passkey-status');
    statusEl.textContent = message;
    statusEl.className = `status-message ${type} show`;
    if (type === 'success') {
      setTimeout(() => {
        statusEl.classList.remove('show');
      }, 5000);
    }
  }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
  const profileManager = new ProfileManager();
  await profileManager.init();
  await new ProfilePasskeys().init();
});
