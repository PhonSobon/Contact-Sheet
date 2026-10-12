// Talking to the FastAPI backend.

// Same origin: FastAPI serves this page AND the /api/* routes, so no
// cross-origin base URL is needed. Leave as '' unless you split the
// frontend onto a different host later.
export const API_BASE = '';

/**
 * fetch() for the API. A network failure (server down, no internet, CORS)
 * makes fetch throw a bare "Failed to fetch"; turn that into a message a
 * person can act on.
 */
export async function apiFetch(path, options){
  try{
    return await fetch(API_BASE + path, options);
  }catch(err){
    if(err && err.name === 'AbortError') throw err;
    throw new Error(navigator.onLine === false
      ? 'You appear to be offline. Check your internet connection and try again.'
      : 'Could not reach the server. Make sure it is running, then try again.');
  }
}

/**
 * Turns a failed response into a readable message. The API always sends
 * JSON {detail}, but a hosting proxy (upload too large, timeout) may answer
 * with plain text/HTML, so fall back to the HTTP status in that case.
 */
export async function readError(res, fallback){
  try{
    const body = await res.clone().json();
    const detail = body && body.detail;
    if(typeof detail === 'string' && detail) return detail;
    if(Array.isArray(detail) && detail.length) return detail.map(d=> d.msg || String(d)).join('; ');
  }catch(_){}
  if(res.status === 413) return fallback + ' The upload is too large for the server (HTTP 413) — try fewer or smaller files.';
  if(res.status === 504 || res.status === 408) return fallback + ' The server took too long (HTTP ' + res.status + ') — try fewer pages at once.';
  return fallback + ' (HTTP ' + res.status + ')';
}

/** Checks the backend once at startup; returns true when it answers. */
export async function checkHealth(){
  try{
    const res = await fetch(API_BASE + '/api/health', { cache: 'no-store' });
    return res.ok;
  }catch(_){
    return false;
  }
}
