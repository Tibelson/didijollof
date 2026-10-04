import { state, branchName } from '../store.js';
import { el, icons } from '../ui.js';

export function sentView({ go }) {
  const request = state.lastRequest;
  const when = request
    ? new Date(request.created_at).toLocaleTimeString('en-GB',
        { hour: '2-digit', minute: '2-digit' })
    : '';
  const count = request ? request.lines.length : 0;

  return el('div', { class: 'sent' },
    el('div', { class: 'tick', 'aria-hidden': 'true', html: icons.tick }),
    el('h2', { text: 'List sent' }),
    el('p', null,
      `Your manager got your list at ${when}.`,
      el('br'),
      `${count} item${count === 1 ? '' : 's'} for ${branchName()}`),
    el('button', { class: 'cta', type: 'button', text: 'Done', onclick: () => go('/') }),
    el('button', {
      class: 'link', type: 'button', text: 'See past lists',
      onclick: () => go('/requests'),
    }));
}
