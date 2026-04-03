import { buildApiError, login, register, logout, getCurrentUser, fetchWithAuth } from './auth.js';
import { loadLayers } from './data.js';
import { clearError, showLoading, hideLoading, normalizeAppError, showSystemMessage, ensureOnlineAction, createInlineStateBlock, setButtonBusy } from './ux.js';
import { setText, toSafeText } from './safe-dom.js';

let ugcInitialized = false;

const FORM_FIELDS = [
  'name_ru',
  'name_en',
  'layer_id',
  'date_start',
  'date_end',
  'latitude',
  'longitude',
  'coordinates_confidence',
  'title_short',
  'description',
  'image_url',
  'source_url',
  'tags'
];

const STATUS_TEXT = {
  pristine: 'pristine',
  editing: 'editing',
  saving: 'saving',
  saved: 'saved as draft',
  submitting: 'submitting to pending',
  validation: 'validation error',
  server: 'server error',
  draft: 'draft',
  pending: 'pending',
  approved: 'approved',
  rejected: 'rejected'
};

const DRAFT_STATUS_LABELS = {
  draft: 'Draft',
  pending: 'Pending review',
  approved: 'Approved',
  rejected: 'Rejected',
  unknown: 'Unknown status'
};

const CONFIDENCE_ALLOWED = new Set(['exact', 'approximate', 'conditional']);
const READ_ONLY_STATUSES = new Set(['pending', 'approved']);

const uiState = {
  drafts: [],
  activeDraftId: null,
  mode: 'create',
  formState: 'pristine',
  ugcBusy: false,
  busyControl: null,
  readOnly: false,
  pendingAfterLogin: null,
  layers: []
};

export async function initUGCUI() {
  if (ugcInitialized) return;
  ugcInitialized = true;

  const els = getElements();
  if (!els.ugcPanel || !els.form) return;
  ensureUgcErrorHost(els);

  uiState.layers = await loadLayers().catch(() => []);
  hydrateLayerSelect(els.form, uiState.layers);

  bindAuth(els);
  bindModalClosers(els);
  bindUgcPanel(els);
  bindForm(els);
  bindEscClose(els);
  syncAuthUI(els);

  if (getCurrentUser()) {
    await refreshDrafts(els);
  } else {
    renderDraftList(els);
  }

  window.addEventListener('artemis:auth-required', () => {
    uiState.pendingAfterLogin = uiState.pendingAfterLogin || 'open-ugc';
    openModal(els.loginModal);
  }, { passive: true });
}

function getElements() {
  return {
    authButtons: document.getElementById('auth-buttons'),
    profilePanel: document.getElementById('profile-panel'),
    loginBtn: document.getElementById('login-btn'),
    registerBtn: document.getElementById('register-btn'),
    logoutBtn: document.getElementById('logout-btn'),
    loginModal: document.getElementById('login-modal'),
    loginForm: document.getElementById('login-form'),

    createBtn: document.getElementById('ugc-create-btn'),
    fallbackCreateBtn: document.getElementById('open-draft-editor-btn'),
    refreshLegacyBtn: document.getElementById('refresh-drafts-btn'),

    ugcPanel: document.getElementById('ugc-panel'),
    ugcTitle: document.getElementById('ugc-panel-title'),
    ugcSubtitle: document.getElementById('ugc-panel-subtitle'),
    ugcAuthCta: document.getElementById('ugc-auth-cta'),
    ugcGlobalError: document.getElementById('ugc-global-error'),
    ugcDraftsList: document.getElementById('ugc-drafts-list'),
    ugcDraftsEmpty: document.getElementById('ugc-drafts-empty'),
    ugcRefreshDraftsBtn: document.getElementById('ugc-refresh-drafts-btn'),
    ugcCloseBtn: document.getElementById('ugc-close-btn'),

    form: document.getElementById('ugc-draft-form'),
    fieldErrors: document.getElementById('ugc-field-errors'),
    saveBtn: document.getElementById('ugc-save-btn'),
    submitBtn: document.getElementById('ugc-submit-btn'),
    deleteBtn: document.getElementById('ugc-delete-btn'),
    cancelBtn: document.getElementById('ugc-cancel-btn'),
    useMapCenterBtn: document.getElementById('ugc-use-map-center-btn')
  };
}

