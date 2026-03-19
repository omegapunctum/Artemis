import { login, register, logout, getCurrentUser } from './auth.js';
import { createDraft, updateDraft, deleteDraft, getDraftsForUser, submitForModeration, validateDraftPayload } from './ugc.js';
import { uploadFile } from './uploads.js';
import { loadLayers } from './data.js';

let ugcInitialized = false;

export async function initUGCUI() {
  if (ugcInitialized) return;
  ugcInitialized = true;

  const els = {
    authButtons: document.getElementById('auth-buttons'),
    loginBtn: document.getElementById('login-btn'),
    registerBtn: document.getElementById('register-btn'),
    profilePanel: document.getElementById('profile-panel'),
    draftsList: document.getElementById('drafts-list'),
    openDraftEditorBtn: document.getElementById('open-draft-editor-btn'),
    refreshDraftsBtn: document.getElementById('refresh-drafts-btn'),
    logoutBtn: document.getElementById('logout-btn'),
    loginModal: document.getElementById('login-modal'),
    loginForm: document.getElementById('login-form'),
    draftModal: document.getElementById('draft-modal'),
    draftForm: document.getElementById('draft-form'),
    draftErrors: document.getElementById('draft-errors')
  };

  const state = {
    activeDraftId: null,
    pendingAfterLogin: null,
    layers: await loadLayers().catch(() => []),
    isRefreshingDrafts: false
  };

  hydrateLayerSelect(state.layers);
  bindModalClosers(els);
  bindAuth(els, state);
  bindDraftEditor(els, state);
  syncAuthUI(els);

  if (getCurrentUser()) {
    await refreshDraftsList(els, state);
  }

  window.addEventListener('artemis:auth-required', () => {
    state.pendingAfterLogin = state.pendingAfterLogin || 'restore-session';
    openModal(els.loginModal);
  }, { passive: true });
}

function bindAuth(els, state) {
  els.loginBtn.addEventListener('click', () => {
    els.loginForm.dataset.mode = 'login';
    openModal(els.loginModal);
  });

  els.registerBtn.addEventListener('click', () => {
    els.loginForm.dataset.mode = 'register';
    openModal(els.loginModal);
  });

  els.loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const mode = els.loginForm.dataset.mode || 'login';
    const email = els.loginForm.email.value.trim();
    const password = els.loginForm.password.value;

    setLoading(els.loginForm, true);
    try {
      if (mode === 'register') await register(email, password);
      else await login(email, password);
      closeModal(els.loginModal);
      syncAuthUI(els);
      await refreshDraftsList(els, state);
      showToast('Авторизация успешна.');

      if (state.pendingAfterLogin === 'open-editor') {
        state.pendingAfterLogin = null;
        openDraftEditor(els, state, null);
      } else {
        state.pendingAfterLogin = null;
      }
    } catch (error) {
      console.error('Ошибка авторизации:', error);
      showToast(error.message || 'Ошибка авторизации.');
    } finally {
      setLoading(els.loginForm, false);
    }
  });

  els.logoutBtn.addEventListener('click', async () => {
    await logout();
    syncAuthUI(els);
    els.draftsList.innerHTML = '';
    state.activeDraftId = null;
    closeModal(els.draftModal);
    showToast('Вы вышли из аккаунта.');
  });
}

