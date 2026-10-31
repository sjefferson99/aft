// User Management functionality
class UserManagement {
  constructor() {
    this.pendingUsersContainer = document.getElementById('pending-users-list');
    this.pendingUsersLoading = document.getElementById('pending-users-loading');
    this.pendingUsersEmpty = document.getElementById('pending-users-empty');
    
    this.activeUsersContainer = document.getElementById('active-users-list');
    this.activeUsersLoading = document.getElementById('active-users-loading');
    this.activeUsersEmpty = document.getElementById('active-users-empty');
    this.usersPagination = document.getElementById('users-pagination');
    this.usersPageSize = document.getElementById('users-page-size');
    this.usersPageStatus = document.getElementById('users-page-status');
    this.usersPrevBtn = document.getElementById('users-prev-btn');
    this.usersNextBtn = document.getElementById('users-next-btn');
    
    this.searchInput = document.getElementById('user-search');
    this.statusMessage = document.getElementById('status-message');
    
    this.confirmModal = document.getElementById('confirm-modal');
    this.confirmModalTitle = document.getElementById('confirm-modal-title');
    this.confirmModalMessage = document.getElementById('confirm-modal-message');
    this.confirmCancelBtn = document.getElementById('confirm-cancel-btn');
    this.confirmOkBtn = document.getElementById('confirm-ok-btn');
    this.showActiveOnlyToggle = document.getElementById('show-active-only');
    
    // Add user modal elements
    this.addUserBtn = document.getElementById('add-user-btn');
    this.addUserModal = document.getElementById('add-user-modal');
    this.addUserEmail = document.getElementById('add-user-email');
    this.addUserUsername = document.getElementById('add-user-username');
    this.addUserDisplayName = document.getElementById('add-user-display-name');
    this.addUserPassword = document.getElementById('add-user-password');
    this.addUserConfirmPassword = document.getElementById('add-user-confirm-password');
    this.addUserPasswordStrengthBar = document.getElementById('add-user-password-strength-bar');
    this.addUserErrorMessage = document.getElementById('add-user-error-message');
    this.addUserCancelBtn = document.getElementById('add-user-cancel-btn');
    this.addUserOkBtn = document.getElementById('add-user-ok-btn');

    // Reset password modal elements
    this.resetPasswordModal = document.getElementById('reset-password-modal');
    this.resetPasswordUserName = document.getElementById('reset-password-user-name');
    this.resetPasswordNew = document.getElementById('reset-password-new');
    this.resetPasswordConfirm = document.getElementById('reset-password-confirm');
    this.resetPasswordErrorMessage = document.getElementById('reset-password-error-message');
    this.resetPasswordCancelBtn = document.getElementById('reset-password-cancel-btn');
    this.resetPasswordOkBtn = document.getElementById('reset-password-ok-btn');
    
    // Role assignment elements
    this.addRoleModal = document.getElementById('add-role-modal');
    this.addRoleUserName = document.getElementById('add-role-user-name');
    this.roleSelect = document.getElementById('role-select');
    this.boardSelect = document.getElementById('board-select');
    this.addRoleCancelBtn = document.getElementById('add-role-cancel-btn');
    this.addRoleOkBtn = document.getElementById('add-role-ok-btn');
    this.testUserSection = document.getElementById('test-user-guidance-section');
    
    this.pendingCallback = null;
    this.allUsers = [];
    this.filteredUsers = [];
    this.usersPage = 1;
    this.usersPerPage = 10;
    this.showActiveOnly = true;
    this.currentUserId = null;
    this.roles = [];
    this.boards = [];
    this.canAssignAllRoles = false; // Whether user has role.manage permission
    this.canManageUsers = false;
    this.canAssignRoles = false;
    this.canResetPasswords = false;
    this.canViewTestUserGuidance = false;
    this.canRemoveTestUser = false;
    this.testUserDetected = false;
    this.selectedResetUser = null;
    
    // Permission model elements
    this.permissionModelLoading = document.getElementById('permission-model-loading');
    this.permissionModelContent = document.getElementById('permission-model-content');
  }

  async init() {
    // Wait for user data to be ready (loaded by header.js)
    if (!window.userDataReady) {
      setTimeout(() => this.init(), 100);
      return;
    }
    
    // Check permission before loading page content
    const hasUserManage = typeof hasPermission === 'function' && hasPermission('user.manage');
    const hasUserRole = typeof hasPermission === 'function' && hasPermission('user.role');
    const hasAdministratorRole = Array.isArray(window.currentUser?.roles)
      && window.currentUser.roles.some(role => role && role.name === 'administrator');

    this.canManageUsers = hasUserManage;
    this.canAssignRoles = hasUserRole;
    this.canResetPasswords = hasUserManage && hasAdministratorRole;
    this.canViewTestUserGuidance = hasUserManage || hasUserRole;
    this.canRemoveTestUser = hasUserManage;
    
    if (!hasUserManage && !hasUserRole) {
      // User doesn't have either permission - show access denied
      showAccessDenied('You need either "user.manage" or "user.role" permission to access this page.');
      return;
    }
    
    this.attachEventListeners();
    
    // Load data based on permissions
    const loadPromises = [this.loadActiveUsers()];

    if (hasUserManage) {
      loadPromises.push(this.loadPendingUsers());
    }

    if (hasUserRole) {
      loadPromises.push(this.loadRoles());
      loadPromises.push(this.loadBoards());
    }

    if (this.canViewTestUserGuidance) {
      loadPromises.push(this.loadTestUserGuidance());
    } else if (this.testUserSection) {
      this.testUserSection.style.display = 'none';
    }
    
    // Load permission model for everyone (it's public documentation)
    loadPromises.push(this.loadPermissionModel());
    
    await Promise.all(loadPromises);
    
    // Show role restriction note if user doesn't have role.manage permission
    const hasRoleManage = typeof hasPermission === 'function' && hasPermission('role.manage');
    if (hasUserRole && !hasRoleManage) {
      const roleRestrictionNote = document.getElementById('role-restriction-note');
      if (roleRestrictionNote) {
        roleRestrictionNote.style.display = 'block';
      }
    }
    
    // Hide sections based on permissions
    if (!hasUserManage) {
      // Role assignment only lists active users, so there is nothing to toggle
      const pendingSection = document.getElementById('pending-users-section');
      const activeOnlyFilter = this.showActiveOnlyToggle?.closest('.filter-toggle');
      if (pendingSection) pendingSection.style.display = 'none';
      if (activeOnlyFilter) activeOnlyFilter.style.display = 'none';
    } else {
      // Show Add User button if user can manage users
      if (this.addUserBtn) {
        this.addUserBtn.style.display = 'inline-flex';
      }
    }
  }

