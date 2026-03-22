import { showError } from './ux.js';

const INSTALL_BUTTON_ID = 'install-app-btn';
let deferredPrompt = null;

export function initPWA() {
  setupInstallPrompt();
  registerServiceWorker();
}

function setupInstallPrompt() {
  const installButton = document.getElementById(INSTALL_BUTTON_ID);
  if (!installButton) return;

  const resetInstallButton = () => {
    installButton.hidden = true;
    installButton.disabled = true;
  };

  resetInstallButton();

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    installButton.hidden = false;
    installButton.disabled = false;
  });

  installButton.addEventListener('click', async () => {
    if (!deferredPrompt) return;

    installButton.disabled = true;

    try {
      await deferredPrompt.prompt();
      await deferredPrompt.userChoice;
    } catch (error) {
      console.info('PWA install prompt was not completed:', error?.message || error);
      installButton.disabled = false;
      return;
    }

    deferredPrompt = null;
    resetInstallButton();
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    resetInstallButton();
  });
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;

  try {
    const registration = await navigator.serviceWorker.register('/sw.js');

    if (registration.waiting) {
      registration.waiting.postMessage({ type: 'SKIP_WAITING' });
    }

    registration.addEventListener('updatefound', () => {
      const nextWorker = registration.installing;
      if (!nextWorker) return;

      nextWorker.addEventListener('statechange', () => {
        if (nextWorker.state === 'installed' && navigator.serviceWorker.controller) {
          nextWorker.postMessage({ type: 'SKIP_WAITING' });
        }
      });
    });
  } catch (error) {
    console.error('Service worker registration failed:', error);
    showError('Не удалось включить офлайн-режим. Приложение продолжит работу без PWA-кэша.');
  }
}