function bindAuth(els) {
  els.loginBtn?.addEventListener('click', () => {
    els.loginForm.dataset.mode = 'login';
    openModal(els.loginModal);
  });

  els.registerBtn?.addEventListener('click', () => {
    els.loginForm.dataset.mode = 'register';
    openModal(els.loginModal);
  });

  els.logoutBtn?.addEventListener('click', async () => {
    await logout();
    uiState.drafts = [];
    uiState.activeDraftId = null;
    syncAuthUI(els);
    renderDraftList(els);
    closeUgcPanel(els);
  });

  els.loginForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const mode = els.loginForm.dataset.mode || 'login';
    const email = els.loginForm.email.value.trim();
    const password = els.loginForm.password.value;

    setLoading(els.loginForm, true);
    try {
      if (mode === 'register') await register(email, password);
      else await login(email, password);

      clearError();
      setGlobalError(els, '');
      closeModal(els.loginModal);
      syncAuthUI(els);
      await refreshDrafts(els);

      if (uiState.pendingAfterLogin === 'open-ugc') {
        uiState.pendingAfterLogin = null;
        openUgcPanel(els);
      } else {
        uiState.pendingAfterLogin = null;
      }
    } catch (error) {
      const message = normalizeAppError(error, 'Authentication failed.').message;
      setGlobalError(els, message);
      showSystemMessage(message, { variant: 'warning' });
    } finally {
      setLoading(els.loginForm, false);
    }
  });
}

function bindModalClosers(els) {
  [els.loginModal].forEach((modal) => {
    modal?.addEventListener('click', (event) => {
      const closeBtn = event.target.closest?.('[data-close-modal]');
      if (event.target === modal || closeBtn) closeModal(modal);
    });
  });
}

function bindUgcPanel(els) {
  const openHandler = () => {
    openUgcPanel(els);
  };
  els.createBtn?.addEventListener('click', openHandler);
  els.fallbackCreateBtn?.addEventListener('click', openHandler);

  els.refreshLegacyBtn?.addEventListener('click', async () => {
    openUgcPanel(els);
    if (getCurrentUser()) await refreshDrafts(els);
  });

  els.ugcRefreshDraftsBtn?.addEventListener('click', async () => {
    if (!requireAuthForUgc(els)) return;
    await refreshDrafts(els);
  });

  els.ugcCloseBtn?.addEventListener('click', () => closeUgcPanel(els));
  els.cancelBtn?.addEventListener('click', () => closeUgcPanel(els));

  document.addEventListener('click', (event) => {
    if (els.ugcPanel.hidden) return;
    const target = event.target;
    const insidePanel = els.ugcPanel.contains(target);
    const opener = target?.closest?.('#ugc-create-btn, #open-draft-editor-btn');
    if (!insidePanel && !opener) closeUgcPanel(els);
  });
}

function bindEscClose(els) {
  document.addEventListener('keydown', (event) => {
    if (event.defaultPrevented) return;
    if (event.key !== 'Escape') return;
    if (!els.loginModal.hidden) {
      closeModal(els.loginModal);
      event.preventDefault();
      return;
    }
    if (!els.ugcPanel.hidden) {
      closeUgcPanel(els);
      event.preventDefault();
    }
  });
}

