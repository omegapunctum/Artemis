import { clearError, setOfflineState, showSystemMessage } from './ux.js';

let deferredPrompt = null;
let installDismissed = false;
let updateDismissed = false;
let iosFallbackShown = false;
let activeBannerKey = '';
let pendingUpdateRegistration = null;
let isUpdating = false;

export function initPWA() {
  setupInstallPrompt();
  setupConnectivityHandlers();
  registerServiceWorker();
}

export async function installApp() {
  if (!deferredPrompt) return;

  const promptEvent = deferredPrompt;
  deferredPrompt = null;
  promptEvent.prompt();
  const choice = await promptEvent.userChoice;
  if (choice?.outcome === 'accepted') {
    removeBanner('install');
  } else {
    installDismissed = true;
    removeBanner('install');
  }
}

function setupInstallPrompt() {
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    renderInstallBanner();
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    installDismissed = true;
    removeBanner('install');
    showSystemMessage('ARTEMIS installed', { variant: 'success' });
  });

  if (!supportsInstallPrompt() && shouldShowIosInstallHint()) {
    window.setTimeout(() => {
      if (!iosFallbackShown && !isStandaloneMode()) {
        iosFallbackShown = true;
        showBanner({
          key: 'install-hint',
          variant: 'info',
          message: 'Add to Home Screen may be available in your browser menu',
          actions: [
            { label: 'Dismiss', onClick: () => removeBanner('install-hint') }
          ]
        });
      }
    }, 1800);
  }
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
  clearError();
  showSystemMessage('Showing cached data when available', { variant: 'warning', timeout: 3000 });
}

function handleOnline() {
  setOfflineState(false);
  clearError();
  showSystemMessage('Connection restored', { variant: 'success' });
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
      markUpdateAvailable(registration);
    }

    registration.addEventListener('updatefound', () => {
      const nextWorker = registration.installing;
      if (!nextWorker) return;

      nextWorker.addEventListener('statechange', () => {
        if (nextWorker.state === 'installed' && navigator.serviceWorker.controller) {
          markUpdateAvailable(registration);
        }
      });
    });

    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (isUpdating) {
        window.location.reload();
      }
    });
  } catch (error) {
    console.error('Service worker registration failed:', error);
    console.info('PWA режим отключен (fail-safe), приложение продолжит работу напрямую из сети без service worker.');
  }
}

function renderInstallBanner() {
  if (!deferredPrompt || installDismissed || isStandaloneMode()) return;
  showBanner({
    key: 'install',
    variant: 'info',
    message: 'Install ARTEMIS for faster access',
    actions: [
      {
        label: 'Install',
        onClick: async () => {
          try {
            await installApp();
          } catch (error) {
            console.info('PWA install prompt was not completed:', error?.message || error);
          }
        }
      },
      {
        label: 'Dismiss',
        onClick: () => {
          installDismissed = true;
          removeBanner('install');
        }
      }
    ]
  });
}

function markUpdateAvailable(registration) {
  if (!registration?.waiting || updateDismissed) return;
  pendingUpdateRegistration = registration;
  showBanner({
    key: 'update',
    variant: 'info',
    message: 'A new version of ARTEMIS is available',
    actions: [
      {
        label: 'Update now',
        onClick: () => applyUpdate()
      },
      {
        label: 'Later',
        onClick: () => {
          updateDismissed = true;
          removeBanner('update');
        }
      }
    ]
  });
}

function applyUpdate() {
  if (!pendingUpdateRegistration?.waiting) return;
  isUpdating = true;
  showSystemMessage('Updating ARTEMIS…', { variant: 'info', timeout: 4000 });
  pendingUpdateRegistration.waiting.postMessage({ type: 'SKIP_WAITING' });
  removeBanner('update');
}

function showBanner({ key, variant = 'info', message = '', actions = [] }) {
  const host = document.getElementById('app-status-host');
  if (!host || !message) return;
  if (activeBannerKey && activeBannerKey !== key) {
    removeBanner(activeBannerKey);
  }

  const existing = host.querySelector(`[data-banner-key="${key}"]`);
  if (existing) existing.remove();

  const banner = document.createElement('section');
  banner.className = `app-system-banner app-system-${variant}`;
  banner.dataset.bannerKey = key;
  banner.setAttribute('role', 'status');
  banner.setAttribute('aria-live', 'polite');

  const text = document.createElement('p');
  text.className = 'app-system-banner-text';
  text.textContent = message;
  banner.appendChild(text);

  if (actions.length) {
    const controls = document.createElement('div');
    controls.className = 'app-system-banner-actions';
    actions.forEach(({ label, onClick }) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'app-system-banner-btn';
      button.textContent = label;
      button.setAttribute('aria-label', label);
      button.addEventListener('click', onClick);
      controls.appendChild(button);
    });
    banner.appendChild(controls);
  }

  host.prepend(banner);
  activeBannerKey = key;
}

function removeBanner(key) {
  const host = document.getElementById('app-status-host');
  const banner = host?.querySelector(`[data-banner-key="${key}"]`);
  if (banner) banner.remove();
  if (activeBannerKey === key) activeBannerKey = '';
}

function isStandaloneMode() {
  return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
}

function supportsInstallPrompt() {
  return 'onbeforeinstallprompt' in window;
}

function shouldShowIosInstallHint() {
  if (isStandaloneMode()) return false;
  const isMobileViewport = window.matchMedia('(max-width: 900px)').matches || window.matchMedia('(pointer: coarse)').matches;
  return isMobileViewport;
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
