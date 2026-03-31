import { showError, clearError, setOfflineState, showSystemMessage } from './ux.js';

const INSTALL_BUTTON_ID = 'install-btn';
let deferredPrompt = null;

export function initPWA() {
  setupInstallPrompt();
  setupConnectivityHandlers();
  registerServiceWorker();
}

export async function installApp() {
  if (!deferredPrompt) return;

  const promptEvent = deferredPrompt;
  deferredPrompt = null;

  hideInstallButton();
  promptEvent.prompt();
  await promptEvent.userChoice;
}

function setupInstallPrompt() {
  hideInstallButton();

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    showInstallButton();
  });

  const installButton = document.getElementById(INSTALL_BUTTON_ID);
  if (!installButton) return;

  installButton.addEventListener('click', async () => {
    installButton.disabled = true;

    try {
      await installApp();
    } catch (error) {
      console.info('PWA install prompt was not completed:', error?.message || error);
      if (deferredPrompt) {
        showInstallButton();
      }
      return;
    } finally {
      installButton.disabled = false;
    }
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    hideInstallButton();
  });
}

function setupConnectivityHandlers() {
  window.addEventListener('online', handleOnline);
  window.addEventListener('offline', handleOffline);

  if (!navigator.onLine) {
    handleOffline();
  }
}

function handleOffline() {
  setOfflineState(true);
  showError('You are offline. Cached data may be shown.');
}

function handleOnline() {
  setOfflineState(false);
  clearError();
  showSystemMessage('Connection restored', { variant: 'success' });
}

function showInstallButton() {
  const installButton = document.getElementById(INSTALL_BUTTON_ID);
  if (!installButton) return;
  installButton.hidden = false;
  installButton.disabled = false;
}

function hideInstallButton() {
  const installButton = document.getElementById(INSTALL_BUTTON_ID);
  if (!installButton) return;
  installButton.hidden = true;
  installButton.disabled = true;
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  const swUrl = new URL('sw.js', document.baseURI);
  const basePath = getBasePath();
  const expectedScope = new URL(basePath, window.location.origin).href;

  try {
    await unregisterMismatchedWorkers(expectedScope);

    const probe = await fetch(swUrl.href, { method: 'HEAD', cache: 'no-store' });
    if (!probe.ok) {
      console.info(`Service worker не найден (${swUrl.href}, HTTP ${probe.status}). PWA пропускается.`);
      return;
    }

    const registration = await navigator.serviceWorker.register(swUrl.href, { scope: basePath });
    console.info('[PWA] Service worker registered', { swUrl: swUrl.href, scope: registration.scope, expectedScope });

    if (registration.waiting) {
      console.log('New version available');
    }

    registration.addEventListener('updatefound', () => {
      const nextWorker = registration.installing;
      if (!nextWorker) return;

      nextWorker.addEventListener('statechange', () => {
        if (nextWorker.state === 'installed' && navigator.serviceWorker.controller) {
          console.log('New version available');
        }
      });
    });
  } catch (error) {
    console.error('Service worker registration failed:', error);
    console.info('PWA режим отключен (fail-safe), приложение продолжит работу напрямую из сети без service worker.');
  }
}

function getBasePath() {
  const path = window.location.pathname || '/';
  const segments = path.split('/').filter(Boolean);
  if (segments.length > 0 && !segments[segments.length - 1].includes('.')) {
    return `/${segments.join('/')}/`;
  }
  return segments.length > 1 ? `/${segments.slice(0, -1).join('/')}/` : '/';
}

async function unregisterMismatchedWorkers(expectedScope) {
  const registrations = await navigator.serviceWorker.getRegistrations();
  await Promise.all(registrations.map(async (registration) => {
    if (registration.scope !== expectedScope) {
      await registration.unregister();
      console.warn('[PWA] Unregistered mismatched service worker scope', {
        foundScope: registration.scope,
        expectedScope
      });
    }
  }));
}