function bindForm(els) {
  els.form?.addEventListener('input', () => {
    if (uiState.formState !== 'saving' && uiState.formState !== 'submitting') {
      setFormState(els, 'editing');
    }
  });

  els.form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!requireAuthForUgc(els)) return;
    await saveDraft(els);
  });

  els.submitBtn?.addEventListener('click', async () => {
    if (!requireAuthForUgc(els)) return;
    await submitDraft(els);
  });

  els.deleteBtn?.addEventListener('click', async () => {
    if (!requireAuthForUgc(els) || !uiState.activeDraftId) return;
    await deleteActiveDraft(els);
  });

  els.useMapCenterBtn?.addEventListener('click', () => {
    const mapNode = document.getElementById('map');
    const map = mapNode?._map || window.__ARTEMIS_MAP || null;
    if (!map || typeof map.getCenter !== 'function') return;
    const center = map.getCenter();
    els.form.latitude.value = Number(center.lat).toFixed(6);
    els.form.longitude.value = Number(center.lng).toFixed(6);
    setFormState(els, 'editing');
  });
}

function openUgcPanel(els) {
  els.ugcPanel.hidden = false;
  els.ugcPanel.setAttribute('aria-hidden', 'false');
  els.ugcPanel.dataset.state = 'open';
  els.createBtn?.setAttribute('aria-expanded', 'true');
  els.fallbackCreateBtn?.setAttribute('aria-expanded', 'true');
  document.dispatchEvent(new CustomEvent('artemis:overlay-open', { detail: { source: 'ugc' } }));

  const loggedIn = Boolean(getCurrentUser());
  els.ugcAuthCta.hidden = loggedIn;
  els.form.hidden = !loggedIn;

  if (!loggedIn) {
    els.ugcAuthCta.replaceChildren();
    const ctaBlock = createInlineStateBlock({
      variant: 'info',
      title: 'Authentication required',
      message: 'Please log in to create and manage drafts.',
      actionLabel: 'Login',
      onAction: () => {
      uiState.pendingAfterLogin = 'open-ugc';
      openModal(els.loginModal);
      }
    });
    els.ugcAuthCta.appendChild(ctaBlock);
    setFormState(els, 'pristine');
    return;
  }

  els.ugcAuthCta.hidden = true;
  els.form.hidden = false;
  openCreateMode(els);
}

function closeUgcPanel(els) {
  els.ugcPanel.hidden = true;
  els.ugcPanel.setAttribute('aria-hidden', 'true');
  els.ugcPanel.dataset.state = 'closed';
  els.createBtn?.setAttribute('aria-expanded', 'false');
  els.fallbackCreateBtn?.setAttribute('aria-expanded', 'false');
  document.dispatchEvent(new CustomEvent('artemis:overlay-close', { detail: { source: 'ugc' } }));
  setGlobalError(els, '');
}

function openCreateMode(els) {
  uiState.activeDraftId = null;
  uiState.mode = 'create';
  uiState.readOnly = false;
  els.form.reset();
  renderFieldErrors(els.form, els.fieldErrors, {});
  syncModeUI(els);
  setFormState(els, 'pristine');
}

function openEditMode(els, draft) {
  uiState.activeDraftId = draft?.id ?? null;
  uiState.mode = 'edit';
  uiState.readOnly = READ_ONLY_STATUSES.has(String(draft?.status || '').toLowerCase());

  els.form.reset();
  FORM_FIELDS.forEach((field) => {
    if (!els.form[field]) return;
    const value = draft?.[field];
    if (value === null || value === undefined) {
      els.form[field].value = '';
      return;
    }
    if (field === 'tags' && Array.isArray(value)) {
      els.form[field].value = value.join(', ');
      return;
    }
    els.form[field].value = String(value);
  });

  if (Array.isArray(draft?.coords)) {
    els.form.longitude.value = draft.coords[0] ?? '';
    els.form.latitude.value = draft.coords[1] ?? '';
  }

  renderFieldErrors(els.form, els.fieldErrors, {});
  syncModeUI(els, draft);
  setFormState(els, draft?.status || 'editing');
}

