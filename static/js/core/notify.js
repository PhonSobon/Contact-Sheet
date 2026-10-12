// Toast notifications. Every error in the app ends up here, so the user always
// sees it — even when the tool's own status line is scrolled out of view.

const ICONS = {
  error: '<path d="M12 8v5"/><path d="M12 16.5v.01"/><path d="M10.3 3.9L2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  success: '<path d="M20 6L9 17l-5-5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.5v.01"/>',
};
const TITLES = { error: 'Something went wrong', success: 'Done', info: 'Heads up' };
const DURATION = { error: 8000, success: 3500, info: 5000 };
const MAX_TOASTS = 4;

let region = null;

function getRegion(){
  if(region) return region;
  region = document.createElement('div');
  region.className = 'toast-region';
  region.setAttribute('aria-live', 'polite');
  document.body.appendChild(region);
  return region;
}

function dismiss(toast){
  if(!toast.isConnected || toast.classList.contains('leaving')) return;
  toast.classList.add('leaving');
  setTimeout(()=> toast.remove(), 200);
}

/**
 * Shows a toast. type: 'error' | 'success' | 'info'.
 * Repeating the same message refreshes the existing toast instead of stacking.
 */
export function notify(message, type = 'info', { title } = {}){
  if(!message) return;
  const root = getRegion();
  const key = type + '|' + message;
  const existing = [...root.children].find(t=> t.dataset.key === key && !t.classList.contains('leaving'));
  if(existing){
    clearTimeout(existing._timer);
    existing._timer = setTimeout(()=> dismiss(existing), DURATION[type]);
    existing.classList.remove('bump'); void existing.offsetWidth; existing.classList.add('bump');
    return existing;
  }

  const toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.dataset.key = key;
  toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
  toast.innerHTML = `
    <span class="toast-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[type] || ICONS.info}</svg></span>
    <div class="toast-body"><div class="toast-title"></div><div class="toast-msg"></div></div>
    <button type="button" class="toast-close" aria-label="Dismiss notification">✕</button>
    <span class="toast-timer"></span>`;
  toast.querySelector('.toast-title').textContent = title || TITLES[type] || TITLES.info;
  toast.querySelector('.toast-msg').textContent = message;
  toast.querySelector('.toast-close').addEventListener('click', ()=> dismiss(toast));
  toast.querySelector('.toast-timer').style.animationDuration = DURATION[type] + 'ms';

  // Pause the countdown while the user is reading (hover / keyboard focus).
  const start = ()=>{ toast._timer = setTimeout(()=> dismiss(toast), DURATION[type]); toast.classList.remove('paused'); };
  const pause = ()=>{ clearTimeout(toast._timer); toast.classList.add('paused'); };
  toast.addEventListener('mouseenter', pause);
  toast.addEventListener('mouseleave', start);
  toast.addEventListener('focusin', pause);
  toast.addEventListener('focusout', start);

  root.appendChild(toast);
  while(root.children.length > MAX_TOASTS) root.firstElementChild.remove();
  start();
  return toast;
}

export const notifyError = (message, opts)=> notify(message, 'error', opts);
export const notifySuccess = (message, opts)=> notify(message, 'success', opts);

/**
 * Updates a tool's inline status line, and raises a toast for errors and
 * successes. kind: undefined (progress text) | 'error' | 'ok'.
 */
export function showStatus(statusEl, msg, kind){
  statusEl.textContent = msg || '';
  statusEl.className = 'status-line' + (kind ? ' ' + kind : '');
  if(!msg) return;
  if(kind === 'error') notifyError(msg);
  else if(kind === 'ok') notifySuccess(msg === 'Done.' ? 'Your file is ready.' : msg);
}

/** Last-resort net: anything that throws without being handled still gets shown. */
export function installGlobalErrorHandlers(){
  window.addEventListener('unhandledrejection', e=>{
    const msg = e.reason && e.reason.message ? e.reason.message : String(e.reason || 'Unknown error');
    notifyError(msg, { title: 'Unexpected error' });
  });
  window.addEventListener('error', e=>{
    if(!e.message) return;  // resource load errors (e.g. an image) carry no message
    notifyError(e.message, { title: 'Unexpected error' });
  });
}
