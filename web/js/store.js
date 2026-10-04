/* Application state.
 *
 * What the chef produces is a short list: the items running low and how many
 * units they need. Quantity is prefilled from what the branch last recorded, so
 * the common case is no typing, but it is a real editable number — the amount
 * is the chef's call, not something the app infers and hides.
 *
 * No prices here. The kitchen says what it needs; what it costs is the owner's
 * and logistics' business, and the server prices the request when it lands.
 *
 * The list survives a reload — someone counting a stockroom who locks their
 * phone should not start again — and is keyed by branch so two outlets on one
 * device can never blend.
 */

const PICKS_KEY = 'didi.picks.v1';

const listeners = new Set();

export const state = {
  user: null,          // { id, name, email, role, branches: [] }
  branchId: null,
  inventory: [],       // InventoryItemOut[]
  belowPar: 0,
  picks: new Map(),    // item_id -> { quantity, noneLeft }
  lastRequest: null,
  online: navigator.onLine,
};

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function notify() {
  for (const fn of listeners) fn(state);
}

/* ------------------------------------------------------------- suggestion */

/** Enough to get back to a full shelf, and never a useless zero. */
export function suggestedQuantity(item) {
  return Math.max(item.par_level - item.current_stock, 1);
}

/* ------------------------------------------------------------------ picks */

export function pickOf(itemId) {
  return state.picks.get(itemId) || null;
}

export function isPicked(itemId) {
  return state.picks.has(itemId);
}

/** Flag an item as needed, or unflag it. Returns the resulting pick. */
export function togglePick(item) {
  if (state.picks.has(item.id)) {
    state.picks.delete(item.id);
  } else {
    state.picks.set(item.id, { quantity: suggestedQuantity(item), noneLeft: false });
  }
  persist();
  notify();
  return pickOf(item.id);
}

export function setQuantity(itemId, quantity) {
  const pick = state.picks.get(itemId);
  if (!pick) return;
  pick.quantity = Math.max(1, Math.min(100000, Math.round(quantity) || 1));
  persist();
  notify();
}

export function setNoneLeft(itemId, noneLeft) {
  const pick = state.picks.get(itemId);
  if (!pick) return;
  pick.noneLeft = Boolean(noneLeft);
  persist();
  notify();
}

export function clearPicks() {
  state.picks.clear();
  persist();
  notify();
}

export function pickCount() {
  return state.picks.size;
}

/** The picked items, with their item record attached, in category order. */
export function pickedLines() {
  const lines = [];
  for (const [itemId, pick] of state.picks) {
    const item = state.inventory.find(i => i.id === itemId);
    if (!item) continue;
    lines.push({ item, quantity: pick.quantity, noneLeft: pick.noneLeft });
  }
  return lines.sort((a, b) =>
    a.item.category.localeCompare(b.item.category) || a.item.name.localeCompare(b.item.name));
}

/**
 * The payload the API expects.
 *
 * existing_stock is what the branch last recorded, unless the chef said the
 * shelf is empty — in which case it is zero, which is both true and the signal
 * the owner most needs to see.
 */
export function orderPayload() {
  return pickedLines().map(line => ({
    item_id: line.item.id,
    quantity: line.quantity,
    existing_stock: line.noneLeft ? 0 : line.item.current_stock,
  }));
}

function persist() {
  if (!state.branchId) return;
  try {
    localStorage.setItem(PICKS_KEY, JSON.stringify({
      branchId: state.branchId,
      picks: [...state.picks],
    }));
  } catch { /* private mode or quota — the list is a convenience, not the record */ }
}

export function restorePicks(branchId) {
  state.picks.clear();
  try {
    const raw = localStorage.getItem(PICKS_KEY);
    if (!raw) return;
    const payload = JSON.parse(raw);
    if (payload.branchId !== branchId) { localStorage.removeItem(PICKS_KEY); return; }
    for (const [itemId, pick] of payload.picks) {
      state.picks.set(Number(itemId), pick);
    }
  } catch {
    localStorage.removeItem(PICKS_KEY);
  }
}

/* ----------------------------------------------------------------- format */

export function plural(n, unit) {
  return `${n} ${n === 1 ? unit : `${unit}s`}`;
}

export function branchName() {
  const branch = state.user?.branches?.find(b => b.id === state.branchId);
  return branch ? branch.name : '';
}

export function branchLocation() {
  const branch = state.user?.branches?.find(b => b.id === state.branchId);
  return branch ? branch.location : '';
}

export function formatDate(iso) {
  const d = new Date(iso);
  if (d.toDateString() === new Date().toDateString()) {
    return `Today, ${d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`;
  }
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
}