async function refreshDrafts(els) {
  if (!getCurrentUser()) {
    renderDraftList(els);
    return;
  }

  showLoading();
  setGlobalError(els, '');
  toggleDraftsEmptyState(els, true, {
    variant: 'info',
    title: 'Loading drafts',
    message: 'Fetching your latest drafts…'
  });
  try {
    const data = await requestDraftApi(['/api/drafts/my', '/drafts/my', '/drafts'], { method: 'GET' }, 'Failed to load drafts.');
    uiState.drafts = Array.isArray(data) ? data : [];
    renderDraftList(els);
    clearError();
  } catch (error) {
    const normalized = normalizeAppError(error, 'Failed to load drafts.');
    const message = handleAuthError(error, els) || normalized.message;
    setGlobalError(els, message, { retry: () => refreshDrafts(els) });
    showSystemMessage(message, { variant: 'warning' });
    toggleDraftsEmptyState(els, false);
  } finally {
    hideLoading();
  }
}

function renderDraftList(els) {
  els.ugcDraftsList.replaceChildren();
  const loggedIn = Boolean(getCurrentUser());

  if (!loggedIn) {
    toggleDraftsEmptyState(els, false);
    return;
  }

  if (!uiState.drafts.length) {
    const hasError = Boolean(String(els.ugcGlobalError?.textContent || '').trim());
    toggleDraftsEmptyState(els, !hasError, {
      variant: 'info',
      title: 'No drafts yet',
      message: 'Start with “Create draft”, then save your progress to see it here.'
    });
    return;
  }

  toggleDraftsEmptyState(els, false);

  uiState.drafts.forEach((draft) => {
    const item = document.createElement('li');
    item.className = 'ugc-draft-item';

    const title = document.createElement('strong');
    setText(title, draft?.title_short || draft?.name_ru || 'Untitled draft');

    const meta = document.createElement('div');
    meta.className = 'ugc-draft-meta';
    const updated = document.createElement('span');
    setText(updated, formatUpdatedAt(draft?.updated_at));

    const statusInfo = renderStatusInfo(draft);
    meta.append(updated, statusInfo);

    const actions = document.createElement('div');
    actions.className = 'ugc-draft-actions';

    const openBtn = document.createElement('button');
    openBtn.type = 'button';
    setText(openBtn, 'Open');
    openBtn.addEventListener('click', () => {
      openEditMode(els, draft);
      if (els.ugcPanel.hidden) openUgcPanel(els);
    });

    actions.appendChild(openBtn);
    item.append(title, meta, actions);

    els.ugcDraftsList.appendChild(item);
  });
}

function toggleDraftsEmptyState(els, visible, options = {}) {
  const emptyNode = els.ugcDraftsEmpty;
  if (!emptyNode) return;

  emptyNode.hidden = !visible;
  if (!visible) return;
  const config = typeof options === 'string'
    ? { variant: 'info', title: 'Empty state', message: options }
    : {
      variant: options.variant || 'info',
      title: options.title || 'Empty state',
      message: options.message || 'No drafts yet.'
    };
  emptyNode.replaceChildren(createInlineStateBlock({
    variant: config.variant,
    title: config.title,
    message: config.message
  }));
}

function renderStatusInfo(draft) {
  const statusWrap = document.createElement('div');
  statusWrap.className = 'ugc-status-info';

  const badge = renderStatusBadge(draft);
  statusWrap.appendChild(badge);

  const status = normalizeDraftStatus(draft?.status);
  const rejectionReason = getDraftRejectionReason(draft);
  if (status === 'rejected' && rejectionReason) {
    const reason = document.createElement('small');
    reason.className = 'ugc-status-reason';
    setText(reason, rejectionReason);
    statusWrap.appendChild(reason);
  }

  return statusWrap;
}

function renderStatusBadge(draft) {
  const status = normalizeDraftStatus(draft?.status);
  const badge = document.createElement('span');
  badge.className = 'ugc-status-badge ui-badge';
  badge.classList.add(`ugc-status-${status}`);
  if (status === 'approved') badge.classList.add('is-success');
  if (status === 'rejected') badge.classList.add('is-error');
  if (status === 'pending') badge.classList.add('is-warning');

  setText(badge, DRAFT_STATUS_LABELS[status] || DRAFT_STATUS_LABELS.unknown);
  return badge;
}

