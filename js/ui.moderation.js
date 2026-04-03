import { buildApiError, canModerate, fetchWithAuth, getCurrentUser } from './auth.js';
import { createTextElement, normalizeSafeUrl, setSafeImageSource, setSafeLink, toSafeText } from './safe-dom.js';
import { createInlineStateBlock, normalizeAppError, showSystemMessage, ensureOnlineAction, setButtonBusy } from './ux.js';

let moderationInitialized = false;

const moderationState = {
  queue: [],
  filteredQueue: [],
  selectedDraftId: null,
  isAllowed: false,
  isOpen: false,
  queueState: 'idle',
  actionState: 'idle',
  queueError: '',
  actionError: '',
  actionMessage: '',
  search: '',
  sort: 'newest',
  rejectReason: '',
  activeModal: null,
  mobileView: 'list'
};

const STATUS = {
  IDLE: 'idle',
  LOADING_QUEUE: 'loading_queue',
  QUEUE_LOADED: 'queue_loaded',
  QUEUE_EMPTY: 'queue_empty',
  REVIEW_SELECTED: 'review_selected',
  NO_ITEM_SELECTED: 'no_item_selected',
  APPROVING: 'approving',
  REJECTING: 'rejecting',
  APPROVE_SUCCESS: 'approve_success',
  REJECT_SUCCESS: 'reject_success',
  ERROR: 'error',
  FORBIDDEN: 'forbidden',
  UNAUTHORIZED: 'unauthorized'
};

export async function initModerationUI() {
  if (moderationInitialized) return;
  moderationInitialized = true;

  bindModerationEvents();
  updateModeratorAccess();
  renderModerationWorkspace();

  window.addEventListener('artemis:auth-changed', async () => {
    updateModeratorAccess();
    renderModerationWorkspace();
    if (moderationState.isAllowed) {
      await loadModerationQueue();
    }
  }, { passive: true });

  if (moderationState.isAllowed) await loadModerationQueue();
}

async function loadModerationQueue() {
  if (!moderationState.isAllowed) return [];

  moderationState.queueState = STATUS.LOADING_QUEUE;
  moderationState.queueError = '';
  renderModerationWorkspace();

  try {
    const response = await fetchWithAuth('/moderation/queue', { method: 'GET' });
    const drafts = await parseModerationResponse(response, 'Failed to load moderation queue.');

    moderationState.queue = Array.isArray(drafts) ? drafts : [];
    moderationState.queueState = moderationState.queue.length ? STATUS.QUEUE_LOADED : STATUS.QUEUE_EMPTY;
    moderationState.actionError = '';
    moderationState.actionMessage = '';

    if (!moderationState.queue.length) {
      moderationState.selectedDraftId = null;
    } else if (!findDraftById(moderationState.selectedDraftId)) {
      moderationState.selectedDraftId = String(moderationState.queue[0]?.id ?? '');
    }

    applyQueueFilters();
    renderModerationWorkspace();
    return moderationState.queue.slice();
  } catch (error) {
    if (error?.status === 401 || error?.responseStatus === 401) {
      moderationState.queueState = STATUS.UNAUTHORIZED;
      moderationState.queueError = 'Your session expired. Please sign in again.';
      moderationState.queue = [];
      moderationState.filteredQueue = [];
      moderationState.selectedDraftId = null;
    } else if (error?.status === 403 || error?.responseStatus === 403) {
      moderationState.queueState = STATUS.FORBIDDEN;
      moderationState.queueError = 'You do not have access to this action.';
      moderationState.queue = [];
      moderationState.filteredQueue = [];
      moderationState.selectedDraftId = null;
      moderationState.isAllowed = false;
    } else {
      moderationState.queueState = STATUS.ERROR;
      moderationState.queueError = error?.message || 'Failed to load moderation queue.';
    }
    renderModerationWorkspace();
    throw error;
  }
}

