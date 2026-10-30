/**
 * Login page functionality
 */

const form = document.getElementById('loginForm');
const errorMessage = document.getElementById('errorMessage');
const loginButton = document.getElementById('loginButton');
let loginFlowInProgress = false;
const createTimeoutController = window.NetworkTimeoutUtils?.createTimeoutController ||
    ((baseTimeoutMs = 5000) => {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), baseTimeoutMs);
        return { controller, timeoutId, timeoutMs: baseTimeoutMs };
    });

function isSafeRelativePath(path) {
    return typeof path === 'string' && path.startsWith('/') && !path.startsWith('//');
}

// Default "Remember me" to checked when launched as an installed PWA -
// staying logged in between launches is the point of a home-screen app,
// unlike the shared web login page, where session-only is a sensible
// default (e.g. a public/shared computer). No-op in a normal browser tab.
// Still overridable - this only sets the initial state.
if (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true) {
    document.getElementById('rememberMe').checked = true;
}

// Support login links that pass ?redirect=... while preserving existing
// sessionStorage redirect flow used elsewhere in the app.
(function hydrateRedirectFromQuery() {
    try {
        const params = new URLSearchParams(window.location.search);
        const redirectParam = params.get('redirect');
        if (isSafeRelativePath(redirectParam)) {
            sessionStorage.setItem('redirectAfterLogin', redirectParam);
        }
    } catch (error) {
        console.warn('Unable to parse login redirect query parameter:', error);
    }
})();

// Cache the user from a successful login response and leave the login page.
function completeLogin(data) {
    // The login response includes permissions
    if (data.user) {
        sessionStorage.setItem('currentUser', JSON.stringify(data.user));
    }

    // Check if there's a redirect URL stored (from before logout)
    const redirectUrl = sessionStorage.getItem('redirectAfterLogin');
    sessionStorage.removeItem('redirectAfterLogin'); // Clean up

    // Validate redirect URL to prevent open redirect attacks
    // Only allow relative paths (no external URLs)
    let targetUrl = '/';
    if (isSafeRelativePath(redirectUrl)) {
        targetUrl = redirectUrl;
    }

    // Redirect to stored page or default to main app
    window.location.href = targetUrl;
}

function showLoginError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.add('show');
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    loginFlowInProgress = true;

    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const rememberMe = document.getElementById('rememberMe').checked;

    // Disable form
    loginButton.disabled = true;
    loginButton.innerHTML = '<span class="loading"></span>Signing in...';
    errorMessage.classList.remove('show');

    let requestTimeoutMs = 5000;

    let timeoutId;
    try {
        const { controller, timeoutId: requestTimeoutId, timeoutMs } = createTimeoutController();
        timeoutId = requestTimeoutId;
        requestTimeoutMs = timeoutMs;
        
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ email, password, remember_me: rememberMe }),
            signal: controller.signal
        });

        const data = await response.json();

        if (response.ok && data.success) {
            completeLogin(data);
        } else {
            // Show error
            errorMessage.textContent = data.message || 'Login failed. Please try again.';
            errorMessage.classList.add('show');
            
            // Re-enable form
            loginButton.disabled = false;
            loginButton.textContent = 'Sign In';
        }
    } catch (error) {
        console.error('Login error:', error);
        
        if (error.name === 'AbortError') {
            errorMessage.textContent = `Request timed out after ${Math.round(requestTimeoutMs / 1000)}s. Please check your connection and try again.`;
        } else {
            errorMessage.textContent = 'An error occurred. Please try again.';
        }
        errorMessage.classList.add('show');
        
        // Re-enable form
        loginButton.disabled = false;
        loginButton.textContent = 'Sign In';
    } finally {
        loginFlowInProgress = false;
        if (timeoutId) {
            clearTimeout(timeoutId);
        }
    }
});