function syncModeUI(els, draft = null) {
  const isEdit = uiState.mode === 'edit';
  const title = isEdit ? 'Edit draft' : 'Create draft';
  setText(els.ugcTitle, title);

  if (uiState.readOnly) {
    setText(els.ugcSubtitle, `Draft status: ${normalizeDraftStatus(draft?.status || 'pending')} (read-only)`);
  } else {
    setText(els.ugcSubtitle, `Draft status: ${STATUS_TEXT[uiState.formState] || uiState.formState}`);
  }

  const disableEdit = uiState.readOnly || uiState.ugcBusy;
  FORM_FIELDS.forEach((field) => {
    if (els.form[field]) els.form[field].disabled = disableEdit;
  });

  const pending = uiState.formState === 'saving' || uiState.formState === 'submitting';
  els.saveBtn.disabled = disableEdit || pending;
  els.submitBtn.disabled = disableEdit || !isEdit || pending;
  els.deleteBtn.hidden = !isEdit;
  els.deleteBtn.disabled = disableEdit || pending;
  els.useMapCenterBtn.disabled = disableEdit || pending;
}

function setFormState(els, nextState) {
  uiState.formState = nextState;
  const label = STATUS_TEXT[nextState] || nextState;
  const suffix = uiState.readOnly ? ' (read-only)' : '';
  setText(els.ugcSubtitle, `Draft status: ${label}${suffix}`);
  const pending = nextState === 'saving' || nextState === 'submitting';
  const disableEdit = uiState.readOnly || uiState.ugcBusy;
  els.saveBtn.disabled = disableEdit || pending;
  els.submitBtn.disabled = disableEdit || uiState.mode !== 'edit' || pending;
  els.deleteBtn.disabled = disableEdit || pending;
  els.useMapCenterBtn.disabled = disableEdit || pending;
}

function normalizeDraftStatus(status) {
  const normalized = String(status || 'draft').toLowerCase();
  if (normalized === 'draft' || normalized === 'pending' || normalized === 'approved' || normalized === 'rejected') {
    return normalized;
  }
  return 'unknown';
}

function getDraftRejectionReason(draft) {
  const reason = draft?.rejection_reason ?? draft?.moderation_reason ?? draft?.rejected_reason;
  if (reason == null) return '';
  return String(reason).trim();
}

async function saveDraft(els) {
  if (uiState.ugcBusy) return;
  if (!ensureOnlineAction()) {
    setGlobalError(els, 'You are offline. Draft save needs connection.');
    return;
  }

  const payload = collectDraftPayload(els.form);
  const validation = validateClientPayload(payload);
  renderFieldErrors(els.form, els.fieldErrors, validation.errors);
  if (!validation.valid) {
    setFormState(els, 'validation');
    setGlobalError(els, 'Please fix highlighted fields before saving.');
    showSystemMessage('Validation failed. Check highlighted fields.', { variant: 'warning' });
    return;
  }

  setUgcBusyState(els, true, els.saveBtn);
  setFormState(els, 'saving');
  setGlobalError(els, '');
  showLoading();

  try {
    const method = uiState.activeDraftId ? 'PUT' : 'POST';
    const paths = uiState.activeDraftId
      ? [`/api/drafts/${uiState.activeDraftId}`, `/drafts/${uiState.activeDraftId}`]
      : ['/api/drafts', '/drafts'];

    const saved = await requestDraftApi(paths, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(validation.data)
    }, 'Failed to save draft.');

    if (saved?.id) {
      uiState.activeDraftId = saved.id;
      uiState.mode = 'edit';
      upsertDraft(saved);
      openEditMode(els, saved);
    }

    setFormState(els, 'saved');
    setGlobalError(els, '');
    showSystemMessage('Draft saved', { variant: 'success' });
    await refreshDrafts(els);
  } catch (error) {
    const message = resolveUgcActionErrorMessage(error, els, 'Failed to save draft.');
    setGlobalError(els, message, { retry: () => saveDraft(els) });
    setFormState(els, 'server');
    showSystemMessage(message, { variant: 'warning' });
  } finally {
    hideLoading();
    setUgcBusyState(els, false);
  }
}