async function approveSelectedDraft() {
  const draft = getSelectedDraft();
  if (!draft || moderationState.actionState === STATUS.APPROVING || moderationState.actionState === STATUS.REJECTING) return;

  moderationState.actionState = STATUS.APPROVING;
  moderationState.actionError = '';
  moderationState.actionMessage = '';
  renderModerationWorkspace();

  try {
    const response = await fetchWithAuth(`/moderation/${draft.id}/approve`, { method: 'POST' });
    await parseModerationResponse(response, 'Failed to approve draft.');

    removeDraftFromQueue(String(draft.id));
    moderationState.actionState = STATUS.APPROVE_SUCCESS;
    moderationState.actionMessage = 'Draft approved.';
    showSystemMessage('Approved', { variant: 'success' });
    renderModerationWorkspace();
  } catch (error) {
    moderationState.actionState = STATUS.ERROR;
    moderationState.actionError = normalizeAppError(error, 'Failed to approve draft.').message;
    showSystemMessage(moderationState.actionError, { variant: 'warning' });
    renderModerationWorkspace();
  }
}

async function rejectSelectedDraft() {
  const draft = getSelectedDraft();
  if (!draft || moderationState.actionState === STATUS.APPROVING || moderationState.actionState === STATUS.REJECTING) return;

  moderationState.actionState = STATUS.REJECTING;
  moderationState.actionError = '';
  moderationState.actionMessage = '';
  renderModerationWorkspace();

  try {
    const payload = moderationState.rejectReason.trim();
    const options = { method: 'POST' };
    if (payload) {
      options.headers = new Headers({ 'Content-Type': 'application/json' });
      options.body = JSON.stringify({ reason: payload });
    }

    const response = await fetchWithAuth(`/moderation/${draft.id}/reject`, options);
    await parseModerationResponse(response, 'Failed to reject draft.');

    removeDraftFromQueue(String(draft.id));
    moderationState.actionState = STATUS.REJECT_SUCCESS;
    moderationState.actionMessage = 'Draft rejected.';
    moderationState.rejectReason = '';
    moderationState.activeModal = null;
    showSystemMessage('Rejected', { variant: 'success' });
    renderModerationWorkspace();
  } catch (error) {
    moderationState.actionState = STATUS.ERROR;
    moderationState.actionError = normalizeAppError(error, 'Failed to reject draft.').message;
    showSystemMessage(moderationState.actionError, { variant: 'warning' });
    renderModerationWorkspace();
  }
}

function bindModerationEvents() {
  document.addEventListener('click', onModerationClick);
  document.addEventListener('click', onModerationOutsideClick);
  document.addEventListener('keydown', onModerationKeydown);

  const searchInput = document.getElementById('moderation-search');
  const sortSelect = document.getElementById('moderation-sort');
  const clearSearchBtn = document.getElementById('moderation-clear-search');

  searchInput?.addEventListener('input', (event) => {
    moderationState.search = String(event.target?.value || '');
    applyQueueFilters();
    renderModerationWorkspace();
  });

  sortSelect?.addEventListener('change', (event) => {
    moderationState.sort = String(event.target?.value || 'newest');
    applyQueueFilters();
    renderModerationWorkspace();
  });

  clearSearchBtn?.addEventListener('click', () => {
    moderationState.search = '';
    if (searchInput) searchInput.value = '';
    applyQueueFilters();
    renderModerationWorkspace();
  });
}

function onModerationOutsideClick(event) {
  const workspace = document.getElementById('moderation-workspace');
  if (!workspace || workspace.hidden || !moderationState.isOpen) return;

  const target = event.target;
  const rejectModal = document.getElementById('moderation-reject-modal');
  if (rejectModal && !rejectModal.hidden) {
    const withinRejectCard = target.closest?.('.moderation-reject-card');
    if (!withinRejectCard) {
      moderationState.activeModal = null;
      moderationState.rejectReason = '';
      renderModerationWorkspace();
    }
    return;
  }

  const insideWorkspace = workspace.contains(target);
  const opener = target.closest?.('[data-moderation-action=\"toggle-workspace\"]');
  if (!insideWorkspace && !opener) {
    moderationState.isOpen = false;
    moderationState.mobileView = 'list';
    renderModerationWorkspace();
  }
}