  attachEventListeners() {
    // Search functionality
    this.searchInput.addEventListener('input', () => {
      this.usersPage = 1;
      this.filterUsers(this.searchInput.value);
    });

    // Active only toggle
    if (this.showActiveOnlyToggle) {
      this.showActiveOnlyToggle.addEventListener('change', (e) => {
        this.showActiveOnly = e.target.checked;
        this.usersPage = 1;
        this.filterUsers(this.searchInput.value);
      });
    }

    // Paging
    this.usersPageSize.addEventListener('change', () => {
      this.usersPerPage = this.usersPageSize.value === 'all' ? Infinity : Number(this.usersPageSize.value);
      this.usersPage = 1;
      this.renderActiveUsers();
    });

    this.usersPrevBtn.addEventListener('click', () => this.changeUsersPage(-1));
    this.usersNextBtn.addEventListener('click', () => this.changeUsersPage(1));

    // Modal close handlers
    this.confirmCancelBtn.addEventListener('click', () => {
      this.closeConfirmModal();
    });

    // Add role modal handlers
    if (this.addRoleCancelBtn) {
      this.addRoleCancelBtn.addEventListener('click', () => {
        this.closeAddRoleModal();
      });
    }

    if (this.addRoleOkBtn) {
      this.addRoleOkBtn.addEventListener('click', () => {
        this.handleAddRole();
      });
    }
    
    // Role select change handler - show/hide board options based on role type
    if (this.roleSelect) {
      this.roleSelect.addEventListener('change', () => {
        this.handleRoleSelectChange();
      });
    }

    // Click outside modal to close
    this.confirmModal.addEventListener('click', (e) => {
      if (e.target === this.confirmModal) {
        this.closeConfirmModal();
      }
    });

    if (this.addRoleModal) {
      this.addRoleModal.addEventListener('click', (e) => {
        if (e.target === this.addRoleModal) {
          this.closeAddRoleModal();
        }
      });
    }

    const testUserBtn = document.getElementById('test-user-btn');
    if (testUserBtn) {
      testUserBtn.addEventListener('click', () => {
        this.confirmRemoveKnownTestUser();
      });
    }

    // Add user button and modal handlers
    if (this.addUserBtn) {
      this.addUserBtn.addEventListener('click', () => {
        this.openAddUserModal();
      });
    }

    if (this.addUserCancelBtn) {
      this.addUserCancelBtn.addEventListener('click', () => {
        this.closeAddUserModal();
      });
    }

    if (this.resetPasswordCancelBtn) {
      this.resetPasswordCancelBtn.addEventListener('click', () => {
        this.closeResetPasswordModal();
      });
    }

    if (this.resetPasswordOkBtn) {
      this.resetPasswordOkBtn.addEventListener('click', () => {
        this.handleResetPassword();
      });
    }

    if (this.addUserOkBtn) {
      this.addUserOkBtn.addEventListener('click', () => {
        this.handleCreateUser();
      });
    }

    if (this.addUserModal) {
      this.addUserModal.addEventListener('click', (e) => {
        if (e.target === this.addUserModal) {
          this.closeAddUserModal();
        }
      });
    }

    if (this.resetPasswordModal) {
      this.resetPasswordModal.addEventListener('click', (e) => {
        if (e.target === this.resetPasswordModal) {
          this.closeResetPasswordModal();
        }
      });
    }

    // Password strength indicator for add user modal
    if (this.addUserPassword) {
      this.addUserPassword.addEventListener('input', () => {
        this.updatePasswordStrength();
      });
    }
  }

  async loadPendingUsers() {
    try {
      this.pendingUsersLoading.style.display = 'block';
      this.pendingUsersEmpty.style.display = 'none';
      this.pendingUsersContainer.style.display = 'none';

      const response = await fetch('/api/users/pending');
      
      // Check for permission errors
      if (response.status === 403) {
        showAccessDenied('You need the "user.manage" permission to access pending user data.');
        return;
      }
      
      const data = await response.json();

      if (data.success && data.users) {
        if (data.users.length === 0) {
          this.pendingUsersLoading.style.display = 'none';
          this.pendingUsersEmpty.style.display = 'block';
        } else {
          this.renderPendingUsers(data.users);
          this.pendingUsersLoading.style.display = 'none';
          this.pendingUsersContainer.style.display = 'block';
        }
      } else {
        throw new Error(data.message || 'Failed to load pending users');
      }
    } catch (error) {
      console.error('Error loading pending users:', error);
      this.showStatus('Error loading pending users: ' + error.message, 'error');
      this.pendingUsersLoading.style.display = 'none';
    }
  }

  async fetchApprovedUsers() {
    const response = await fetch('/api/users?status=approved');

    if (response.status === 403) {
      showAccessDenied('You need the "user.manage" permission to access active user data.');
      return null;
    }

    const data = await response.json();

    if (data.success && data.users) {
      return data.users;
    }
    throw new Error(data.message || 'Failed to load users');
  }

  async fetchRoleUsers() {
    // Role editing is optional for a row, so a failure here still shows the list
    try {
      const response = await fetch('/api/roles/users');

      if (response.status === 403) {
        console.warn('Permission denied loading role users');
        return null;
      }

      const data = await response.json();

      if (data.success && data.users) {
        return data.users;
      }
      throw new Error(data.message || 'Failed to load users for role assignment');
    } catch (error) {
      console.error('Error loading role users:', error);
      this.showStatus('Error loading users for role assignment: ' + error.message, 'error');
      return null;
    }
  }

  // Each endpoint needs a different permission. /api/users has the account
  // details but only global roles, and /api/roles/users has every role but only
  // active users. roleAssignments is null for rows whose roles can't be edited.
  mergeUsers(approvedUsers, roleUsers) {
    if (!this.canManageUsers) {
      return (roleUsers || []).map(user => ({ ...user, roles: [], roleAssignments: user.roles }));
    }

    const roleUsersById = new Map((roleUsers || []).map(user => [user.id, user]));
    return approvedUsers.map(user => ({
      ...user,
      roleAssignments: roleUsersById.get(user.id)?.roles || null
    }));
  }

  async loadActiveUsers() {
    try {
      const [approvedUsers, roleUsers] = await Promise.all([
        this.canManageUsers ? this.fetchApprovedUsers() : null,
        this.canAssignRoles ? this.fetchRoleUsers() : null
      ]);

      if (this.canManageUsers && !approvedUsers) {
        return;
      }

      this.allUsers = this.mergeUsers(approvedUsers, roleUsers);
      this.filterUsers(this.searchInput.value);
    } catch (error) {
      console.error('Error loading users:', error);
      this.showStatus('Error loading users: ' + error.message, 'error');
    } finally {
      this.activeUsersLoading.style.display = 'none';
    }
  }