async function submitDraft(els) {
  if (uiState.ugcBusy) return;
  if (!ensureOnlineAction()) {
    setGlobalError(els, 'You are offline. Cannot submit for review.');
    return;
  }

  if (!uiState.activeDraftId) {
    setGlobalError(els, 'Save draft first.');
    return;
  }

  setUgcBusyState(els, true, els.submitBtn);
  setFormState(els, 'submitting');
  setGlobalError(els, '');
  showLoading();

  const id = uiState.activeDraftId;
  const submitPaths = [`/api/drafts/${id}/submit`, `/drafts/${id}/submit`];

  try {
    let submitted;
    try {
      submitted = await requestDraftApi(submitPaths, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'pending' })
      }, 'Failed to submit draft.');
    } catch (error) {
      const patchPayload = { ...collectDraftPayload(els.form), status: 'pending' };
      const fallback = validateClientPayload(patchPayload);
      submitted = await requestDraftApi([`/api/drafts/${id}`, `/drafts/${id}`], {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fallback.data)
      }, error.message || 'Failed to submit draft.');
    }

    upsertDraft(submitted);
    openEditMode(els, { ...submitted, status: 'pending' });
    setGlobalError(els, '');
    showSystemMessage('Submitted for review', { variant: 'success' });
    await refreshDrafts(els);
  } catch (error) {
    const message = resolveUgcActionErrorMessage(error, els, 'Failed to submit draft.');
    setGlobalError(els, message, { retry: () => submitDraft(els) });
    setFormState(els, 'server');
    showSystemMessage(message, { variant: 'warning' });
  } finally {
    hideLoading();
    setUgcBusyState(els, false);
  }
}

async function deleteActiveDraft(els) {
  if (uiState.ugcBusy) return;
  if (!ensureOnlineAction()) {
    setGlobalError(els, 'You are offline. Cannot delete draft.');
    return;
  }

  const id = uiState.activeDraftId;
  if (!id) return;

  setUgcBusyState(els, true, els.deleteBtn);
  setGlobalError(els, '');
  showLoading();
  try {
    await requestDraftApi([`/api/drafts/${id}`, `/drafts/${id}`], { method: 'DELETE' }, 'Failed to delete draft.');
    uiState.drafts = uiState.drafts.filter((draft) => String(draft.id) !== String(id));
    openCreateMode(els);
    renderDraftList(els);
    setGlobalError(els, '');
    showSystemMessage('Draft deleted', { variant: 'success' });
  } catch (error) {
    const message = resolveUgcActionErrorMessage(error, els, 'Failed to delete draft.');
    setGlobalError(els, message, { retry: () => deleteActiveDraft(els) });
    showSystemMessage(message, { variant: 'warning' });
  } finally {
    hideLoading();
    setUgcBusyState(els, false);
  }
}

async function requestDraftApi(paths, options, fallbackMessage) {
  let lastError;

  for (const path of paths) {
    try {
      const response = await fetchWithAuth(path, options);

      if (response.ok) {
        if (response.status === 204) return { ok: true };
        return await response.json();
      }

      if (response.status === 404 || response.status === 405) {
        lastError = await buildApiError(response, fallbackMessage);
        continue;
      }

      throw await buildApiError(response, fallbackMessage);
    } catch (error) {
      lastError = error;
      if (error?.status === 404 || error?.status === 405) continue;
      throw error;
    }
  }

  throw lastError || new Error(fallbackMessage);
}

function requireAuthForUgc(els) {
  if (getCurrentUser()) return true;
  uiState.pendingAfterLogin = 'open-ugc';
  openModal(els.loginModal);
  setGlobalError(els, 'Please login to continue.');
  showSystemMessage('Please login to continue.', { variant: 'warning' });
  return false;
}