function onModerationClick(event) {
  const actionEl = event.target.closest('[data-moderation-action]');
  if (!actionEl) return;

  const action = actionEl.dataset.moderationAction;

  if (action === 'toggle-workspace') {
    if (!moderationState.isAllowed) return;
    moderationState.isOpen = !moderationState.isOpen;
    moderationState.activeModal = null;
    moderationState.mobileView = 'list';
    if (moderationState.isOpen) {
      document.dispatchEvent(new CustomEvent('artemis:overlay-open', { detail: { source: 'moderation' } }));
      if (moderationState.queueState === STATUS.IDLE) {
        loadModerationQueue().catch((error) => {
          const message = normalizeAppError(error, 'Failed to load moderation queue.').message;
          showSystemMessage(message, { variant: 'warning' });
        });
      }
    }
    renderModerationWorkspace();
    return;
  }

  if (action === 'close-workspace') {
    moderationState.isOpen = false;
    moderationState.activeModal = null;
    moderationState.mobileView = 'list';
    renderModerationWorkspace();
    return;
  }

  if (action === 'refresh-queue') {
    if (!ensureOnlineAction()) return;
    loadModerationQueue().catch((error) => {
      const message = normalizeAppError(error, 'Failed to load moderation queue.').message;
      showSystemMessage(message, { variant: 'warning' });
    });
    return;
  }

  if (action === 'mobile-back') {
    moderationState.mobileView = 'list';
    renderModerationWorkspace();
    return;
  }

  if (action === 'select-draft') {
    const draftId = String(actionEl.dataset.draftId || '');
    moderationState.selectedDraftId = draftId;
    moderationState.queueState = STATUS.REVIEW_SELECTED;
    moderationState.mobileView = 'review';
    moderationState.actionError = '';
    moderationState.actionMessage = '';
    centerMapForDraft(findDraftById(draftId));
    renderModerationWorkspace();
    return;
  }

  if (action === 'approve-draft') {
    if (!ensureOnlineAction()) return;
    approveSelectedDraft();
    return;
  }

  if (action === 'open-reject-modal') {
    moderationState.activeModal = 'reject';
    moderationState.actionError = '';
    renderModerationWorkspace();
    const input = document.getElementById('moderation-reject-reason');
    input?.focus();
    return;
  }

  if (action === 'close-reject-modal') {
    moderationState.activeModal = null;
    moderationState.rejectReason = '';
    renderModerationWorkspace();
    return;
  }

  if (action === 'submit-reject') {
    if (!ensureOnlineAction()) return;
    const reasonInput = document.getElementById('moderation-reject-reason');
    moderationState.rejectReason = String(reasonInput?.value || '').trim();
    rejectSelectedDraft();
  }
}

function onModerationKeydown(event) {
  if (event.defaultPrevented) return;
  if (event.key !== 'Escape') return;

  if (moderationState.activeModal === 'reject') {
    moderationState.activeModal = null;
    moderationState.rejectReason = '';
    renderModerationWorkspace();
    event.preventDefault();
    return;
  }

  if (moderationState.isOpen) {
    moderationState.isOpen = false;
    moderationState.mobileView = 'list';
    renderModerationWorkspace();
    event.preventDefault();
  }
}

function updateModeratorAccess() {
  const user = getCurrentUser();
  moderationState.isAllowed = canModerate(user);

  if (!moderationState.isAllowed) {
    moderationState.isOpen = false;
    moderationState.activeModal = null;
    moderationState.mobileView = 'list';
    moderationState.queue = [];
    moderationState.filteredQueue = [];
    moderationState.selectedDraftId = null;
    moderationState.queueState = STATUS.IDLE;
    moderationState.queueError = '';
  }
}

function applyQueueFilters() {
  const searchText = moderationState.search.trim().toLowerCase();
  moderationState.filteredQueue = moderationState.queue
    .filter((draft) => {
      if (!searchText) return true;
      const name = `${toSafeText(draft?.name_ru, '')} ${toSafeText(draft?.title, '')} ${toSafeText(draft?.title_short, '')}`.toLowerCase();
      return name.includes(searchText);
    })
    .sort((left, right) => {
      const leftTime = getDraftTimestamp(left);
      const rightTime = getDraftTimestamp(right);
      if (moderationState.sort === 'oldest') return leftTime - rightTime;
      return rightTime - leftTime;
    });
}

function removeDraftFromQueue(draftId) {
  moderationState.queue = moderationState.queue.filter((item) => String(item?.id) !== String(draftId));
  applyQueueFilters();

  if (!moderationState.queue.length) {
    moderationState.selectedDraftId = null;
    moderationState.queueState = STATUS.QUEUE_EMPTY;
    return;
  }

  const stillSelected = findDraftById(moderationState.selectedDraftId);
  if (stillSelected) {
    moderationState.queueState = STATUS.REVIEW_SELECTED;
    moderationState.mobileView = 'review';
    return;
  }

  moderationState.selectedDraftId = String(moderationState.filteredQueue[0]?.id ?? moderationState.queue[0]?.id ?? '');
  moderationState.queueState = STATUS.REVIEW_SELECTED;
}

