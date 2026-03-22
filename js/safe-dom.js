export function toSafeText(value, fallback = '') {
  if (value === null || value === undefined) return fallback;
  const text = String(value);
  return text || fallback;
}

export function setText(node, value, fallback = '') {
  if (!node) return node;
  node.textContent = toSafeText(value, fallback);
  return node;
}

export function appendText(parent, value, fallback = '') {
  if (!parent) return null;
  const textNode = document.createTextNode(toSafeText(value, fallback));
  parent.appendChild(textNode);
  return textNode;
}

export function isSafeHttpUrl(value, { allowRelative = false } = {}) {
  if (typeof value !== 'string') return false;
  const trimmed = value.trim();
  if (!trimmed) return false;

  if (allowRelative && trimmed.startsWith('/')) {
    return !trimmed.startsWith('//');
  }

  try {
    const url = new URL(trimmed, window.location.origin);
    if (allowRelative && url.origin === window.location.origin && trimmed.startsWith('/')) return true;
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch (_error) {
    return false;
  }
}

export function normalizeSafeUrl(value, options = {}) {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!isSafeHttpUrl(trimmed, options)) return null;

  if (options.allowRelative && trimmed.startsWith('/')) return trimmed;

  try {
    return new URL(trimmed, window.location.origin).toString();
  } catch (_error) {
    return null;
  }
}

export function setSafeLink(link, value, options = {}) {
  const safeUrl = normalizeSafeUrl(value, options);
  if (!link || !safeUrl) return null;
  link.href = safeUrl;
  link.rel = 'noopener noreferrer';
  if (options.newTab !== false) link.target = '_blank';
  return safeUrl;
}

export function createTextElement(tagName, value, { className = '', fallback = '' } = {}) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  setText(node, value, fallback);
  return node;
}
