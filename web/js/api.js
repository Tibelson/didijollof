/* Thin wrapper over fetch.
 *
 * The session lives in an HttpOnly cookie, so there is no token for this file
 * to hold or leak — `credentials: 'same-origin'` is the whole auth story.
 * A 401 anywhere means the session is gone, so it is turned into a single
 * typed error the app can route on rather than handled at each call site.
 */

export class ApiError extends Error {
  constructor(status, detail, payload) {
    super(detail || `request failed (${status})`);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
  get isAuth() { return this.status === 401; }
  get isOffline() { return this.status === 0; }
}

async function request(method, path, body) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    // Network unreachable — distinct from any server response.
    throw new ApiError(0, 'You appear to be offline.');
  }

  if (response.status === 204) return null;

  const text = await response.text();
  let payload = null;
  if (text) { try { payload = JSON.parse(text); } catch { /* non-JSON error page */ } }

  if (!response.ok) {
    throw new ApiError(response.status, detailOf(payload) || response.statusText, payload);
  }
  return payload;
}

/* FastAPI returns `detail` as either a string or a list of validation errors. */
function detailOf(payload) {
  if (!payload || payload.detail === undefined) return null;
  const { detail } = payload;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(d => d.msg || JSON.stringify(d)).join('; ');
  }
  return null;
}

export const api = {
  login: (email, password) => request('POST', '/auth/login', { email, password }),
  logout: () => request('POST', '/auth/logout'),
  me: () => request('GET', '/me'),

  inventory(branchId, { category, q } = {}) {
    const params = new URLSearchParams();
    if (category) params.set('category', category);
    if (q) params.set('q', q);
    const qs = params.toString();
    return request('GET', `/branches/${branchId}/inventory${qs ? `?${qs}` : ''}`);
  },

  suggestions: branchId => request('GET', `/branches/${branchId}/inventory/suggestions`),

  submitRequest: (branchId, lines) =>
    request('POST', `/branches/${branchId}/requests`, { lines }),

  requests: (branchId, status) =>
    request('GET', `/branches/${branchId}/requests${status ? `?status=${status}` : ''}`),

  requestDetail: id => request('GET', `/requests/${id}`),
};