function bindDraftEditor(els, state) {
  els.openDraftEditorBtn.addEventListener('click', () => {
    if (!getCurrentUser()) {
      state.pendingAfterLogin = 'open-editor';
      els.loginForm.dataset.mode = 'login';
      openModal(els.loginModal);
      return;
    }
    openDraftEditor(els, state, null);
  });

  els.refreshDraftsBtn.addEventListener('click', async () => {
    if (!getCurrentUser()) {
      openModal(els.loginModal);
      return;
    }
    await refreshDraftsList(els, state);
  });

  // Загружает файл отдельно и не блокирует форму при предупреждениях по лицензии.
  els.draftForm.image_file.addEventListener('change', async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      setLoading(els.draftForm, true);
      const upload = await uploadFile(file);
      els.draftForm.source_media_url.value = upload.url || '';
      els.draftForm.source_license.value = upload.license || '';
      if (!upload.license) showToast('Изображение загружено, но лицензия не указана. Проверьте поле source_license.');
      else showToast('Изображение загружено.');
    } catch (error) {
      console.error('Ошибка загрузки изображения:', error);
      if (String(error.message || '').includes('Требуется повторный вход')) {
        state.pendingAfterLogin = 'open-editor';
        openModal(els.loginModal);
      }
      showToast(error.message || 'Не удалось загрузить изображение.');
    } finally {
      setLoading(els.draftForm, false);
    }
  });

  els.draftForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    const payload = collectDraftPayload(els.draftForm);
    const check = validateDraftPayload(payload);
    if (!check.valid) {
      renderFieldErrors(els.draftForm, els.draftErrors, check.errors);
      return;
    }

    setLoading(els.draftForm, true);
    renderFieldErrors(els.draftForm, els.draftErrors, {});
    try {
      if (state.activeDraftId) {
        await updateDraft(state.activeDraftId, payload);
        showToast('Черновик обновлён.');
      } else {
        await createDraft(payload);
        showToast('Черновик создан.');
      }
      closeModal(els.draftModal);
      await refreshDraftsList(els, state);
    } catch (error) {
      console.error('Ошибка сохранения черновика:', error);
      if (error.type === 'validation') {
        renderFieldErrors(els.draftForm, els.draftErrors, error.fields || {});
      } else if (error.type === 'auth' || String(error.message || '').includes('Требуется повторный вход')) {
        state.pendingAfterLogin = 'open-editor';
        showToast('Нужна авторизация.');
        openModal(els.loginModal);
      } else {
        showToast(error.message || 'Не удалось сохранить черновик.');
      }
    } finally {
      setLoading(els.draftForm, false);
    }
  });
}

// Обновляет список черновиков без перезагрузки страницы.
async function refreshDraftsList(els, state) {
  if (state.isRefreshingDrafts) return;
  state.isRefreshingDrafts = true;
  try {
    const drafts = await getDraftsForUser();
    els.draftsList.innerHTML = '';

    drafts.forEach((draft) => {
      const item = document.createElement('li');
      item.className = 'draft-item';
      item.innerHTML = `
        <strong>${escapeHtml(draft.name_ru || 'Без названия')}</strong>
        <span class="status-label">${humanStatus(draft.status)}</span>
        <div class="draft-actions">
          <button type="button" data-action="edit">Edit</button>
          <button type="button" data-action="delete">Delete</button>
          <button type="button" data-action="submit">Submit for moderation</button>
        </div>
      `;

      item.querySelector('[data-action="edit"]').addEventListener('click', () => openDraftEditor(els, state, draft));
      item.querySelector('[data-action="delete"]').addEventListener('click', async () => {
        try {
          await deleteDraft(draft.id);
          showToast('Черновик удалён.');
          await refreshDraftsList(els, state);
        } catch (error) {
          console.error('Ошибка удаления:', error);
          handlePossiblyUnauthorized(error, state, els);
          showToast(error.message || 'Не удалось удалить черновик.');
        }
      });
      item.querySelector('[data-action="submit"]').addEventListener('click', async () => {
        try {
          await submitForModeration(draft.id);
          showToast('Черновик отправлен на модерацию.');
          await refreshDraftsList(els, state);
        } catch (error) {
          console.error('Ошибка отправки на модерацию:', error);
          handlePossiblyUnauthorized(error, state, els);
          showToast(error.message || 'Не удалось отправить на модерацию.');
        }
      });

      els.draftsList.appendChild(item);
    });
  } catch (error) {
    console.error('Ошибка загрузки черновиков:', error);
    handlePossiblyUnauthorized(error, state, els);
    showToast(error.message || 'Не удалось загрузить черновики.');
  } finally {
    state.isRefreshingDrafts = false;
  }
}