function getSelectedDraft() {
  return findDraftById(moderationState.selectedDraftId);
}

function findDraftById(id) {
  return moderationState.queue.find((draft) => String(draft?.id) === String(id));
}

function renderModerationWorkspace() {
  const toggleButton = document.getElementById('moderation-toggle-btn');
  const workspace = document.getElementById('moderation-workspace');
  const listNode = document.getElementById('moderation-list');
  const reviewNode = document.getElementById('moderation-review');
  const queueStateNode = document.getElementById('moderation-queue-state');

  if (!toggleButton || !workspace || !listNode || !reviewNode || !queueStateNode) return;

  toggleButton.hidden = !moderationState.isAllowed;
  toggleButton.setAttribute('aria-expanded', moderationState.isOpen ? 'true' : 'false');
  toggleButton.classList.toggle('is-active', moderationState.isOpen);
  toggleButton.dataset.activeCount = moderationState.search.trim() ? '1' : '';

  workspace.hidden = !moderationState.isAllowed;
  workspace.classList.toggle('is-open', moderationState.isAllowed && moderationState.isOpen);
  workspace.setAttribute('aria-hidden', moderationState.isAllowed && moderationState.isOpen ? 'false' : 'true');
  workspace.dataset.state = moderationState.isAllowed && moderationState.isOpen ? 'open' : 'closed';

  const isMobile = window.matchMedia('(max-width: 720px)').matches;
  workspace.classList.toggle('is-mobile-review', isMobile && moderationState.mobileView === 'review');

  renderQueueState(queueStateNode);
  renderPendingList(listNode);
  renderReviewPanel(reviewNode);
  renderRejectModal();
}

function renderQueueState(node) {
  node.replaceChildren();

  if (!moderationState.isOpen) {
    node.appendChild(createInlineState('Moderation workspace is closed.'));
    return;
  }

  if (moderationState.queueState === STATUS.LOADING_QUEUE) {
    node.appendChild(createInlineState('Loading moderation queue… Please wait.'));
    return;
  }

  if (moderationState.queueState === STATUS.QUEUE_EMPTY) {
    node.appendChild(createInlineState('Moderation queue is empty. New submitted drafts will appear here.'));
    return;
  }

  if (moderationState.queueState === STATUS.UNAUTHORIZED || moderationState.queueState === STATUS.FORBIDDEN || moderationState.queueState === STATUS.ERROR) {
    node.appendChild(createInlineError(moderationState.queueError || 'Moderation queue is unavailable.', moderationState.queueState === STATUS.ERROR ? () => {
      if (!ensureOnlineAction()) return;
      loadModerationQueue().catch(() => {});
    } : null));
  }
}

function renderPendingList(listNode) {
  listNode.replaceChildren();

  if (!moderationState.isOpen || !moderationState.isAllowed) return;
  if (moderationState.queueState === STATUS.LOADING_QUEUE) return;
  if (!moderationState.queue.length) return;

  const data = moderationState.filteredQueue;
  if (!data.length) {
    listNode.appendChild(createInlineStateBlock({
      variant: 'warning',
      title: 'No matches',
      message: `No drafts match “${moderationState.search.trim()}”.`,
      actionLabel: 'Clear search',
      onAction: () => {
        moderationState.search = '';
        const input = document.getElementById('moderation-search');
        if (input) input.value = '';
        applyQueueFilters();
        renderModerationWorkspace();
      }
    }));
    return;
  }

  data.forEach((draft) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'moderation-item';
    button.dataset.moderationAction = 'select-draft';
    button.dataset.draftId = String(draft?.id || '');
    button.classList.toggle('is-selected', String(draft?.id) === String(moderationState.selectedDraftId));

    const heading = document.createElement('div');
    heading.className = 'moderation-item-head';
    heading.append(
      createTextElement('strong', resolveDraftTitle(draft), { fallback: 'Untitled draft' }),
      createStatusBadge(toSafeText(draft?.status, 'pending'))
    );

    const meta = createTextElement('p', buildListMeta(draft), { className: 'moderation-item-meta', fallback: 'No metadata' });

    button.append(heading, meta);
    listNode.appendChild(button);
  });
}