function validateClientPayload(payload) {
  const errors = {};

  if (!payload.name_ru) errors.name_ru = 'name_ru is required';
  if (!payload.date_start) errors.date_start = 'date_start is required';
  if (!payload.source_url) errors.source_url = 'source_url is required';

  const latitude = parseOptionalNumber(payload.latitude);
  const longitude = parseOptionalNumber(payload.longitude);

  if ((latitude === null) !== (longitude === null)) {
    errors.latitude = 'latitude and longitude should be filled together';
    errors.longitude = 'latitude and longitude should be filled together';
  }

  if (latitude !== null && (Number.isNaN(latitude) || latitude < -90 || latitude > 90)) {
    errors.latitude = 'latitude should be in range -90..90';
  }

  if (longitude !== null && (Number.isNaN(longitude) || longitude < -180 || longitude > 180)) {
    errors.longitude = 'longitude should be in range -180..180';
  }

  if (payload.title_short.length > 120) {
    errors.title_short = 'title_short must be <= 120';
  }

  if (payload.description.length > 2000) {
    errors.description = 'description must be <= 2000';
  }

  if (payload.coordinates_confidence && !CONFIDENCE_ALLOWED.has(payload.coordinates_confidence)) {
    errors.coordinates_confidence = 'coordinates_confidence must be exact/approximate/conditional';
  }

  if (Object.keys(errors).length > 0) {
    return { valid: false, errors, data: payload };
  }

  return {
    valid: true,
    errors,
    data: {
      ...payload,
      coords: latitude !== null && longitude !== null ? [longitude, latitude] : null
    }
  };
}

function collectDraftPayload(form) {
  const payload = {};
  FORM_FIELDS.forEach((field) => {
    const node = form[field];
    payload[field] = node ? String(node.value || '').trim() : '';
  });

  payload.tags = parseTags(payload.tags);
  return payload;
}