function openDraftEditor(els, state, draft) {
  state.activeDraftId = draft?.id || null;
  els.draftForm.reset();
  renderFieldErrors(els.draftForm, els.draftErrors, {});

  if (draft) {
    for (const [key, value] of Object.entries(draft)) {
      if (els.draftForm[key] && value !== null && value !== undefined) {
        els.draftForm[key].value = Array.isArray(value) ? value.join(', ') : value;
      }
    }
    if (Array.isArray(draft.coords)) {
      els.draftForm.longitude.value = draft.coords[0] ?? '';
      els.draftForm.latitude.value = draft.coords[1] ?? '';
    }
  }

  openModal(els.draftModal);
}

function collectDraftPayload(form) {
  return {
    name_ru: form.name_ru.value.trim(),
    name_en: form.name_en.value.trim(),
    layer_id: form.layer_id.value,
    date_start: form.date_start.value,
    date_construction_end: form.date_construction_end.value,
    date_end: form.date_end.value,
    longitude: form.longitude.value,
    latitude: form.latitude.value,
    influence_radius_km: form.influence_radius_km.value,
    title_short: form.title_short.value.trim(),
    description: form.description.value.trim(),
    tags: form.tags.value,
    source_media_url: form.source_media_url.value.trim(),
    source_license: form.source_license.value.trim()
  };
}

// Показывает ошибки рядом с соответствующими полями формы.
function renderFieldErrors(form, container, errors) {
  container.innerHTML = '';
  form.querySelectorAll('.field-error-message').forEach((node) => node.remove());
  form.querySelectorAll('.is-invalid').forEach((node) => node.classList.remove('is-invalid'));

  Object.entries(errors).forEach(([field, message]) => {
    const row = document.createElement('div');
    row.className = 'field-error';
    row.textContent = `${field}: ${message}`;
    container.appendChild(row);

    const input = form[field];
    if (!input) return;
    input.classList.add('is-invalid');
    const inline = document.createElement('div');
    inline.className = 'field-error-message';
    inline.textContent = message;
    input.insertAdjacentElement('afterend', inline);
  });
}

function hydrateLayerSelect(layers) {
  const select = document.querySelector('#draft-form select[name="layer_id"]');
  if (!select) return;
  const known = new Set([...select.options].map((option) => option.value));
  (Array.isArray(layers) ? layers : []).forEach((layer) => {
    const id = String(layer?.id || '').trim();
    if (!id || known.has(id)) return;
    known.add(id);
    select.appendChild(new Option(layer.name_ru || id, id));
  });
}

function syncAuthUI(els) {
  const loggedIn = Boolean(getCurrentUser());
  els.authButtons.hidden = loggedIn;
  els.profilePanel.hidden = !loggedIn;
}

function bindModalClosers(els) {
  [els.loginModal, els.draftModal].forEach((modal) => {
    modal.addEventListener('click', (event) => {
      if (event.target === modal || event.target.matches('[data-close-modal]')) {
        closeModal(modal);
      }
    });
  });
}

function openModal(node) {
  if (!node || !node.hidden) return;
  node.hidden = false;
  document.body.classList.add('modal-open');
}

function closeModal(node) {
  if (!node || node.hidden) return;
  node.hidden = true;
  const hasVisibleModal = [...document.querySelectorAll('.modal')].some((modal) => !modal.hidden);
  if (!hasVisibleModal) document.body.classList.remove('modal-open');
}

function setLoading(form, loading) {
  form.querySelectorAll('button, input, select, textarea').forEach((node) => {
    if (node.type === 'file') {
      node.disabled = loading;
      return;
    }
    if (node.tagName === 'BUTTON') node.disabled = loading;
  });
}

function humanStatus(status) {
  if (status === 'pending') return 'Ожидает модерации';
  if (status === 'approved') return 'Одобрено';
  if (status === 'rejected') return 'Отклонено';
  return 'Черновик';
}

function showToast(message) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timerId);
  showToast.timerId = window.setTimeout(() => toast.classList.remove('show'), 2800);
}

function handlePossiblyUnauthorized(error, state, els) {
  if (error?.type === 'auth' || String(error?.message || '').includes('Требуется повторный вход')) {
    state.pendingAfterLogin = 'open-editor';
    openModal(els.loginModal);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}