  renderPendingUsers(users) {
    this.pendingUsersContainer.innerHTML = '';

    users.forEach(user => {
      const userCard = this.createPendingUserCard(user);
      this.pendingUsersContainer.appendChild(userCard);
    });
  }

  createPendingUserCard(user) {
    const card = document.createElement('div');
    card.className = 'user-card pending-user-card';
    card.dataset.userId = user.id;

    const displayName = user.display_name || user.username || user.email;
    const createdDate = user.created_at ? new Date(user.created_at).toLocaleDateString() : 'Unknown';
    const safeUserId = this.escapeHtml(String(user.id));

    card.innerHTML = `
      <div class="user-info">
        <div class="user-avatar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
          </svg>
        </div>
        <div class="user-details">
          <div class="user-name">${this.escapeHtml(displayName)}</div>
          <div class="user-email">${this.escapeHtml(user.email)}</div>
          ${user.username ? `<div class="user-meta">Username: ${this.escapeHtml(user.username)}</div>` : ''}
          <div class="user-meta">Registered: ${createdDate}</div>
        </div>
      </div>
      <div class="user-actions">
        <button class="btn btn-primary btn-sm" data-action="approve" data-user-id="${safeUserId}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
          Approve
        </button>
        <button class="btn btn-danger btn-sm" data-action="reject" data-user-id="${safeUserId}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
          Reject
        </button>
      </div>
    `;

    // Attach event listeners to buttons
    const approveBtn = card.querySelector('[data-action="approve"]');
    const rejectBtn = card.querySelector('[data-action="reject"]');

    approveBtn.addEventListener('click', () => this.handleApprove(user));
    rejectBtn.addEventListener('click', () => this.handleReject(user));

    return card;
  }

  renderActiveUsers() {
    const users = this.filteredUsers;
    this.activeUsersContainer.innerHTML = '';

    if (users.length === 0) {
      this.activeUsersContainer.style.display = 'none';
      this.activeUsersEmpty.style.display = 'block';
      this.usersPagination.style.display = 'none';
      return;
    }

    this.activeUsersContainer.style.display = 'flex';
    this.activeUsersEmpty.style.display = 'none';

    // A reload can leave fewer users than the page being shown
    const totalPages = Math.ceil(users.length / this.usersPerPage) || 1;
    this.usersPage = Math.min(this.usersPage, totalPages);
    const start = this.usersPerPage === Infinity ? 0 : (this.usersPage - 1) * this.usersPerPage;
    const pageUsers = users.slice(start, start + this.usersPerPage);

    pageUsers.forEach(user => {
      const userCard = this.createActiveUserCard(user);
      this.activeUsersContainer.appendChild(userCard);
    });

    this.usersPagination.style.display = users.length > 10 ? 'flex' : 'none';
    this.usersPageStatus.textContent = `${start + 1}–${start + pageUsers.length} of ${users.length}`;
    this.usersPrevBtn.disabled = this.usersPage === 1;
    this.usersNextBtn.disabled = this.usersPage === totalPages;
  }

  changeUsersPage(delta) {
    this.usersPage += delta;
    this.renderActiveUsers();
    document.getElementById('active-users-section').scrollIntoView();
  }

  createActiveUserCard(user) {
    const card = document.createElement('div');
    card.className = 'user-card active-user-card';
    if (!user.is_active) {
      card.classList.add('user-deactivated');
    }
    card.dataset.userId = user.id;

    const isCurrentUser = Boolean(window.currentUser && user.id === window.currentUser.id);
    const displayName = user.display_name || user.username || user.email;
    const createdDate = user.created_at ? new Date(user.created_at).toLocaleDateString() : 'Unknown';
    const lastLogin = user.last_login_at ? new Date(user.last_login_at).toLocaleDateString() : 'Never';
    const safeUserId = this.escapeHtml(String(user.id));
    const passkeyCount = Number.isInteger(user.passkey_count) ? user.passkey_count : 0;

    const statusBadge = user.is_active
      ? '<span class="status-badge status-active">Active</span>'
      : '<span class="status-badge status-inactive">Inactive</span>';

    const accountActions = this.canManageUsers ? `
        ${user.is_active
          ? `<button class="btn btn-secondary btn-sm" data-action="deactivate" data-user-id="${safeUserId}" ${isCurrentUser ? 'disabled title="You cannot deactivate your own account"' : ''}>Deactivate</button>`
          : `<button class="btn btn-primary btn-sm" data-action="activate" data-user-id="${safeUserId}">Activate</button>`
        }
        ${this.canResetPasswords && !isCurrentUser
          ? `<button class="btn btn-secondary btn-sm" data-action="reset-password" data-user-id="${safeUserId}">Reset Password</button>`
          : ''
        }
        ${passkeyCount > 0
          ? `<button class="btn btn-secondary btn-sm" data-action="revoke-passkeys" data-user-id="${safeUserId}">Revoke Passkeys</button>`
          : ''
        }
    ` : '';

    card.innerHTML = `
      <div class="user-info">
        <div class="user-avatar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
          </svg>
        </div>
        <div class="user-details">
          <div class="user-name">
            ${this.escapeHtml(displayName)}
            ${statusBadge}
            ${isCurrentUser ? '<span class="status-badge user-you-badge">You</span>' : ''}
          </div>
          <div class="user-email">${this.escapeHtml(user.email)}</div>
          ${user.username ? `<div class="user-meta">Username: ${this.escapeHtml(user.username)}</div>` : ''}
          ${this.canManageUsers ? `<div class="user-meta">Registered: ${createdDate} • Last login: ${lastLogin}</div>` : ''}
          ${passkeyCount > 0 ? `<div class="user-meta">Passkeys: ${passkeyCount}</div>` : ''}
          <div class="user-roles"></div>
        </div>
      </div>
      ${accountActions ? `<div class="user-actions">${accountActions}</div>` : ''}
    `;

    this.renderUserRoles(card.querySelector('.user-roles'), user, isCurrentUser);

    // Attach event listeners to buttons
    const deactivateBtn = card.querySelector('[data-action="deactivate"]');
    // Only add event listener if it's not the current user's own account
    if (deactivateBtn && !isCurrentUser) {
      deactivateBtn.addEventListener('click', () => this.handleDeactivate(user));
    }

    const activateBtn = card.querySelector('[data-action="activate"]');
    if (activateBtn) {
      activateBtn.addEventListener('click', () => this.handleActivate(user));
    }

    const resetPasswordBtn = card.querySelector('[data-action="reset-password"]');
    if (resetPasswordBtn) {
      resetPasswordBtn.addEventListener('click', () => this.openResetPasswordModal(user));
    }

    const revokePasskeysBtn = card.querySelector('[data-action="revoke-passkeys"]');
    if (revokePasskeysBtn) {
      revokePasskeysBtn.addEventListener('click', () => this.handleRevokePasskeys(user));
    }

    return card;
  }