// Check if already logged in
async function checkAuth() {
    // Skip auto-auth redirects while manual login flow is active.
    if (loginFlowInProgress) {
        return;
    }

    try {
        // First check if setup is complete
        const { controller, timeoutId } = createTimeoutController();
        let setupResponse;
        try {
            setupResponse = await fetch('/api/auth/setup/status', {
                credentials: 'include',
                signal: controller.signal
            });
        } finally {
            clearTimeout(timeoutId);
        }
        
        if (setupResponse.ok) {
            const setupData = await setupResponse.json();

            if (loginFlowInProgress) {
                return;
            }
            
            // If setup not complete, redirect to setup
            if (!setupData.setup_complete) {
                window.location.href = '/setup.html';
                return;
            }
        }
        
        // Check if already authenticated
        const { controller: controller2, timeoutId: timeoutId2 } = createTimeoutController();
        let response;
        try {
            response = await fetch('/api/auth/check', {
                credentials: 'include',
                signal: controller2.signal
            });
        } finally {
            clearTimeout(timeoutId2);
        }
        
        if (response.ok) {
            const data = await response.json();
            if (loginFlowInProgress) {
                return;
            }
            if (data.authenticated) {
                // Already logged in, check for redirect URL or go to main app
                const redirectUrl = sessionStorage.getItem('redirectAfterLogin');
                sessionStorage.removeItem('redirectAfterLogin'); // Clean up
                
                // Validate redirect URL to prevent open redirect attacks
                // Only allow relative paths (no external URLs)
                let targetUrl = '/';
                if (isSafeRelativePath(redirectUrl)) {
                    targetUrl = redirectUrl;
                }
                
                window.location.href = targetUrl;
            }
        }
    } catch (error) {
        if (error.name !== 'AbortError') {
            console.log('Not authenticated');
        }
    }
}

// Passkeys: offered in username autofill where the browser supports it, and
// through the "Sign in with a passkey" button. Only one browser request can be
// pending at a time, so the button cancels autofill and restarts it after.
const passkeySignIn = document.getElementById('passkeySignIn');
const passkeyButton = document.getElementById('passkeyButton');
const passkeyButtonLabel = passkeyButton.textContent.trim();
let passkeyAutofillController = null;
let passkeyAutofillAvailable = false;

function rememberMeChecked() {
    return document.getElementById('rememberMe').checked;
}

function stopPasskeyAutofill() {
    if (passkeyAutofillController) {
        passkeyAutofillController.abort();
        passkeyAutofillController = null;
    }
}

async function startPasskeyAutofill() {
    if (!passkeyAutofillAvailable || passkeyAutofillController) {
        return;
    }
    const controller = new AbortController();
    passkeyAutofillController = controller;
    try {
        const data = await window.Passkeys.signIn({
            autofill: true,
            signal: controller.signal,
            rememberMe: rememberMeChecked
        });
        loginFlowInProgress = true;
        completeLogin(data);
    } catch (error) {
        if (controller.signal.aborted) {
            return;
        }
        if (passkeyAutofillController === controller) {
            passkeyAutofillController = null;
        }
        // Never restart from here: some browsers reject straight away when there
        // is nothing to offer, which would loop. The button still works.
        if (!window.Passkeys.isCancelled(error)) {
            console.error('Passkey autofill sign-in error:', error);
            showLoginError(window.Passkeys.describeError(error));
        }
    }
}

passkeyButton.addEventListener('click', async () => {
    stopPasskeyAutofill();
    loginFlowInProgress = true;
    passkeyButton.disabled = true;
    loginButton.disabled = true;
    passkeyButton.textContent = 'Waiting for your passkey...';
    errorMessage.classList.remove('show');

    try {
        const data = await window.Passkeys.signIn({ rememberMe: rememberMeChecked });
        completeLogin(data);
        return;
    } catch (error) {
        console.error('Passkey sign-in error:', error);
        showLoginError(window.Passkeys.describeError(error));
    }

    loginFlowInProgress = false;
    passkeyButton.disabled = false;
    loginButton.disabled = false;
    passkeyButton.textContent = passkeyButtonLabel;
    startPasskeyAutofill();
});

async function initPasskeys() {
    if (!window.Passkeys || !window.Passkeys.isSupported() || !(await window.Passkeys.isEnabled())) {
        return;
    }
    passkeySignIn.hidden = false;
    passkeyAutofillAvailable = await window.Passkeys.isAutofillAvailable();
    startPasskeyAutofill();
}

checkAuth();
initPasskeys();
