/**
 * Setup page functionality
 */

const form = document.getElementById('setupForm');
const errorMessage = document.getElementById('errorMessage');
const setupButton = document.getElementById('setupButton');
const passwordInput = document.getElementById('password');
const passwordStrengthBar = document.getElementById('passwordStrengthBar');
const restoreControls = document.getElementById('restoreControls');
const restoreFileInput = document.getElementById('restoreFile');
const restoreButton = document.getElementById('restoreButton');
const restoreProgress = new RestoreProgressDisplay();
const MAX_BACKUP_FILE_SIZE_BYTES = 100 * 1024 * 1024;
const RESTORE_TIMEOUT_MS = 25 * 60 * 1000;
const createTimeoutController = window.NetworkTimeoutUtils?.createTimeoutController ||
    ((baseTimeoutMs = 5000) => {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), baseTimeoutMs);
        return { controller, timeoutId, timeoutMs: baseTimeoutMs };
    });

// Check if setup is needed
async function checkSetupStatus() {
    try {
        const { controller, timeoutId } = createTimeoutController();
        let response;
        try {
            response = await fetch('/api/auth/setup/status', {
                credentials: 'include',
                signal: controller.signal
            });
        } finally {
            clearTimeout(timeoutId);
        }
        
        if (response.ok) {
            const data = await response.json();
            
            // If setup is complete, redirect to login
            if (data.setup_complete) {
                window.location.href = '/login.html';
            }
        }
    } catch (error) {
        console.error('Setup status check failed:', error);
    }
}

checkSetupStatus();

// Password strength indicator
passwordInput.addEventListener('input', () => {
    const password = passwordInput.value;
    let strength = 0;

    if (password.length >= 8) strength++;
    if (password.length >= 12) strength++;
    if (password.match(/[a-z]/) && password.match(/[A-Z]/)) strength++;
    if (password.match(/\d/)) strength++;
    if (password.match(/[^a-zA-Z\d]/)) strength++;

    passwordStrengthBar.className = 'password-strength-bar';
    if (strength >= 4) {
        passwordStrengthBar.classList.add('strong');
    } else if (strength >= 3) {
        passwordStrengthBar.classList.add('medium');
    } else if (strength >= 1) {
        passwordStrengthBar.classList.add('weak');
    }
});

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const email = document.getElementById('email').value;
    const username = document.getElementById('username').value;
    const displayName = document.getElementById('displayName').value;
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirmPassword').value;

    // Validate passwords match
    if (password !== confirmPassword) {
        errorMessage.textContent = 'Passwords do not match';
        errorMessage.classList.add('show');
        return;
    }

    // Validate password strength
    if (password.length < 8) {
        errorMessage.textContent = 'Password must be at least 8 characters';
        errorMessage.classList.add('show');
        return;
    }

    // Disable form
    setupButton.disabled = true;
    setupButton.innerHTML = '<span class="loading"></span>Setting up...';
    errorMessage.classList.remove('show');

    let requestTimeoutMs = 5000;
    let timeoutId;

    try {
        const { controller, timeoutId: requestTimeoutId, timeoutMs } = createTimeoutController();
        timeoutId = requestTimeoutId;
        requestTimeoutMs = timeoutMs;
        
        const response = await fetch('/api/auth/setup/admin', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ 
                email, 
                username, 
                password,
                display_name: displayName
            }),
            signal: controller.signal
        });

        const data = await response.json();

        if (response.ok && data.success) {
            // Cache user data immediately from setup response
            // The setup response now includes permissions
            if (data.user) {
                sessionStorage.setItem('currentUser', JSON.stringify(data.user));
            }
            
            // Redirect to main app
            setupButton.innerHTML = '✓ Setup Complete! Redirecting...';
            setTimeout(() => {
                window.location.href = '/';
            }, 1500);
        } else {
            // Show error
            errorMessage.textContent = data.message || 'Setup failed. Please try again.';
            errorMessage.classList.add('show');
            
            // Re-enable form
            setupButton.disabled = false;
            setupButton.textContent = 'Complete Setup';
        }
    } catch (error) {
        console.error('Setup error:', error);
        
        if (error.name === 'AbortError') {
            errorMessage.textContent = `Request timed out after ${Math.round(requestTimeoutMs / 1000)}s. Please check your connection and try again.`;
        } else {
            errorMessage.textContent = 'An error occurred. Please try again.';
        }
        errorMessage.classList.add('show');
        
        // Re-enable form
        setupButton.disabled = false;
        setupButton.textContent = 'Complete Setup';
    } finally {
        if (timeoutId) {
            clearTimeout(timeoutId);
        }
    }
});

restoreFileInput.addEventListener('change', () => {
    restoreButton.disabled = restoreFileInput.files.length === 0;
});

function showRestoreError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.add('show');
    errorMessage.scrollIntoView({ block: 'nearest' });
}

function endFailedRestore(message) {
    restoreProgress.stop();
    form.hidden = false;
    restoreControls.hidden = false;
    showRestoreError(message);
}

restoreButton.addEventListener('click', async () => {
    const file = restoreFileInput.files[0];
    if (!file) {
        return;
    }

    errorMessage.classList.remove('show');
    if (file.size > MAX_BACKUP_FILE_SIZE_BYTES) {
        showRestoreError('The backup file is larger than the 100MB limit.');
        return;
    }

    form.hidden = true;
    restoreControls.hidden = true;
    const progressId = restoreProgress.start('Uploading the backup file');
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), RESTORE_TIMEOUT_MS);

    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/api/auth/setup/restore', {
            method: 'POST',
            headers: { 'X-Restore-Progress-Id': progressId },
            credentials: 'include',
            body: formData,
            signal: controller.signal
        });
        const data = await response.json();

        if (response.ok && data.success) {
            restoreProgress.stop();
            document.getElementById('restoreComplete').hidden = false;
            // The login page returns here if the backup had no usable accounts
            setTimeout(() => {
                window.location.href = '/login.html';
            }, 1500);
        } else {
            endFailedRestore(data.message || 'The restore failed. Please try again.');
        }
    } catch (error) {
        console.error('Restore error:', error);
        endFailedRestore('The restore may still be running on the server. Wait a few minutes, then refresh this page to check.');
    } finally {
        clearTimeout(timeoutId);
    }
});