  // Built from DOM nodes because role and board names end up in attributes,
  // and escapeHtml doesn't escape quotes.
  renderUserRoles(container, user, isCurrentUser) {
    const displayName = user.display_name || user.username || user.email;

    if (!user.roleAssignments) {
      user.roles.forEach(role => {
        const badge = document.createElement('span');
        badge.className = 'role-badge';
        badge.textContent = role.name;
        container.appendChild(badge);
      });
      if (user.roles.length === 0) {
        container.appendChild(this.createNoRolesBadge());
      }
      return;
    }

    user.roleAssignments.forEach(role => {
      container.appendChild(this.createRoleChip(user, role, displayName, isCurrentUser));
    });
    if (user.roleAssignments.length === 0) {
      container.appendChild(this.createNoRolesBadge());
    }

    if (isCurrentUser) {
      const note = document.createElement('span');
      note.className = 'user-role-note';
      note.textContent = 'Cannot modify own roles';
      container.appendChild(note);
      return;
    }

    const addRoleBtn = document.createElement('button');
    addRoleBtn.type = 'button';
    addRoleBtn.className = 'user-role-add';
    addRoleBtn.dataset.action = 'add-role';
    addRoleBtn.textContent = '+ Add Role';
    addRoleBtn.setAttribute('aria-label', `Add role to ${displayName}`);
    addRoleBtn.addEventListener('click', () => this.openAddRoleModal(user.id, displayName));
    container.appendChild(addRoleBtn);
  }

  createNoRolesBadge() {
    const badge = document.createElement('span');
    badge.className = 'role-badge role-badge-none';
    badge.textContent = 'No roles';
    return badge;
  }

  createRoleChip(user, role, displayName, isCurrentUser) {
    const scope = role.board_name || 'Global';
    const description = `${role.role_name} (${scope})`;

    const chip = document.createElement('span');
    chip.className = 'user-role-chip';
    chip.title = description;

    const name = document.createElement('span');
    name.className = 'user-role-chip-name';
    name.textContent = role.role_name;
    chip.appendChild(name);

    const scopeLabel = document.createElement('span');
    scopeLabel.className = 'user-role-chip-scope';
    scopeLabel.textContent = scope;
    chip.appendChild(scopeLabel);

    if (!isCurrentUser) {
      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'user-role-chip-remove';
      removeBtn.textContent = '×';
      removeBtn.title = 'Remove role';
      removeBtn.setAttribute('aria-label', `Remove ${description} from ${displayName}`);
      removeBtn.addEventListener('click', () => {
        const roleScope = role.board_name ? ` on board "${role.board_name}"` : ' (global)';
        this.confirmRemoveRole(
          user.id,
          role.role_id,
          role.board_id || null,
          `${displayName}: ${role.role_name}${roleScope}`
        );
      });
      chip.appendChild(removeBtn);
    }

    return chip;
  }

  filterUsers(searchTerm) {
    const term = searchTerm.toLowerCase().trim();
    
    let filtered = this.allUsers;
    
    // Filter by active status if toggle is on
    if (this.showActiveOnly) {
      filtered = filtered.filter(user => user.is_active);
    }
    
    // Filter by search term
    if (term !== '') {
      filtered = filtered.filter(user => {
        const displayName = (user.display_name || '').toLowerCase();
        const username = (user.username || '').toLowerCase();
        const email = (user.email || '').toLowerCase();
        
        return displayName.includes(term) || username.includes(term) || email.includes(term);
      });
    }

    this.filteredUsers = filtered;
    this.renderActiveUsers();
  }