function parseTags(value) {
  if (!value) return [];
  return String(value)
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function parseOptionalNumber(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  const parsed = Number.parseFloat(String(value).replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : NaN;
}

function renderFieldErrors(form, container, errors) {
  container.replaceChildren();
  form.querySelectorAll('.field-error-message').forEach((node) => node.remove());
  form.querySelectorAll('.is-invalid').forEach((node) => node.classList.remove('is-invalid'));

  Object.entries(errors || {}).forEach(([field, message]) => {
    const row = document.createElement('div');
    row.className = 'field-error';
    setText(row, `${toSafeText(field)}: ${toSafeText(message)}`);
    container.appendChild(row);

    const input = form[field];
    if (!input) return;
    input.classList.add('is-invalid');

    const inline = document.createElement('div');
    inline.className = 'field-error-message';
    setText(inline, message);
    input.insertAdjacentElement('afterend', inline);
  });
}

function syncAuthUI(els) {
  const loggedIn = Boolean(getCurrentUser());
  if (els.authButtons) els.authButtons.hidden = loggedIn;
  if (els.profilePanel) els.profilePanel.hidden = !loggedIn;
}

function hydrateLayerSelect(form, layers) {
  const select = form?.querySelector('select[name="layer_id"]');
  if (!select) return;

  const known = new Set(Array.from(select.options).map((option) => option.value));
  (Array.isArray(layers) ? layers : []).forEach((layer) => {
    const layerId = String(layer?.layer_id || layer?.id || '').trim();
    if (!layerId || known.has(layerId)) return;
    known.add(layerId);
    const option = document.createElement('option');
    option.value = layerId;
    setText(option, layer?.name_ru || layerId);
    select.appendChild(option);
  });
}

function openModal(node) {
  if (!node) return;
  node.hidden = false;
  document.body.classList.add('modal-open');
}

function closeModal(node) {
  if (!node) return;
  node.hidden = true;
  const hasVisibleModal = Array.from(document.querySelectorAll('.modal')).some((modal) => !modal.hidden);
  if (!hasVisibleModal) document.body.classList.remove('modal-open');
}

function setLoading(container, loading) {
  container?.querySelectorAll('button,input,select,textarea').forEach((node) => {
    if (node.tagName === 'BUTTON') node.disabled = loading;
  });
}

function setUgcBusyState(els, busy, control = null) {
  uiState.ugcBusy = Boolean(busy);
  if (busy) {
    uiState.busyControl = control || null;
    if (uiState.busyControl) setButtonBusy(uiState.busyControl, true);
    els.form?.classList.add('ugc-form-busy');
    els.form?.setAttribute('aria-busy', 'true');
  } else {
    if (uiState.busyControl) setButtonBusy(uiState.busyControl, false);
    uiState.busyControl = null;
    els.form?.classList.remove('ugc-form-busy');
    els.form?.removeAttribute('aria-busy');
  }

  syncModeUI(els, getActiveDraft());
}

function getActiveDraft() {
  if (!uiState.activeDraftId) return null;
  return uiState.drafts.find((draft) => String(draft?.id) === String(uiState.activeDraftId)) || null;
}

function setGlobalError(els, message, { retry = null } = {}) {
  const host = ensureUgcErrorHost(els);
  if (!host) return;

  const safeMessage = String(message || '').trim();
  const visible = Boolean(safeMessage);
  host.hidden = !visible;
  host.setAttribute('aria-live', 'assertive');
  host.setAttribute('role', 'alert');

  if (!visible) {
    host.replaceChildren();
    return;
  }

  host.replaceChildren(createInlineStateBlock({
    variant: 'error',
    title: 'Action required',
    message: safeMessage,
    actionLabel: typeof retry === 'function' ? 'Retry' : '',
    onAction: retry
  }));
}

function ensureUgcErrorHost(els) {
  if (els.ugcGlobalError) return els.ugcGlobalError;
  if (!els.ugcPanel) return null;

  const host = document.createElement('div');
  host.id = 'ugc-global-error';
  host.className = 'ugc-error-state ugc-error-banner';
  host.hidden = true;

  const anchor = els.form || els.ugcDraftsList || els.ugcPanel.firstElementChild;
  if (anchor?.parentNode) {
    anchor.parentNode.insertBefore(host, anchor);
  } else {
    els.ugcPanel.appendChild(host);
  }

  els.ugcGlobalError = host;
  return host;
}

function resolveUgcActionErrorMessage(error, els, fallbackMessage) {
  const authMessage = handleAuthError(error, els);
  if (authMessage) return authMessage;

  const serverMessage = extractServerErrorMessage(error);
  if (serverMessage) return serverMessage;

  return normalizeAppError(error, fallbackMessage).message || fallbackMessage;
}

function extractServerErrorMessage(error) {
  const payload = error?.payload;
  const candidates = [
    error?.message,
    payload?.message,
    payload?.error,
    payload?.error?.message,
    payload?.detail,
    payload?.details?.message
  ];

  for (const value of candidates) {
    const message = String(value || '').trim();
    if (message) return message;
  }

  return '';
}

function handleAuthError(error, els) {
  if (error?.status !== 401 && !String(error?.message || '').toLowerCase().includes('auth')) {
    return '';
  }

  uiState.pendingAfterLogin = 'open-ugc';
  openModal(els.loginModal);
  return 'Session expired. Please sign in again.';
}

function upsertDraft(draft) {
  if (!draft || !draft.id) return;
  const idx = uiState.drafts.findIndex((item) => String(item.id) === String(draft.id));
  if (idx < 0) {
    uiState.drafts.unshift(draft);
    return;
  }
  uiState.drafts[idx] = { ...uiState.drafts[idx], ...draft };
}

function formatUpdatedAt(value) {
  if (!value) return 'updated_at: —';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return `updated_at: ${String(value)}`;
  return `updated_at: ${date.toISOString().slice(0, 16).replace('T', ' ')}`;
}