function renderReviewPanel(container) {
  container.replaceChildren();

  if (!moderationState.isOpen || !moderationState.isAllowed) return;

  if (!moderationState.queue.length) {
    container.appendChild(createInlineState('No draft selected for review. Choose an item from the left list when available.'));
    return;
  }

  const draft = getSelectedDraft();
  if (!draft) {
    container.appendChild(createInlineState('No item selected.'));
    moderationState.queueState = STATUS.NO_ITEM_SELECTED;
    return;
  }

  moderationState.queueState = STATUS.REVIEW_SELECTED;

  const hero = document.createElement('section');
  hero.className = 'moderation-hero';
  const imageUrl = normalizeSafeUrl(draft?.image_url, { allowRelative: true });
  if (imageUrl) {
    const img = document.createElement('img');
    setSafeImageSource(img, imageUrl, { allowRelative: true });
    img.alt = toSafeText(resolveDraftTitle(draft), 'Draft preview');
    hero.appendChild(img);
  } else {
    hero.appendChild(createTextElement('div', 'No media preview', { className: 'moderation-hero-empty' }));
  }

  const header = document.createElement('section');
  header.className = 'moderation-review-header';
  const top = document.createElement('div');
  top.className = 'moderation-review-title-row';
  top.append(
    createTextElement('h3', resolveDraftTitle(draft), { fallback: 'Untitled draft' }),
    createStatusBadge(toSafeText(draft?.status, 'pending'))
  );

  const details = document.createElement('div');
  details.className = 'moderation-review-sub';
  details.append(
    createMetaPill(`Updated ${formatDateLabel(draft?.updated_at || draft?.created_at)}`),
    createMetaPill(`Layer ${toSafeText(draft?.layer_id || draft?.layer_type, 'n/a')}`),
    createMetaPill(`Type ${toSafeText(draft?.layer_type || draft?.type, 'n/a')}`)
  );
  header.append(top, details);

  const main = document.createElement('section');
  main.className = 'moderation-review-main';
  main.append(
    createReviewBlock('Description', draft?.description, 'No description provided.'),
    createReviewBlock('title_short', draft?.title_short, 'No short title provided.')
  );

  const metadata = document.createElement('section');
  metadata.className = 'moderation-review-meta';
  metadata.append(
    createMetadataRow('source_url', draft?.source_url, { link: true }),
    createMetadataRow('image_url', draft?.image_url, { link: true, allowRelative: true }),
    createMetadataRow('coordinates', formatCoordinates(draft)),
    createMetadataRow('coordinates_confidence', draft?.coordinates_confidence),
    createMetadataRow('tags', formatTags(draft?.tags))
  );

  const actions = document.createElement('section');
  actions.className = 'moderation-review-actions';
  const approveButton = document.createElement('button');
  approveButton.type = 'button';
  approveButton.dataset.moderationAction = 'approve-draft';
  approveButton.className = 'moderation-approve-btn';
  approveButton.disabled = moderationState.actionState === STATUS.APPROVING || moderationState.actionState === STATUS.REJECTING;
  approveButton.textContent = 'Approve';

  const rejectButton = document.createElement('button');
  rejectButton.type = 'button';
  rejectButton.dataset.moderationAction = 'open-reject-modal';
  rejectButton.className = 'moderation-reject-btn';
  rejectButton.disabled = moderationState.actionState === STATUS.APPROVING || moderationState.actionState === STATUS.REJECTING;
  rejectButton.textContent = 'Reject';
  setButtonBusy(approveButton, moderationState.actionState === STATUS.APPROVING, { idle: 'Approve', busy: 'Approving…' });
  setButtonBusy(rejectButton, moderationState.actionState === STATUS.REJECTING, { idle: 'Reject', busy: 'Rejecting…' });

  actions.append(approveButton, rejectButton);

  if (moderationState.actionMessage) actions.appendChild(createInlineState(moderationState.actionMessage));
  if (moderationState.actionError) actions.appendChild(createInlineError(moderationState.actionError));

  container.append(hero, header, main, metadata, actions);
}

function renderRejectModal() {
  const modal = document.getElementById('moderation-reject-modal');
  const textarea = document.getElementById('moderation-reject-reason');
  if (!modal || !textarea) return;

  const open = moderationState.isAllowed && moderationState.isOpen && moderationState.activeModal === 'reject';
  modal.hidden = !open;
  modal.setAttribute('aria-hidden', open ? 'false' : 'true');
  modal.dataset.state = open ? 'open' : 'closed';
  textarea.value = moderationState.rejectReason;
}