  async handleApprove(user) {
    const displayName = user.display_name || user.username || user.email;
    
    this.showConfirmModal(
      'Approve User',
      `Are you sure you want to approve ${displayName}? They will be able to access the system.`,
      async () => {
        console.log('Approving user:', user.id, user.email);
        try {
          const url = `/api/users/${user.id}/approve`;
          console.log('Making POST request to:', url);
          
          const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin'  // Ensure cookies are sent
          });

          console.log('Response status:', response.status);
          console.log('Response headers:', Object.fromEntries(response.headers.entries()));

          const data = await response.json();
          console.log('Response data:', data);

          if (response.ok && data.success) {
            this.showStatus('User approved successfully', 'success');
            await this.loadPendingUsers();
            await this.loadActiveUsers();
          } else {
            // Show specific error message from server
            const errorMsg = data.message || `Failed to approve user (Status: ${response.status})`;
            this.showStatus('Error: ' + errorMsg, 'error');
            console.error('Approve user failed:', { status: response.status, data });
          }
        } catch (error) {
          console.error('Error approving user:', error);
          this.showStatus('Error approving user: ' + error.message, 'error');
        }
      }
    );
  }

  async handleReject(user) {
    const displayName = user.display_name || user.username || user.email;
    
    this.showConfirmModal(
      'Reject User',
      `Are you sure you want to reject ${displayName}? This will permanently delete their account.`,
      async () => {
        try {
          const response = await fetch(`/api/users/${user.id}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
          });

          const data = await response.json();

          if (data.success) {
            this.showStatus('User rejected and removed', 'success');
            await this.loadPendingUsers();
          } else {
            throw new Error(data.message || 'Failed to reject user');
          }
        } catch (error) {
          console.error('Error rejecting user:', error);
          this.showStatus('Error rejecting user: ' + error.message, 'error');
        }
      }
    );
  }

  async handleDeactivate(user) {
    const displayName = user.display_name || user.username || user.email;
    
    this.showConfirmModal(
      'Deactivate User',
      `Are you sure you want to deactivate ${displayName}? They will not be able to log in.`,
      async () => {
        try {
          const response = await fetch(`/api/users/${user.id}/deactivate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
          });

          const data = await response.json();

          if (data.success) {
            this.showStatus('User deactivated successfully', 'success');
            await this.loadActiveUsers();
          } else {
            throw new Error(data.message || 'Failed to deactivate user');
          }
        } catch (error) {
          console.error('Error deactivating user:', error);
          this.showStatus('Error deactivating user: ' + error.message, 'error');
        }
      }
    );
  }

  async handleRevokePasskeys(user) {
    const displayName = user.display_name || user.username || user.email;

    this.showConfirmModal(
      'Revoke Passkeys',
      `Remove all of ${displayName}'s passkeys? They will need to sign in with their password and add passkeys again. ` +
        'Sessions signed in with a passkey end now. To also end password sessions, reset their password.',
      async () => {
        try {
          const response = await fetch(`/api/users/${user.id}/passkeys`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' }
          });

          const data = await response.json();

          if (data.success) {
            this.showStatus(`Removed ${data.removed} passkey(s) for ${displayName}`, 'success');
            await this.loadActiveUsers();
          } else {
            throw new Error(data.message || 'Failed to revoke passkeys');
          }
        } catch (error) {
          console.error('Error revoking passkeys:', error);
          this.showStatus('Error revoking passkeys: ' + error.message, 'error');
        }
      }
    );
  }

  async handleActivate(user) {
    const displayName = user.display_name || user.username || user.email;
    
    this.showConfirmModal(
      'Activate User',
      `Are you sure you want to activate ${displayName}? They will be able to log in again.`,
      async () => {
        try {
          const response = await fetch(`/api/users/${user.id}/activate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
          });

          const data = await response.json();

          if (data.success) {
            this.showStatus('User activated successfully', 'success');
            await this.loadActiveUsers();
          } else {
            throw new Error(data.message || 'Failed to activate user');
          }
        } catch (error) {
          console.error('Error activating user:', error);
          this.showStatus('Error activating user: ' + error.message, 'error');
        }
      }
    );
  }

  showConfirmModal(title, message, callback) {
    console.log('showConfirmModal called', { title, hasCallback: !!callback });
    this.confirmModalTitle.textContent = title;
    this.confirmModalMessage.textContent = message;
    this.pendingCallback = callback;
    
    console.log('Stored callback:', !!this.pendingCallback);
    
    // Remove old listener and add new one
    const newOkBtn = this.confirmOkBtn.cloneNode(true);
    this.confirmOkBtn.parentNode.replaceChild(newOkBtn, this.confirmOkBtn);
    this.confirmOkBtn = newOkBtn;
    
    console.log('Added new event listener to OK button');
    
    this.confirmOkBtn.addEventListener('click', async (e) => {
      console.log('OK button clicked!');
      console.log('pendingCallback exists?', !!this.pendingCallback);
      
      // Store callback locally before closing modal (which clears it)
      const callback = this.pendingCallback;
      
      this.closeConfirmModal();
      
      if (callback) {
        console.log('Executing callback...');
        // Await the callback if it's async
        try {
          await callback();
          console.log('Callback executed successfully');
        } catch (error) {
          console.error('Error in modal callback:', error);
          this.showStatus('Error: ' + error.message, 'error');
        }
      } else {
        console.log('No pending callback to execute');
      }
    });
    
    this.confirmModal.style.display = 'flex';
    setupModalEscapeClose(this.confirmModal, () => this.closeConfirmModal());
    console.log('Modal displayed');
  }

  closeConfirmModal() {
    this.confirmModal.style.display = 'none';
    this.pendingCallback = null;
  }

  showStatus(message, type = 'info') {
    this.statusMessage.textContent = message;
    this.statusMessage.className = 'settings-status ' + type;
    
    setTimeout(() => {
      this.statusMessage.textContent = '';
      this.statusMessage.className = 'settings-status';
    }, 5000);
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  async loadTestUserGuidance() {
    const presence = document.getElementById('test-user-presence');
    const compatibility = document.getElementById('test-user-compatibility');
    const actionNote = document.getElementById('test-user-action-note');
    const statusDiv = document.getElementById('test-user-status');
    const btn = document.getElementById('test-user-btn');
    const btnText = document.getElementById('test-user-btn-text');

    if (!presence || !compatibility || !actionNote || !statusDiv || !btn || !btnText) {
      return;
    }

    if (this.testUserSection) {
      this.testUserSection.style.display = 'block';
    }

    try {
      const response = await fetch('/api/admin/test-user');
      if (!response.ok) {
        throw new Error(`Status check failed (${response.status})`);
      }

      const data = await response.json();
      const detectedUser = data.detected_user;

      this.testUserDetected = Boolean(detectedUser);
      this.canRemoveTestUser = Boolean(data.permissions?.can_remove);

      if (detectedUser) {
        presence.textContent = data.test_user_compatible
          ? 'Known test user detected and matches the current test suite expectations.'
          : 'Known test user detected, but it is not active and approved. Tests may still fail until it is fixed or removed.';

        compatibility.textContent = data.test_user_compatible
          ? 'A clean database also works. Remove this account when testing is complete or when the environment should no longer contain known credentials.'
          : 'A clean database is compatible. On a non-clean database, the known test user must be active and approved to satisfy the current test suite.';
      } else {
        presence.textContent = 'No known test user detected.';
        compatibility.textContent = 'A clean database is already compatible with the tests. If tests must run against an existing database, create the approved administrator account shown above outside this page.';
      }

      if (this.canRemoveTestUser && this.testUserDetected) {
        btn.style.display = 'inline-flex';
        btn.disabled = false;
        btnText.textContent = 'Remove Known Test User';
        actionNote.textContent = 'Removal is available because you have user.manage.';
      } else {
        btn.style.display = 'none';
        actionNote.textContent = this.testUserDetected
          ? 'A user with user.manage should remove this account when it is no longer required.'
          : 'This page no longer creates the known test user.';
      }
    } catch (error) {
      console.error('Error loading test user guidance:', error);
      this.testUserDetected = false;
      btn.style.display = 'none';
      presence.textContent = 'Unable to verify known test user status right now.';
      compatibility.textContent = 'A clean database is still compatible with the tests.';
      actionNote.textContent = 'Retry the page if you need to re-check the known test user.';
      statusDiv.style.display = 'none';
    }
  }

  confirmRemoveKnownTestUser() {
    if (!this.testUserDetected || !this.canRemoveTestUser) {
      return;
    }

    this.showConfirmModal(
      'Remove Known Test User',
      'Are you sure you want to remove the known test user? This page cannot recreate it.',
      async () => {
        await this.removeKnownTestUser();
      }
    );
  }

  async removeKnownTestUser() {
    const btn = document.getElementById('test-user-btn');
    const btnText = document.getElementById('test-user-btn-text');
    const statusDiv = document.getElementById('test-user-status');

    if (!btn || !btnText || !statusDiv) {
      return;
    }

    btn.disabled = true;
    const originalText = btnText.textContent;
    btnText.textContent = 'Processing...';

    try {
      const response = await fetch('/api/admin/test-user', {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json'
        }
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.message || 'Failed to remove known test user');
      }

      statusDiv.style.display = 'block';
      statusDiv.style.background = '#d1fae5';
      statusDiv.style.color = '#065f46';
      statusDiv.innerHTML = '<strong>Known test user removed successfully.</strong>';

      if (data.deleted_current_user) {
        statusDiv.innerHTML = '<strong>Known test user removed successfully.</strong><br>Redirecting to login...';
        setTimeout(() => {
          window.location.href = '/login.html';
        }, 1200);
        return;
      }

      await Promise.all([this.loadTestUserGuidance(), this.loadActiveUsers()]);

      setTimeout(() => {
        statusDiv.style.display = 'none';
      }, 5000);
    } catch (error) {
      console.error('Error removing known test user:', error);
      statusDiv.style.display = 'block';
      statusDiv.style.background = '#fee2e2';
      statusDiv.style.color = '#991b1b';
      statusDiv.textContent = `Error: ${error.message}`;
    } finally {
      btn.disabled = false;
      btnText.textContent = originalText;
    }
  }

  openAddUserModal() {
    // Clear form fields
    this.addUserEmail.value = '';
    this.addUserUsername.value = '';
    this.addUserDisplayName.value = '';
    this.addUserPassword.value = '';
    this.addUserConfirmPassword.value = '';
    this.addUserPasswordStrengthBar.className = 'password-strength-bar';
    this.addUserErrorMessage.style.display = 'none';
    this.addUserErrorMessage.textContent = '';
    
    // Enable submit button
    this.addUserOkBtn.disabled = false;
    
    // Display modal
    this.addUserModal.style.display = 'flex';
    setupModalEscapeClose(this.addUserModal, () => this.closeAddUserModal());
    
    // Focus on first field after modal is visible
    this.addUserEmail.focus();
  }

  closeAddUserModal() {
    this.addUserModal.style.display = 'none';
    this.addUserEmail.value = '';
    this.addUserUsername.value = '';
    this.addUserDisplayName.value = '';
    this.addUserPassword.value = '';
    this.addUserConfirmPassword.value = '';
    this.addUserErrorMessage.style.display = 'none';
    this.addUserErrorMessage.textContent = '';
  }

  updatePasswordStrength() {
    const password = this.addUserPassword.value;
    let strength = 0;

    if (password.length >= 8) strength++;
    if (password.match(/[a-z]/) && password.match(/[A-Z]/)) strength++;
    if (password.match(/\d/)) strength++;
    if (password.match(/[^a-zA-Z\d]/)) strength++;

    this.addUserPasswordStrengthBar.className = 'password-strength-bar';
    if (strength >= 3) {
      this.addUserPasswordStrengthBar.classList.add('strong');
    } else if (strength >= 2) {
      this.addUserPasswordStrengthBar.classList.add('medium');
    } else if (strength >= 1) {
      this.addUserPasswordStrengthBar.classList.add('weak');
    }
  }

  async handleCreateUser() {
    const email = this.addUserEmail.value.trim().toLowerCase();
    const username = this.addUserUsername.value.trim();
    const displayName = this.addUserDisplayName.value.trim();
    const password = this.addUserPassword.value;
    const confirmPassword = this.addUserConfirmPassword.value;

    // Validate inputs
    if (!email || !username || !password) {
      this.showAddUserError('Email, username, and password are required');
      return;
    }

    if (password.length < 8) {
      this.showAddUserError('Password must be at least 8 characters');
      return;
    }

    if (password !== confirmPassword) {
      this.showAddUserError('Passwords do not match');
      return;
    }

    // Validate username format: letters, numbers, underscores, and hyphens only
    const usernameRegex = /^[a-zA-Z0-9_-]+$/;
    if (!usernameRegex.test(username)) {
      this.showAddUserError('Username can only contain letters, numbers, underscores, and hyphens');
      return;
    }

    // Disable button during submission
    this.addUserOkBtn.disabled = true;
    const originalText = this.addUserOkBtn.textContent;
    this.addUserOkBtn.textContent = 'Creating...';

    try {
      // Step 1: Create the user via registration endpoint
      const createResponse = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          email,
          username,
          password,
          display_name: displayName || username
        })
      });

      const createData = await createResponse.json();

      if (!createResponse.ok || !createData.success) {
        throw new Error(createData.message || 'Failed to create user');
      }

      const newUserId = createData.user.id;

      // Step 2: Immediately approve the user
      const approveResponse = await fetch(`/api/users/${newUserId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin'
      });

      const approveData = await approveResponse.json();

      if (!approveResponse.ok || !approveData.success) {
        // User was created but approval failed - provide specific feedback
        console.error('User created but approval failed:', approveData);
        this.showAddUserError('User was created but approval failed. Please approve the account from the Pending Approval list.');
        this.closeAddUserModal();
        // Reload pending users to show the newly created user
        if (typeof this.loadPendingUsers === 'function') {
          await this.loadPendingUsers();
        }
        return;
      }

      // Success! Close modal and refresh user list
      this.showStatus(`User ${username} created and approved successfully`, 'success');
      this.closeAddUserModal();
      
      // Refresh the active users list
      await this.loadActiveUsers();

    } catch (error) {
      console.error('Error creating user:', error);
      this.showAddUserError(error.message);
    } finally {
      this.addUserOkBtn.disabled = false;
      this.addUserOkBtn.textContent = originalText;
    }
  }

  showAddUserError(message) {
    this.addUserErrorMessage.textContent = message;
    this.addUserErrorMessage.style.display = 'block';
  }

  openResetPasswordModal(user) {
    if (!this.canResetPasswords) {
      this.showStatus('Only administrators can reset other users\' passwords.', 'error');
      return;
    }

    this.selectedResetUser = user;
    this.resetPasswordNew.value = '';
    this.resetPasswordConfirm.value = '';
    this.resetPasswordErrorMessage.style.display = 'none';
    this.resetPasswordErrorMessage.textContent = '';
    this.resetPasswordOkBtn.disabled = false;

    const displayName = user.display_name || user.username || user.email;
    this.resetPasswordUserName.textContent = `Reset password for ${displayName}`;

    this.resetPasswordModal.style.display = 'flex';
    setupModalEscapeClose(this.resetPasswordModal, () => this.closeResetPasswordModal());
    this.resetPasswordNew.focus();
  }

  closeResetPasswordModal() {
    if (this.resetPasswordModal) {
      this.resetPasswordModal.style.display = 'none';
    }
    this.selectedResetUser = null;
    this.resetPasswordNew.value = '';
    this.resetPasswordConfirm.value = '';
    this.resetPasswordErrorMessage.style.display = 'none';
    this.resetPasswordErrorMessage.textContent = '';
  }

  showResetPasswordError(message) {
    this.resetPasswordErrorMessage.textContent = message;
    this.resetPasswordErrorMessage.style.display = 'block';
  }

  async handleResetPassword() {
    if (!this.selectedResetUser) {
      this.showResetPasswordError('No user selected for password reset.');
      return;
    }

    const newPassword = this.resetPasswordNew.value;
    const confirmPassword = this.resetPasswordConfirm.value;

    if (!newPassword) {
      this.showResetPasswordError('New password is required.');
      return;
    }

    if (newPassword.length < 8) {
      this.showResetPasswordError('Password must be at least 8 characters.');
      return;
    }

    if (newPassword !== confirmPassword) {
      this.showResetPasswordError('Passwords do not match.');
      return;
    }

    const displayName = this.selectedResetUser.display_name || this.selectedResetUser.username || this.selectedResetUser.email;

    this.resetPasswordOkBtn.disabled = true;
    const originalText = this.resetPasswordOkBtn.textContent;
    this.resetPasswordOkBtn.textContent = 'Resetting...';

    try {
      const response = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          user_id: this.selectedResetUser.id,
          new_password: newPassword
        })
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.message || 'Failed to reset password');
      }

      this.showStatus(`Password reset for ${displayName}`, 'success');
      this.closeResetPasswordModal();
    } catch (error) {
      console.error('Error resetting password:', error);
      this.showResetPasswordError(error.message);
    } finally {
      this.resetPasswordOkBtn.disabled = false;
      this.resetPasswordOkBtn.textContent = originalText;
    }
  }

  // Role assignment methods
  async loadRoles() {
    try {
      // Use /my-roles endpoint which filters based on user's permissions
      const response = await fetch('/api/roles/my-roles');
      
      if (response.status === 403) {
        console.warn('Permission denied loading roles');
        return;
      }
      
      const data = await response.json();

      if (data.success && data.roles) {
        this.roles = data.roles;
        this.canAssignAllRoles = data.can_assign_all || false;
      }
    } catch (error) {
      console.error('Error loading roles:', error);
    }
  }

  async loadBoards() {
    try {
      const response = await fetch('/api/roles/boards');
      
      if (response.status === 403) {
        console.warn('Permission denied loading boards');
        return;
      }
      
      const data = await response.json();

      if (data.success && data.boards) {
        this.boards = data.boards;
      }
    } catch (error) {
      console.error('Error loading boards:', error);
    }
  }

  async loadPermissionModel() {
    if (!this.permissionModelLoading || !this.permissionModelContent) {
      return; // Elements don't exist
    }

    try {
      this.permissionModelLoading.style.display = 'block';
      this.permissionModelContent.style.display = 'none';

      const response = await fetch('/api/roles/permission-model');
      const data = await response.json();

      if (data.success && data.model) {
        this.renderPermissionModel(data.model);
        this.permissionModelLoading.style.display = 'none';
        this.permissionModelContent.style.display = 'block';
      }
    } catch (error) {
      console.error('Error loading permission model:', error);
      this.permissionModelLoading.innerHTML = '<div class="empty-message">Failed to load permission model.</div>';
    }
  }

  renderPermissionModel(model) {
    const container = this.permissionModelContent;
    
    let html = '';
    
    // Overview
    if (model.overview) {
      html += `<div class="permission-section">`;
      html += `<h4>${this.escapeHtml(model.overview.title)}</h4>`;
      html += `<p>${this.escapeHtml(model.overview.description)}</p>`;
      html += `</div>`;
    }
    
    // Concepts
    if (model.concepts && model.concepts.length > 0) {
      html += `<div class="permission-section">`;
      html += `<h4>Key Concepts</h4>`;
      model.concepts.forEach(concept => {
        html += `<div class="permission-concept">`;
        html += `<h5>${this.escapeHtml(concept.title)}</h5>`;
        html += `<ul>`;
        concept.points.forEach(point => {
          html += `<li>${this.escapeHtml(point)}</li>`;
        });
        html += `</ul>`;
        html += `</div>`;
      });
      html += `</div>`;
    }
    
    // Roles
    if (model.roles) {
      html += `<div class="permission-section">`;
      html += `<h4>Available Roles</h4>`;
      
      if (model.roles.global && model.roles.global.length > 0) {
        html += `<h5>Global Roles (Assigned System-Wide)</h5>`;
        html += `<div class="roles-grid">`;
        model.roles.global.forEach(role => {
          html += `<div class="role-card">`;
          html += `<div class="role-name">${this.escapeHtml(role.name)}</div>`;
          html += `<div class="role-description">${this.escapeHtml(role.description)}</div>`;
          html += `<div class="role-use-case"><strong>Use Case:</strong> ${this.escapeHtml(role.use_case)}</div>`;
          html += `</div>`;
        });
        html += `</div>`;
      }
      
      if (model.roles.board_specific && model.roles.board_specific.length > 0) {
        html += `<h5>Board-Specific Roles (Assigned Per Board)</h5>`;
        html += `<div class="roles-grid">`;
        model.roles.board_specific.forEach(role => {
          html += `<div class="role-card">`;
          html += `<div class="role-name">${this.escapeHtml(role.name)}</div>`;
          html += `<div class="role-description">${this.escapeHtml(role.description)}</div>`;
          html += `<div class="role-use-case"><strong>Use Case:</strong> ${this.escapeHtml(role.use_case)}</div>`;
          html += `</div>`;
        });
        html += `</div>`;
      }
      
      html += `</div>`;
    }
    
    // Examples
    if (model.examples && model.examples.length > 0) {
      html += `<div class="permission-section">`;
      html += `<h4>Examples</h4>`;
      model.examples.forEach((example, index) => {
        html += `<div class="permission-example">`;
        html += `<h5>${index + 1}. ${this.escapeHtml(example.title)}</h5>`;
        html += `<p><em>${this.escapeHtml(example.scenario)}</em></p>`;
        html += `<ul>`;
        example.details.forEach(detail => {
          html += `<li>${this.escapeHtml(detail)}</li>`;
        });
        html += `</ul>`;
        html += `</div>`;
      });
      html += `</div>`;
    }
    
    // Assignment Rules
    if (model.assignment_rules && model.assignment_rules.length > 0) {
      html += `<div class="permission-section">`;
      html += `<h4>Role Assignment Rules</h4>`;
      html += `<ul class="rules-list">`;
      model.assignment_rules.forEach(rule => {
        html += `<li>${this.escapeHtml(rule)}</li>`;
      });
      html += `</ul>`;
      html += `</div>`;
    }
    
    // Summary
    if (model.summary && model.summary.length > 0) {
      html += `<div class="permission-section summary-section">`;
      html += `<h4>Summary</h4>`;
      html += `<ul class="summary-list">`;
      model.summary.forEach(point => {
        html += `<li>${this.escapeHtml(point)}</li>`;
      });
      html += `</ul>`;
      html += `</div>`;
    }
    
    container.innerHTML = html;
  }

  openAddRoleModal(userId, username) {
    this.currentUserId = userId;
    this.addRoleUserName.textContent = `Assign role to: ${username}`;
    
    // Populate roles dropdown
    this.roleSelect.innerHTML = '<option value="">Select a role...</option>';
    this.roles.forEach(role => {
      const option = document.createElement('option');
      option.value = role.id;
      option.textContent = role.name;
      // Store role metadata
      option.dataset.boardSpecificOnly = role.board_specific_only || false;
      option.dataset.globalOnly = role.global_only || false;
      this.roleSelect.appendChild(option);
    });

    // Populate boards dropdown (initially with global option)
    this.boardSelect.innerHTML = '<option value="">Global (All Boards)</option>';
    this.boards.forEach(board => {
      const option = document.createElement('option');
      option.value = board.id;
      option.textContent = board.name;
      this.boardSelect.appendChild(option);
    });
    
    // Show/hide restriction note based on whether user can assign all roles
    const modalRestrictionNote = document.getElementById('modal-role-restriction-note');
    if (modalRestrictionNote) {
      modalRestrictionNote.style.display = this.canAssignAllRoles ? 'none' : 'block';
    }

    this.addRoleModal.style.display = 'flex';
    setupModalEscapeClose(this.addRoleModal, () => this.closeAddRoleModal());
  }
  
  handleRoleSelectChange() {
    const selectedOption = this.roleSelect.options[this.roleSelect.selectedIndex];
    if (!selectedOption || !selectedOption.value) return;
    
    const isBoardSpecificOnly = selectedOption.dataset.boardSpecificOnly === 'true';
    const isGlobalOnly = selectedOption.dataset.globalOnly === 'true';
    
    // Clear and rebuild board select based on role type
    if (isBoardSpecificOnly) {
      // Board-specific role: Remove "Global" option, force board selection
      this.boardSelect.innerHTML = '<option value="">Select a board...</option>';
      this.boards.forEach(board => {
        const option = document.createElement('option');
        option.value = board.id;
        option.textContent = board.name;
        this.boardSelect.appendChild(option);
      });
      this.boardSelect.disabled = false;
      this.boardSelect.required = true;
    } else if (isGlobalOnly) {
      // Global-only role: Show only "Global" option and disable select
      this.boardSelect.innerHTML = '<option value="">Global (All Boards)</option>';
      this.boardSelect.disabled = true;
      this.boardSelect.value = '';
    } else {
      // Other roles: Allow both global and board-specific
      this.boardSelect.innerHTML = '<option value="">Global (All Boards)</option>';
      this.boards.forEach(board => {
        const option = document.createElement('option');
        option.value = board.id;
        option.textContent = board.name;
        this.boardSelect.appendChild(option);
      });
      this.boardSelect.disabled = false;
      this.boardSelect.required = false;
    }
  }

  closeAddRoleModal() {
    this.addRoleModal.style.display = 'none';
    this.currentUserId = null;
    this.roleSelect.value = '';
    this.boardSelect.value = '';
  }

  async handleAddRole() {
    const roleId = parseInt(this.roleSelect.value);
    const boardId = this.boardSelect.value ? parseInt(this.boardSelect.value) : null;

    if (!roleId) {
      this.showStatus('Please select a role', 'error');
      return;
    }

    // Additional safety check - prevent modifying own roles
    if (window.currentUser && this.currentUserId === window.currentUser.id) {
      this.showStatus('You cannot modify your own roles', 'error');
      this.closeAddRoleModal();
      return;
    }

    try {
      const response = await fetch('/api/roles/assign', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          user_id: this.currentUserId,
          role_id: roleId,
          board_id: boardId
        })
      });

      const data = await response.json();

      if (data.success) {
        this.showStatus(data.message || 'Role assigned successfully', 'success');
        this.closeAddRoleModal();
        await this.loadActiveUsers();
      } else {
        throw new Error(data.message || 'Failed to assign role');
      }
    } catch (error) {
      console.error('Error assigning role:', error);
      this.showStatus('Error: ' + error.message, 'error');
    }
  }

  confirmRemoveRole(userId, roleId, boardId, roleDescription) {
    this.confirmModalTitle.textContent = 'Confirm Role Removal';
    this.confirmModalMessage.textContent = `Are you sure you want to remove the role: ${roleDescription}?`;
    
    // Store callback locally before setting up OK button
    const callback = async () => {
      await this.removeRole(userId, roleId, boardId);
    };
    
    this.pendingCallback = callback;

    // Remove old listener and add new one
    const newOkBtn = this.confirmOkBtn.cloneNode(true);
    this.confirmOkBtn.parentNode.replaceChild(newOkBtn, this.confirmOkBtn);
    this.confirmOkBtn = newOkBtn;
    
    this.confirmOkBtn.addEventListener('click', async () => {
      const cb = this.pendingCallback;
      this.closeConfirmModal();
      if (cb) {
        try {
          await cb();
        } catch (error) {
          console.error('Error in confirm callback:', error);
          this.showStatus('Error: ' + error.message, 'error');
        }
      }
    });
    
    this.confirmModal.style.display = 'flex';
    setupModalEscapeClose(this.confirmModal, () => this.closeConfirmModal());
  }

  async removeRole(userId, roleId, boardId) {
    // Additional safety check - prevent modifying own roles
    if (window.currentUser && userId === window.currentUser.id) {
      this.showStatus('You cannot modify your own roles', 'error');
      return;
    }

    try {
      const response = await fetch('/api/roles/remove', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          user_id: userId,
          role_id: roleId,
          board_id: boardId
        })
      });

      const data = await response.json();

      if (data.success) {
        this.showStatus(data.message || 'Role removed successfully', 'success');
        await this.loadActiveUsers();
      } else {
        throw new Error(data.message || 'Failed to remove role');
      }
    } catch (error) {
      console.error('Error removing role:', error);
      this.showStatus('Error: ' + error.message, 'error');
    }
  }
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', async () => {
  // Wait for header to load and user info to be available
  // The header.js sets window.userDataReady flag when done
  let attempts = 0;
  while (!window.userDataReady && attempts < 50) {
    await new Promise(resolve => setTimeout(resolve, 100)); // Wait 100ms
    attempts++;
  }
  
  const userManagement = new UserManagement();
  await userManagement.init();
});
