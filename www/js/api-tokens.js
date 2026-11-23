// Personal API token dialogs (#714), shared by the Profile and User Management pages.
// The dialogs are built from DOM nodes on first use, so token names never go
// through innerHTML.
(function () {
  const EXPIRY_CHOICES = [
    { value: '30', label: '30 days' },
    { value: '90', label: '90 days' },
    { value: '365', label: '1 year' },
    { value: '', label: 'Never' }
  ];

  let idCounter = 0;

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    Object.entries(props).forEach(([key, value]) => {
      if (key === 'className') {
        node.className = value;
      } else if (key === 'text') {
        node.textContent = value;
      } else {
        node.setAttribute(key, value);
      }
    });
    children.forEach((child) => node.appendChild(child));
    return node;
  }

  function field(labelText, input, helpText) {
    const group = el('div', { className: 'api-token-field' });
    group.appendChild(el('label', { for: input.id, text: labelText }));
    if (helpText) {
      const helpId = `${input.id}-help`;
      group.appendChild(el('p', { className: 'api-token-help', id: helpId, text: helpText }));
      input.setAttribute('aria-describedby', helpId);
    }
    group.appendChild(input);
    return group;
  }

  async function requestJson(method, url, body) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);
    try {
      const options = {
        method,
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal
      };
      if (body !== undefined) {
        options.body = JSON.stringify(body);
      }
      const response = await fetch(url, options);
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

  // Shows a modal-app dialog and returns a close function. Focus goes back to
  // whatever had it when the dialog opened.
  function openDialog(modal, focusEl, onClose) {
    const returnFocusTo = document.activeElement;
    document.body.appendChild(modal);
    let closed = false;
    const close = () => {
      if (closed) {
        return;
      }
      closed = true;
      if (typeof cleanupEscape === 'function') {
        cleanupEscape();
      }
      modal.remove();
      if (returnFocusTo && document.body.contains(returnFocusTo)) {
        returnFocusTo.focus();
      }
      if (onClose) {
        onClose();
      }
    };
    const cleanupEscape = setupModalEscapeClose(modal, close);
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        close();
      }
    });
    modal.classList.add('show');
    focusEl.focus();
    return close;
  }

  /**
   * Show a new token once, with a copy button.
   * @param {string} token The token value from the create response.
   * @param {Function} [onClose] Called when the dialog closes.
   */
  function showCreatedToken(token, onClose) {
    const titleId = `api-token-shown-title-${++idCounter}`;
    const descId = `api-token-shown-desc-${idCounter}`;
    const tokenId = `api-token-shown-value-${idCounter}`;

    const tokenInput = el('input', {
      type: 'text',
      id: tokenId,
      className: 'api-token-input api-token-value',
      readonly: 'readonly',
      spellcheck: 'false',
      autocomplete: 'off',
      'aria-label': 'API token'
    });
    tokenInput.value = token;
    tokenInput.addEventListener('focus', () => tokenInput.select());

    const copyStatus = el('div', { className: 'api-token-status', role: 'status', 'aria-live': 'polite' });
    const copyBtn = el('button', { type: 'button', className: 'btn btn-secondary', text: 'Copy' });
    const doneBtn = el('button', { type: 'button', className: 'btn btn-primary', text: 'Done' });

    const modal = el('div', {
      className: 'modal-app api-token-dialog',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-labelledby': titleId,
      'aria-describedby': descId
    }, [
      el('div', { className: 'modal-content' }, [
        el('div', { className: 'modal-header' }, [el('h2', { id: titleId, text: 'API token created' })]),
        el('div', { className: 'modal-body' }, [
          el('p', {
            id: descId,
            text: 'Copy this token now and keep it somewhere safe. It won\'t be shown again. ' +
              'Send it in the Authorization header as "Bearer <token>".'
          }),
          tokenInput,
          copyStatus
        ]),
        el('div', { className: 'modal-actions' }, [copyBtn, doneBtn])
      ])
    ]);

    copyBtn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(token);
        copyStatus.textContent = 'Copied';
      } catch (error) {
        tokenInput.focus();
        tokenInput.select();
        copyStatus.textContent = 'Couldn\'t copy. The token is selected: copy it with your keyboard.';
      }
    });

    const close = openDialog(modal, tokenInput, onClose);
    doneBtn.addEventListener('click', close);
  }

  /**
   * Open the dialog that creates a token, then show the new token.
   * @param {Object} options
   * @param {string} options.url Endpoint to POST to.
   * @param {string} [options.title] Dialog title.
   * @param {string} [options.description] Text under the title.
   * @param {boolean} [options.askPassword] Ask for the current password.
   * @param {Function} [options.onCreated] Called with the create response.
   */
  function openCreateDialog(options) {
    const n = ++idCounter;
    const titleId = `api-token-create-title-${n}`;

    const nameInput = el('input', {
      type: 'text',
      id: `api-token-name-${n}`,
      className: 'api-token-input',
      maxlength: '100',
      required: 'required',
      'aria-required': 'true',
      autocomplete: 'off'
    });
    const accessSelect = el('select', { id: `api-token-access-${n}`, className: 'api-token-input' }, [
      el('option', { value: 'write', text: 'Read and write' }),
      el('option', { value: 'read', text: 'Read only' })
    ]);
    const expirySelect = el('select', { id: `api-token-expiry-${n}`, className: 'api-token-input' },
      EXPIRY_CHOICES.map((choice) => el('option', { value: choice.value, text: choice.label })));
    expirySelect.value = '90';
    const passwordInput = options.askPassword
      ? el('input', {
        type: 'password',
        id: `api-token-password-${n}`,
        className: 'api-token-input',
        autocomplete: 'current-password',
        required: 'required',
        'aria-required': 'true'
      })
      : null;

    const error = el('div', { className: 'api-token-error', role: 'alert' });
    const cancelBtn = el('button', { type: 'button', className: 'btn btn-secondary', text: 'Cancel' });
    const createBtn = el('button', { type: 'submit', className: 'btn btn-primary', text: 'Create token' });

    const bodyChildren = [];
    if (options.description) {
      bodyChildren.push(el('p', { text: options.description }));
    }
    bodyChildren.push(
      error,
      field('Name', nameInput, 'What uses this token, for example "Backup script".'),
      field('Access', accessSelect, 'A read-only token can look but not change anything.'),
      field('Expires', expirySelect)
    );
    if (passwordInput) {
      bodyChildren.push(field('Current Password', passwordInput));
    }

    const form = el('form', { novalidate: 'novalidate' }, [
      el('div', { className: 'modal-body' }, bodyChildren),
      el('div', { className: 'modal-actions' }, [cancelBtn, createBtn])
    ]);

    const modal = el('div', {
      className: 'modal-app api-token-dialog',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-labelledby': titleId
    }, [
      el('div', { className: 'modal-content' }, [
        el('div', { className: 'modal-header' }, [
          el('h2', { id: titleId, text: options.title || 'Create API token' })
        ]),
        form
      ])
    ]);

    const close = openDialog(modal, nameInput);
    cancelBtn.addEventListener('click', close);

    const showError = (message) => {
      error.textContent = message;
      error.classList.add('show');
    };

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = nameInput.value.trim();
      if (!name) {
        showError('Enter a name.');
        nameInput.focus();
        return;
      }
      if (passwordInput && !passwordInput.value) {
        showError('Enter your current password.');
        passwordInput.focus();
        return;
      }

      const body = {
        name,
        read_only: accessSelect.value === 'read',
        expires_in_days: expirySelect.value ? Number(expirySelect.value) : null
      };
      if (passwordInput) {
        body.password = passwordInput.value;
      }

      const controls = modal.querySelectorAll('button, input, select');
      controls.forEach((control) => { control.disabled = true; });
      error.classList.remove('show');
      try {
        const data = await requestJson('POST', options.url, body);
        close();
        showCreatedToken(data.token);
        if (options.onCreated) {
          options.onCreated(data);
        }
      } catch (err) {
        console.error('Error creating API token:', err);
        controls.forEach((control) => { control.disabled = false; });
        showError(err.message);
      }
    });
  }

  function formatDate(value) {
    return value ? new Date(value).toLocaleDateString() : null;
  }

  function describeToken(token) {
    const created = formatDate(token.created_at) || 'Unknown';
    const used = formatDate(token.last_used_at) || 'Never';
    const expires = token.expires_at
      ? `${token.expired ? 'Expired' : 'Expires'} ${formatDate(token.expires_at)}`
      : 'Never expires';
    return `Created ${created} · Last used ${used} · ${expires}`;
  }

  /**
   * Open the admin dialog that lists one account's tokens and revokes them
   * one at a time, or all together.
   * @param {Object} options
   * @param {number} options.userId Account whose tokens to manage.
   * @param {string} options.displayName Shown in the title.
   * @param {Function} [options.onClose] Called on close with true if anything was revoked.
   */
  function openManageDialog(options) {
    const n = ++idCounter;
    const titleId = `api-token-manage-title-${n}`;
    const baseUrl = `/api/users/${encodeURIComponent(options.userId)}/tokens`;
    let changed = false;

    const list = el('ul', { className: 'api-token-manage-list', 'aria-labelledby': titleId });
    const empty = el('p', { className: 'api-token-manage-empty', text: 'This account has no API tokens.' });
    empty.hidden = true;
    const error = el('div', { className: 'api-token-error', role: 'alert' });
    const status = el('div', { className: 'api-token-status', role: 'status', 'aria-live': 'polite' });
    const revokeAllBtn = el('button', { type: 'button', className: 'btn btn-danger', text: 'Revoke all' });
    revokeAllBtn.hidden = true;
    const closeBtn = el('button', { type: 'button', className: 'btn btn-primary', text: 'Close' });

    const modal = el('div', {
      className: 'modal-app api-token-dialog api-token-manage-dialog',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-labelledby': titleId
    }, [
      el('div', { className: 'modal-content' }, [
        el('div', { className: 'modal-header' }, [
          el('h2', { id: titleId, text: `API tokens for ${options.displayName}` })
        ]),
        el('div', { className: 'modal-body' }, [
          el('p', {
            text: 'Revoking a token stops anything using it straight away. ' +
              'The account\'s other tokens keep working.'
          }),
          error,
          list,
          empty,
          status
        ]),
        el('div', { className: 'modal-actions' }, [revokeAllBtn, closeBtn])
      ])
    ]);

    const showError = (message) => {
      error.textContent = message;
      error.classList.add('show');
    };

    // Revoking takes a second click on the same button, rather than another
    // dialog stacked on top of this one.
    const armButton = (button, armedText, armedLabel, action) => {
      const idleText = button.textContent;
      const idleLabel = button.getAttribute('aria-label');
      let armed = false;
      let timer = null;
      const reset = () => {
        armed = false;
        clearTimeout(timer);
        button.textContent = idleText;
        if (idleLabel) {
          button.setAttribute('aria-label', idleLabel);
        } else {
          button.removeAttribute('aria-label');
        }
      };
      button.addEventListener('click', async () => {
        if (!armed) {
          armed = true;
          button.textContent = armedText;
          button.setAttribute('aria-label', armedLabel);
          status.textContent = 'Click again to confirm.';
          timer = setTimeout(reset, 5000);
          return;
        }
        reset();
        button.disabled = true;
        error.classList.remove('show');
        try {
          await action();
        } catch (err) {
          console.error('Error revoking API token:', err);
          showError(err.message);
          button.disabled = false;
        }
      });
      button.addEventListener('blur', () => {
        if (armed) {
          reset();
        }
      });
    };

    let load = null;

    const render = (tokens) => {
      list.replaceChildren();
      empty.hidden = tokens.length > 0;
      revokeAllBtn.hidden = tokens.length < 2;

      tokens.forEach((token) => {
        const name = el('div', { className: 'api-token-manage-name', text: token.name });
        const badges = [];
        if (token.read_only) {
          badges.push('Read only');
        }
        if (token.expired) {
          badges.push('Expired');
        }
        badges.forEach((text) => name.appendChild(el('span', { className: 'api-token-manage-badge', text })));

        const meta = el('div', { className: 'api-token-manage-meta' }, [
          el('span', { className: 'api-token-manage-prefix', text: `${token.prefix}…` })
        ]);
        meta.append(` · ${describeToken(token)}`);

        const revokeBtn = el('button', {
          type: 'button',
          className: 'btn btn-danger btn-sm',
          text: 'Revoke',
          'aria-label': `Revoke API token ${token.name}`
        });
        armButton(revokeBtn, 'Confirm', `Confirm revoking API token ${token.name}`, async () => {
          await requestJson('DELETE', `${baseUrl}/${encodeURIComponent(token.id)}`);
          changed = true;
          await load();
          status.textContent = `Revoked "${token.name}"`;
          closeBtn.focus();
        });

        const item = el('li', { className: 'api-token-manage-item' }, [
          el('div', { className: 'api-token-manage-info' }, [name, meta]),
          revokeBtn
        ]);
        item.dataset.tokenId = token.id;
        list.appendChild(item);
      });
    };

    load = async () => {
      const data = await requestJson('GET', baseUrl);
      render(data.tokens || []);
    };

    armButton(revokeAllBtn, 'Confirm revoke all', 'Confirm revoking all API tokens', async () => {
      const data = await requestJson('DELETE', baseUrl);
      changed = true;
      await load();
      status.textContent = `Revoked ${data.removed} API token(s)`;
      closeBtn.focus();
    });

    const close = openDialog(modal, closeBtn, () => {
      if (options.onClose) {
        options.onClose(changed);
      }
    });
    closeBtn.addEventListener('click', close);

    load().catch((err) => {
      console.error('Error loading API tokens:', err);
      showError(`Could not load API tokens: ${err.message}`);
    });
  }

  window.ApiTokens = { openCreateDialog, openManageDialog, showCreatedToken };
})();