function createInlineState(message) {
  return createInlineStateBlock({ variant: 'info', message });
}

function createInlineError(message, onRetry = null) {
  return createInlineStateBlock({
    variant: 'error',
    title: 'Action unavailable',
    message,
    actionLabel: onRetry ? 'Retry' : '',
    onAction: onRetry
  });
}

function createStatusBadge(status) {
  const badge = document.createElement('span');
  const normalized = String(status || 'pending').toLowerCase();
  badge.className = 'moderation-status-badge ui-badge';
  badge.classList.toggle('is-success', normalized === 'approved');
  badge.classList.toggle('is-error', normalized === 'rejected');
  badge.classList.toggle('is-warning', normalized === 'pending');
  badge.textContent = toSafeText(normalized, 'pending');
  return badge;
}

function createMetaPill(text) {
  return createTextElement('span', text, { className: 'moderation-meta-pill' });
}

function createReviewBlock(title, value, fallback = '—') {
  const section = document.createElement('article');
  section.className = 'moderation-review-block';
  section.append(createTextElement('h4', title), createTextElement('p', toSafeText(value, fallback)));
  return section;
}

function createMetadataRow(label, value, options = {}) {
  const row = document.createElement('div');
  row.className = 'moderation-meta-row';
  row.appendChild(createTextElement('span', label, { className: 'moderation-meta-label' }));

  if (options.link) {
    const link = document.createElement('a');
    const linked = setSafeLink(link, value, { allowRelative: options.allowRelative, newTab: true });
    if (linked) {
      link.textContent = linked;
      row.appendChild(link);
      return row;
    }
  }

  row.appendChild(createTextElement('span', toSafeText(value, '—'), { className: 'moderation-meta-value' }));
  return row;
}

function centerMapForDraft(draft) {
  if (!draft) return;
  const coords = extractCoordinates(draft);
  if (!coords) return;

  const map = window.__ARTEMIS_MAP;
  if (!map?.flyTo) return;

  map.flyTo({ center: coords, zoom: Math.max(Number(map.getZoom?.() || 5), 7), essential: false });
}

function extractCoordinates(draft) {
  const longitude = Number(draft?.longitude ?? draft?.lng ?? draft?.lon);
  const latitude = Number(draft?.latitude ?? draft?.lat);
  if (Number.isFinite(longitude) && Number.isFinite(latitude)) return [longitude, latitude];

  const coords = draft?.geometry?.coordinates;
  if (Array.isArray(coords) && coords.length >= 2) {
    const lon = Number(coords[0]);
    const lat = Number(coords[1]);
    if (Number.isFinite(lon) && Number.isFinite(lat)) return [lon, lat];
  }
  return null;
}

function formatCoordinates(draft) {
  const coords = extractCoordinates(draft);
  if (!coords) return '—';
  return `${coords[1].toFixed(5)}, ${coords[0].toFixed(5)}`;
}

function formatTags(tags) {
  if (Array.isArray(tags)) return tags.filter(Boolean).map((tag) => String(tag).trim()).filter(Boolean).join(', ') || '—';
  const raw = toSafeText(tags, '').trim();
  return raw || '—';
}

function resolveDraftTitle(draft) {
  return toSafeText(draft?.name_ru, '').trim()
    || toSafeText(draft?.title, '').trim()
    || toSafeText(draft?.title_short, '').trim()
    || 'Untitled draft';
}

function buildListMeta(draft) {
  const updated = formatDateLabel(draft?.updated_at || draft?.created_at);
  const layer = toSafeText(draft?.layer_id || draft?.layer_type, 'n/a');
  return `${layer} • ${updated}`;
}

function formatDateLabel(value) {
  if (!value) return 'n/a';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return toSafeText(value, 'n/a');
  return parsed.toLocaleString();
}

function getDraftTimestamp(draft) {
  const candidate = draft?.updated_at || draft?.created_at;
  const ts = new Date(candidate || 0).getTime();
  return Number.isFinite(ts) ? ts : 0;
}

async function parseModerationResponse(response, fallbackMessage) {
  let data = null;

  try {
    data = await response.json();
  } catch (_error) {
    data = null;
  }

  if (response.ok) return data;
  response.json = async () => data;
  throw await buildApiError(response, fallbackMessage);
}
