/* Confirm and send.
 *
 * Deliberately shows no money. The kitchen's job is to say what it needs; what
 * that costs is the owner's and logistics' side, and the server prices the
 * request when it lands.
 *
 * It does show the outlet, prominently, because a list sent to the wrong
 * kitchen is the mistake that actually costs something.
 */

import { api, ApiError } from '../api.js';
import {
  state, pickedLines, orderPayload, clearPicks, plural, branchName, branchLocation,
} from '../store.js';
import { el, icons, emptyState, toast } from '../ui.js';

export function reviewView({ go }) {
  const screen = el('div', { class: 'screen' });
  const body = el('div', { class: 'scroll with-cta' });

  screen.append(
    el('div', { class: 'topbar' },
      el('button', {
        class: 'icon-btn', type: 'button', 'aria-label': 'Back',
        html: icons.back, onclick: () => go('/'),
      }),
      el('div', { class: 'greet' }, el('strong', { text: 'Your list' }))),
    body);

  const send = el('button', { class: 'cta', type: 'button', text: 'Send to Mr Owner' });
  const dock = el('div', { class: 'cta-dock' },
    send,
    el('p', { class: 'cta-note', text: 'Nothing is bought until your manager approves it.' }));
  screen.append(dock);

  send.addEventListener('click', async () => {
    const lines = orderPayload();
    if (!lines.length) return;

    send.disabled = true;
    send.replaceChildren(el('span', { class: 'spinner' }), document.createTextNode('Sending…'));
    try {
      state.lastRequest = await api.submitRequest(state.branchId, lines);
      clearPicks();
      go('/sent');
    } catch (err) {
      send.disabled = false;
      send.textContent = 'Send to Mr Owner';
      toast(err instanceof ApiError && err.isOffline
        ? 'You are offline. The list was not sent.'
        : err.message || 'Could not send the list.', { bad: true });
    }
  });

  const lines = pickedLines();
  if (!lines.length) {
    body.append(emptyState('Nothing on the list',
      'Go back and tap anything you need.'));
    dock.hidden = true;
    return screen;
  }

  body.append(el('div', { class: 'for-branch' },
    el('span', { class: 'pin', html: icons.pin, 'aria-hidden': 'true' }),
    el('span', null,
      el('b', { text: branchName() }),
      el('small', { text: branchLocation() }))));

  const list = el('div', { class: 'pad' });
  for (const line of lines) {
    list.append(el('div', { class: 'buy-item' },
      el('div', { class: 'top' },
        el('span', { class: 'name', text: line.item.name }),
        el('span', { class: 'amount', text: plural(line.quantity, line.item.unit) })),
      line.noneLeft
        ? el('p', { class: 'why urgent' },
            el('span', { class: 'outcome-icon', html: icons.alert, 'aria-hidden': 'true' }),
            'None left')
        : null));
  }
  body.append(list);

  // Summing 26 kgs and 12 pieces into "38 units" would be a number that means
  // nothing. Count the items, and call out the ones that are completely out.
  const out = lines.filter(l => l.noneLeft).length;
  body.append(el('div', { class: 'pad' },
    el('div', { class: 'count-bar' },
      el('span', { text: lines.length === 1 ? '1 item' : `${lines.length} items` }),
      out ? el('b', { text: `${out} with none left` }) : null)));

  return screen;
}
