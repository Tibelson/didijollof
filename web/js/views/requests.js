import { api } from '../api.js';
import { state, formatDate, plural } from '../store.js';
import { el, icons, spinner, emptyState, clear } from '../ui.js';

/* The API's `active` is what the chef sees as "pending". */
const FILTERS = [
  { key: null, label: 'All' },
  { key: 'active', label: 'Pending' },
  { key: 'completed', label: 'Completed' },
];

const STATUS_LABEL = {
  active: 'pending',
  approved: 'approved',
  completed: 'completed',
  rejected: 'rejected',
};

export function requestsView({ go }) {
  const screen = el('div', { class: 'screen' });
  const body = el('div', { class: 'scroll with-cta' });
  let active = null;

  const tabs = el('div', { class: 'tabs', role: 'group', 'aria-label': 'Filter requests' });

  function renderTabs() {
    clear(tabs);
    for (const filter of FILTERS) {
      tabs.append(el('button', {
        type: 'button',
        'aria-pressed': String(filter.key === active),
        text: filter.label,
        onclick: () => { active = filter.key; renderTabs(); load(); },
      }));
    }
  }

  screen.append(
    el('div', { class: 'topbar' },
      el('button', {
        class: 'icon-btn', type: 'button', 'aria-label': 'Back',
        html: icons.back, onclick: () => go('/'),
      }),
      el('div', { class: 'greet' }, el('strong', { text: 'Past lists' }))),
    tabs,
    body);

  screen.append(el('div', { class: 'cta-dock' },
    el('button', {
      class: 'cta', type: 'button', text: 'Start a new list',
      onclick: () => go('/'),
    })));

  async function load() {
    clear(body).append(spinner('Loading requests'));
    try {
      const rows = await api.requests(state.branchId, active);
      clear(body);
      if (!rows.length) {
        body.append(emptyState('No requests yet',
          'Requests you send to your manager will appear here.'));
        return;
      }
      const list = el('div', { class: 'pad' });
      for (const row of rows) list.append(card(row));
      body.append(list);
    } catch (err) {
      clear(body).append(emptyState('Could not load requests', err.message));
    }
  }

  function card(row) {
    const label = STATUS_LABEL[row.status] || row.status;
    return el('button', {
      class: 'card req',
      type: 'button',
      style: 'width:100%;text-align:left',
      onclick: () => go(`/requests/${row.id}`),
    },
      el('div', { class: 'meat' },
        el('div', { class: 'date', text: formatDate(row.created_at) }),
        // "items" means distinct lines, matching the Sent screen and the
        // number of rows you see when you open the request.
        // No money on the chef's side — the owner sees what it costs.
        el('div', { class: 'sub' },
          el('b', { text: `${row.line_count} item${row.line_count === 1 ? '' : 's'}` }))),
      el('span', { class: `status ${row.status}`, text: label }));
  }

  renderTabs();
  load();
  return screen;
}

export function requestDetailView({ go, requestId }) {
  const screen = el('div', { class: 'screen' });
  const body = el('div', { class: 'scroll' });

  screen.append(
    el('div', { class: 'topbar' },
      el('button', {
        class: 'icon-btn', type: 'button', 'aria-label': 'Back',
        html: icons.back, onclick: () => go('/requests'),
      }),
      el('div', { class: 'greet' }, el('strong', { text: 'Request' }))),
    body);

  (async () => {
    body.append(spinner('Loading request'));
    try {
      const detail = await api.requestDetail(requestId);
      clear(body);

      const head = el('div', { class: 'pad' },
        el('h3', { class: 'h-section', text: formatDate(detail.created_at) }),
        el('div', { class: 'muted', style: 'font-size:13px;margin-top:-4px' },
          `${detail.branch_name} · by ${detail.requested_by} · `,
          el('span', {
            class: `status ${detail.status}`,
            text: STATUS_LABEL[detail.status] || detail.status,
          })));
      body.append(head);

      const list = el('div', { class: 'pad' });
      for (const line of detail.lines) {
        list.append(el('div', { class: 'card item' },
          el('div', { class: 'meat' },
            el('span', { class: 'name', text: line.name }),
            line.existing_stock === 0
              ? el('div', { class: 'muted small-note', text: 'None left at the time' })
              : null),
          el('b', { class: 'tnum', text: plural(line.quantity, line.unit) })));
      }
      body.append(list);

      body.append(el('div', { class: 'pad' },
        el('div', { class: 'count-bar' },
          el('span', { text: `${detail.lines.length} item${detail.lines.length === 1 ? '' : 's'}` }),
          el('b', { text: detail.branch_name }))));

      if (detail.review_note) {
        body.append(el('div', { class: 'pad' },
          el('div', { class: 'card', text: detail.review_note })));
      }
    } catch (err) {
      clear(body).append(emptyState('Could not load this request', err.message));
    }
  })();

  return screen;
}
