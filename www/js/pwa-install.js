// Surfaces an "Install App" affordance in Settings. A no-op unless the
// browser supports installable PWAs and the app isn't already installed.
// iOS Safari never fires beforeinstallprompt, so it gets static instructions
// instead of a non-functional button.
(function () {
  let deferredInstallPrompt = null;

  function isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  }

  function isIos() {
    return /iphone|ipad|ipod/i.test(window.navigator.userAgent);
  }

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    const section = document.getElementById('pwa-install-section');
    if (section && !isStandalone()) {
      section.hidden = false;
    }
  });

  document.addEventListener('DOMContentLoaded', () => {
    if (isStandalone()) {
      return;
    }

    if (isIos()) {
      const iosSection = document.getElementById('pwa-ios-instructions-section');
      if (iosSection) {
        iosSection.hidden = false;
      }
      return;
    }

    const button = document.getElementById('pwa-install-btn');
    if (!button) {
      return;
    }

    button.addEventListener('click', async () => {
      if (!deferredInstallPrompt) {
        return;
      }
      deferredInstallPrompt.prompt();
      await deferredInstallPrompt.userChoice;
      deferredInstallPrompt = null;
      const section = document.getElementById('pwa-install-section');
      if (section) {
        section.hidden = true;
      }
    });
  });

  window.addEventListener('appinstalled', () => {
    const section = document.getElementById('pwa-install-section');
    if (section) {
      section.hidden = true;
    }
  });
})();
