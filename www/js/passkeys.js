/**
 * Passkey (WebAuthn) helpers shared by the login and profile pages.
 *
 * The server sends WebAuthn options as JSON with binary values base64url
 * encoded, and expects credentials back in the same form. These helpers do
 * that conversion around navigator.credentials.create() and .get().
 */
(function() {
  const REQUEST_TIMEOUT_MS = 15000;

  function base64urlToBuffer(value) {
    const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (value.length % 4)) % 4);
    const binary = atob(padded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
  }

  function bufferToBase64url(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function toDescriptors(list) {
    return (list || []).map((item) => ({ ...item, id: base64urlToBuffer(item.id) }));
  }

  function toCreationOptions(json) {
    return {
      ...json,
      challenge: base64urlToBuffer(json.challenge),
      user: { ...json.user, id: base64urlToBuffer(json.user.id) },
      excludeCredentials: toDescriptors(json.excludeCredentials)
    };
  }

  function toRequestOptions(json) {
    return {
      ...json,
      challenge: base64urlToBuffer(json.challenge),
      allowCredentials: toDescriptors(json.allowCredentials)
    };
  }

  function credentialToJSON(credential) {
    const response = credential.response;
    const json = {
      id: credential.id,
      rawId: bufferToBase64url(credential.rawId),
      type: credential.type,
      response: { clientDataJSON: bufferToBase64url(response.clientDataJSON) },
      clientExtensionResults: {}
    };
    if (credential.authenticatorAttachment) {
      json.authenticatorAttachment = credential.authenticatorAttachment;
    }
    if (response.attestationObject) {
      json.response.attestationObject = bufferToBase64url(response.attestationObject);
      if (typeof response.getTransports === 'function') {
        json.response.transports = response.getTransports();
      }
    }
    if (response.authenticatorData) {
      json.response.authenticatorData = bufferToBase64url(response.authenticatorData);
      json.response.signature = bufferToBase64url(response.signature);
      if (response.userHandle) {
        json.response.userHandle = bufferToBase64url(response.userHandle);
      }
    }
    return json;
  }

  async function postJSON(url, body) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body || {}),
        signal: controller.signal
      });
      let data = {};
      try {
        data = await response.json();
      } catch (e) {
        // Non-JSON error page; fall through with an empty body.
      }
      if (!response.ok || !data.success) {
        const error = new Error(data.message || 'Request failed. Please try again.');
        error.status = response.status;
        throw error;
      }
      return data;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  let statusPromise = null;

  const Passkeys = {
    /** True when this browser and connection can use passkeys. */
    isSupported() {
      return Boolean(window.isSecureContext && window.PublicKeyCredential && navigator.credentials);
    },

    /** True when the server has passkeys turned on. Cached per page load. */
    isEnabled() {
      if (!statusPromise) {
        statusPromise = fetch('/api/auth/passkeys/status', { credentials: 'include' })
          .then((response) => (response.ok ? response.json() : { enabled: false }))
          .then((data) => data.enabled === true)
          .catch(() => false);
      }
      return statusPromise;
    },

    /** True when the browser can offer passkeys in username autofill. */
    async isAutofillAvailable() {
      try {
        return Boolean(
          window.PublicKeyCredential &&
          typeof PublicKeyCredential.isConditionalMediationAvailable === 'function' &&
          await PublicKeyCredential.isConditionalMediationAvailable()
        );
      } catch (e) {
        return false;
      }
    },

    /**
     * Add a passkey to the signed-in account.
     * @returns {Promise<object>} The new passkey as returned by the server.
     */
    async register(password, name) {
      const { options } = await postJSON('/api/auth/passkeys/register/options', { password });
      const credential = await navigator.credentials.create({ publicKey: toCreationOptions(options) });
      const body = { credential: credentialToJSON(credential) };
      if (name) {
        body.name = name;
      }
      const data = await postJSON('/api/auth/passkeys/register/verify', body);
      return data.passkey;
    },

    /**
     * Sign in with a passkey.
     * @param {object} opts
     * @param {boolean} opts.autofill - Offer passkeys in username autofill instead of a dialog.
     * @param {AbortSignal} opts.signal - Cancels the browser prompt.
     * @param {function(): boolean} opts.rememberMe - Read when the passkey is chosen.
     * @returns {Promise<object>} The login response (same shape as password login).
     */
    async signIn({ autofill = false, signal, rememberMe = () => false } = {}) {
      const { options } = await postJSON('/api/auth/passkeys/login/options');
      const request = { publicKey: toRequestOptions(options), signal };
      if (autofill) {
        request.mediation = 'conditional';
      }
      const credential = await navigator.credentials.get(request);
      return postJSON('/api/auth/passkeys/login/verify', {
        credential: credentialToJSON(credential),
        remember_me: rememberMe()
      });
    },

    /** True for errors that mean the user dismissed or aborted the browser prompt. */
    isCancelled(error) {
      return Boolean(error) && (error.name === 'NotAllowedError' || error.name === 'AbortError');
    },

    /** A short, user-facing message for a passkey error. */
    describeError(error) {
      if (!error) {
        return 'Something went wrong. Please try again.';
      }
      if (error.name === 'NotAllowedError') {
        return 'The passkey request was cancelled or timed out.';
      }
      if (error.name === 'InvalidStateError') {
        return 'This device already has a passkey for your account.';
      }
      if (error.name === 'SecurityError') {
        return 'Passkeys are not set up for this web address. Ask your administrator to check the passkey settings.';
      }
      if (error.name === 'AbortError') {
        return 'The request timed out. Please check your connection and try again.';
      }
      if (typeof error.status === 'number') {
        return error.message;
      }
      return 'Something went wrong with the passkey. Please try again.';
    }
  };

  window.Passkeys = Passkeys;
})();
