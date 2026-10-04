/* Bootstrap, routing and chrome.
 *
 * Routing is hash-based so Workers Static Assets can serve a single index.html
 * without needing a SPA rewrite rule, and a deep link still survives a reload.
 */

import { api, ApiError } from './api.js';
import { state, restorePicks, pickCount, subscribe } from './store.js';
import { el, icons, clear, toast } from './ui.js';
import { loginView } from './views/login.js';
import { checkView } from './views/check.js';
import { reviewView } from './views/review.js';
import { sentView } from './views/sent.js';
import { requestsView, requestDetailView } from './views/requests.js';

const root = document.getElementById('view');
const navHost = document.getElementById('nav');
const drawer = document.getElementById('drawer');
const scrim = document.getElementById('scrim');

let currentScreen = null;

/* Three destinations. The old cart tab is gone: there is no basket to assemble
   any more, the list falls out of what the chef reported. */
const NAV = [
  { path: '/', icon: 'home', label: 'Stock check' },
  { path: '/requests', icon: 'list', label: 'Past lists' },
  { path: '/profile', icon: 'user', label: 'Profile' },
];

/* ------------------------------------------------------------------ routing */

function go(path) {
  if (location.hash.slice(1) === path) render();
  else location.hash = path;
}

function parseRoute() {
  const raw = location.hash.slice(1) || '/';
  const [path, query] = raw.split('?');
  return { path, params: new URLSearchParams(query || '') };
}

function render() {
  const { path } = parseRoute();

  if (!state.user) {
    mount(loginView({ onSignedIn: signedIn }));
    navHost.hidden = true;
    return;
  }

  navHost.hidden = false;
  const detail = path.match(/^\/requests\/(\d+)$/);

  if (path === '/review') mount(reviewView({ go }));
  else if (path === '/sent') mount(sentView({ go }));
  else if (detail) mount(requestDetailView({ go, requestId: detail[1] }));
  else if (path === '/requests') mount(requestsView({ go }));
  else if (path === '/profile') { openDrawer(); go('/'); return; }
  else mount(checkView({ go, openDrawer }));

  // The Sent screen is a full-bleed confirmation; the nav would fight it.
  navHost.hidden = path === '/sent';
  renderNav(path);
}

function mount(screen) {
  // Let the outgoing screen stop its timers before it is discarded.
  currentScreen?.dispatchEvent(new CustomEvent('didi:teardown'));
  currentScreen = screen;
  clear(root).append(screen);
  root.scrollTop = 0;
}

/* --------------------------------------------------------------------- nav */

function renderNav(path) {
  clear(navHost);
  for (const entry of NAV) {
    const active = entry.path === path
      || (entry.path === '/requests' && path.startsWith('/requests'));
    const button = el('button', {
      type: 'button',
      'aria-label': entry.label,
      'aria-current': active ? 'page' : null,
      html: icons[entry.icon],
      onclick: () => go(entry.path),
    });
    if (entry.path === '/' && pickCount() > 0) {
      button.append(el('span', { class: 'badge', text: String(pickCount()) }));
    }
    navHost.append(button);
  }
}

/* ------------------------------------------------------------------ drawer */

function openDrawer() {
  drawer.classList.add('open');
  scrim.classList.add('open');
  drawer.querySelector('button')?.focus();
}

function closeDrawer() {
  drawer.classList.remove('open');
  scrim.classList.remove('open');
}

function renderDrawer() {
  const branch = state.user?.branches?.find(b => b.id === state.branchId);
  clear(drawer).append(
    el('div', { class: 'who', text: state.user?.name || '' }),
    el('div', { class: 'where', text: branch ? branch.name : '' }),
    el('nav', null,
      el('button', { type: 'button', text: 'My Requests',
        onclick: () => { closeDrawer(); go('/requests'); } }),
      el('button', { type: 'button', text: 'Stock check',
        onclick: () => { closeDrawer(); go('/'); } }),
      ...branchSwitcher()),
    el('button', {
      class: 'sign-out', type: 'button', text: 'Log out',
      onclick: signOut,
    }));
}

/* Only an owner switches branches. A chef reports for their own kitchen and
 * nothing else — a switcher would only ever be a way to send a list to the
 * wrong outlet. */
function branchSwitcher() {
  const branches = state.user?.branches || [];
  if (state.user?.role !== 'owner' || branches.length < 2) return [];
  return [
    el('div', {
      class: 'muted',
      style: 'font-size:11px;font-weight:700;letter-spacing:.1em;margin:18px 12px 6px',
      text: 'BRANCH',
    }),
    ...branches.map(branch => el('button', {
      type: 'button',
      text: branch.id === state.branchId ? `✓ ${branch.name}` : branch.name,
      onclick: () => { closeDrawer(); switchBranch(branch.id); },
    })),
  ];
}

async function switchBranch(branchId) {
  state.branchId = branchId;
  localStorage.setItem('didi.branch', String(branchId));
  restorePicks(branchId);
  await loadInventory();
  renderDrawer();
  render();
  toast(`Switched to ${state.user.branches.find(b => b.id === branchId).name}`);
}

/* ------------------------------------------------------------------ session */

async function signedIn(user) {
  state.user = user;
  const remembered = Number(localStorage.getItem('didi.branch'));
  const allowed = user.branches.map(b => b.id);
  state.branchId = allowed.includes(remembered) ? remembered : allowed[0];
  localStorage.setItem('didi.branch', String(state.branchId));
  restorePicks(state.branchId);
  renderDrawer();
  await loadInventory();
  go('/');
}

async function signOut() {
  closeDrawer();
  try { await api.logout(); } catch { /* clearing local state matters more */ }
  state.user = null;
  state.branchId = null;
  state.inventory = [];
  localStorage.removeItem('didi.branch');
  render();
}

async function loadInventory() {
  try {
    const data = await api.inventory(state.branchId);
    state.inventory = data.items;
    state.belowPar = data.below_par;
  } catch (err) {
    if (err instanceof ApiError && err.isAuth) { state.user = null; render(); return; }
    toast('Could not load inventory.', { bad: true });
  }
}

/* --------------------------------------------------------------------- boot */

/* The splash is in the HTML so it shows on the first frame. Hide it once we
   know whether there is a session, and guarantee it goes away even if boot
   throws — a stuck splash is worse than no splash. */
function hideSplash() {
  const splash = document.getElementById('splash');
  if (!splash || splash.classList.contains('gone')) return;
  splash.classList.add('gone');
  splash.addEventListener('transitionend', () => splash.remove(), { once: true });
  setTimeout(() => splash.remove(), 900);   // in case the transition never fires
}

async function boot() {
  try {
    const user = await api.me();
    await signedIn(user);
  } catch (err) {
    if (!(err instanceof ApiError) || !err.isAuth) {
      // Offline with no session: still show the login screen rather than a blank page.
      console.warn('session check failed', err);
    }
    state.user = null;
    render();
  } finally {
    hideSplash();
  }
}

window.addEventListener('hashchange', render);
scrim.addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

window.addEventListener('online', () => {
  state.online = true;
  document.getElementById('offline').hidden = true;
});
window.addEventListener('offline', () => {
  state.online = false;
  document.getElementById('offline').hidden = false;
});
document.getElementById('offline').hidden = navigator.onLine;

// Keep the cart badge in step with the draft without re-rendering the screen.
subscribe(() => renderNav(parseRoute().path));

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* non-fatal */ });
  });
}

boot();
