import { showError, clearError } from './ux.js';

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
  showError('Нет интернета. Используются кэшированные данные.');
}

function handleOnline() {
  clearError();
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
  const swUrl = new URL('sw.js', document.baseURI).pathname;

  try {
    const probe = await fetch(swUrl, { method: 'HEAD', cache: 'no-store' });
    if (!probe.ok) {
      console.info(`Service worker не найден (${swUrl}, HTTP ${probe.status}). PWA пропускается.`);
      return;
    }

    const registration = await navigator.serviceWorker.register(swUrl);

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
    console.info('PWA режим отключен, приложение продолжит работу без service worker.');
  }
}
