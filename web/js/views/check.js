/* The stock check.
 *
 * Categories are collapsed sections, not a flat list. A chef is physically at
 * the meat fridge or the dry store, so they open that one section, do their
 * items and close it. Five collapsed headers fit on a screen; seventeen open
 * rows do not, and scrolling past things you do not need is the overhead.
 *
 * Tap a row to flag it as needed. A quantity appears, prefilled with enough to
 * refill the shelf, and it is editable — typing a number is fast when you know
 * it, and the nudge buttons are there when you do not.
 *
 * No prices on this screen. The kitchen reports what it needs; cost is the
 * owner's side of the conversation.
 */

import { api } from '../api.js';
import {
  state, togglePick, pickOf, isPicked, setQuantity, setNoneLeft,
  suggestedQuantity, pickCount, branchName,
} from '../store.js';
import { el, icons, categoryArt, spinner, emptyState, toast, clear } from '../ui.js';

const CATEGORY_ORDER = ['protein', 'produce', 'spices', 'packaging', 'other'];

export function checkView({ go, openDrawer }) {
  const screen = el('div', { class: 'screen' });
  const body = el('div', { class: 'scroll with-cta' });

  // Which sections are open. Nothing is open to begin with — the point is that
  // the chef chooses where they are rather than scrolling past everywhere else.
  const open = new Set();
  let search = '';
  let searchTimer;

  const searchInput = el('input', {
    type: 'search', placeholder: 'Find an item…',
    'aria-label': 'Find an item',
    oninput: event => {
      clearTimeout(searchTimer);
      const value = event.target.value;
      searchTimer = setTimeout(() => { search = value.trim().toLowerCase(); paint(); }, 180);
    },
  });

  screen.append(
    el('div', { class: 'topbar' },
      el('button', {
        class: 'icon-btn', type: 'button', 'aria-label': 'Open menu',
        html: icons.menu, onclick: openDrawer,
      }),
      el('div', { class: 'greet' },
        el('small', { text: `${partOfDay()},` }),
        el('strong', { class: 'signature', text: state.user?.name || '' })),
      el('button', {
        class: 'icon-btn', type: 'button', 'aria-label': 'Notifications',
        html: icons.bell,
      })),
    // Which kitchen this list is for. Always on screen, because a list sent to
    // the wrong outlet is the expensive mistake.
    el('div', { class: 'branch-bar' },
      el('span', { class: 'pin', html: icons.pin, 'aria-hidden': 'true' }),
      el('span', { class: 'branch-name', text: branchName() })),
    el('div', { class: 'search' },
      searchInput,
      el('span', { html: icons.search, 'aria-hidden': 'true' })),
    body,
  );

  const sendButton = el('button', {
    class: 'cta', type: 'button', onclick: () => go('/review'),
  });
  screen.append(el('div', { class: 'cta-dock' }, sendButton));

  function syncCta() {
    const n = pickCount();
    sendButton.textContent = n
      ? `Review list · ${n} item${n === 1 ? '' : 's'}`
      : 'Tap what you need';
    sendButton.disabled = n === 0;
  }

  function paint() {
    clear(body);

    body.append(el('div', { class: 'ask' },
      el('h2', { text: "What do you need?" }),
      el('p', { text: 'Open a section and tap anything running low.' })));

    if (!state.inventory.length) { body.append(spinner('Loading the list')); return; }

    const matches = state.inventory.filter(
      item => !search || item.name.toLowerCase().includes(search));

    // A search cuts across categories, so show flat results rather than making
    // someone open a section to find what they just typed.
    if (search) {
      if (!matches.length) {
        body.append(emptyState(`Nothing matches “${search}”`, 'Try a shorter word.'));
      } else {
        const list = el('div', { class: 'pad' });
        for (const item of matches) list.append(row(item));
        body.append(list);
      }
      syncCta();
      return;
    }

    const grouped = new Map();
    for (const item of matches) {
      if (!grouped.has(item.category)) grouped.set(item.category, []);
      grouped.get(item.category).push(item);
    }
    const ordered = [...grouped.entries()].sort(
      (a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]));

    const wrap = el('div', { class: 'pad' });
    for (const [name, group] of ordered) wrap.append(section(name, group));
    body.append(wrap);
    syncCta();
  }

  function section(name, group) {
    const isOpen = open.has(name);
    const picked = group.filter(item => isPicked(item.id)).length;

    const panel = el('div', { class: 'sect-body', hidden: !isOpen });
    if (isOpen) for (const item of group) panel.append(row(item));

    const count = el('span', { class: 'sect-count' },
      picked
        ? el('span', { class: 'sect-badge', text: String(picked) })
        : null,
      el('span', { text: `${group.length}` }));

    const head = el('button', {
      class: 'sect-head', type: 'button',
      'aria-expanded': String(isOpen),
      onclick: () => {
        if (open.has(name)) open.delete(name); else open.add(name);
        paint();
        // Bring the section the chef just opened to the top of the screen.
        if (open.has(name)) {
          requestAnimationFrame(() => {
            body.querySelector(`[data-section="${name}"]`)
              ?.scrollIntoView({ block: 'start', behavior: 'smooth' });
          });
        }
      },
    },
      el('img', { class: 'sect-art', src: categoryArt[name] || categoryArt.other, alt: '' }),
      el('span', { class: 'sect-name', text: capitalise(name) }),
      count,
      el('span', { class: 'chev', html: icons.chevron, 'aria-hidden': 'true' }));

    return el('section', { class: isOpen ? 'sect open' : 'sect', dataset: { section: name } },
      head, panel);
  }

  function row(item) {
    const pick = pickOf(item.id);
    const controls = el('div', { class: 'qty-row', hidden: !pick });

    const card = el('div', { class: pick ? 'need-item picked' : 'need-item' });

    const toggle = el('button', {
      class: 'need-top', type: 'button',
      'aria-pressed': String(Boolean(pick)),
      onclick: () => {
        const next = togglePick(item);
        card.classList.toggle('picked', Boolean(next));
        toggle.setAttribute('aria-pressed', String(Boolean(next)));
        box.checked = Boolean(next);
        clear(controls);
        controls.hidden = !next;
        if (next) buildControls(item, next, controls);
        syncCta();
        repaintSectionCounts();
      },
    },
      el('span', { class: 'tickbox', html: icons.tick, 'aria-hidden': 'true' }),
      el('span', { class: 'need-name', text: item.name }),
      el('span', { class: 'need-unit', text: item.unit }));

    // Kept in sync so assistive tech sees a checkbox, not a mystery button.
    const box = el('input', {
      type: 'checkbox', class: 'vh', checked: Boolean(pick),
      'aria-label': `Need ${item.name}`,
      onchange: () => toggle.click(),
    });

    card.append(box, toggle, controls);
    if (pick) buildControls(item, pick, controls);
    return card;
  }

  function buildControls(item, pick, host) {
    // syncUnit is declared below; the field's handlers only call it after both
    // exist, so the forward reference is safe.
    const field = el('input', {
      type: 'number', class: 'qty-input',
      inputmode: 'numeric', min: '1', step: '1',
      value: String(pick.quantity),
      'aria-label': `How many ${item.unit}s of ${item.name}`,
      onfocus: event => event.target.select(),
      oninput: event => {
        const n = parseInt(event.target.value, 10);
        if (Number.isFinite(n) && n > 0) { setQuantity(item.id, n); syncUnit(n); }
      },
      onblur: event => {
        if (!event.target.value || parseInt(event.target.value, 10) < 1) {
          event.target.value = String(suggestedQuantity(item));
          setQuantity(item.id, suggestedQuantity(item));
        }
      },
    });

    const unitLabel = el('span', { class: 'qty-unit' });
    const syncUnit = n => {
      unitLabel.textContent = n === 1 ? item.unit : `${item.unit}s`;
    };
    syncUnit(pick.quantity);

    const nudge = delta => () => {
      const next = Math.max(1, (parseInt(field.value, 10) || 1) + delta);
      field.value = String(next);
      setQuantity(item.id, next);
      syncUnit(next);
    };

    const noneLeft = el('button', {
      class: pick.noneLeft ? 'none-left on' : 'none-left',
      type: 'button',
      'aria-pressed': String(pick.noneLeft),
      onclick: () => {
        const next = !pick.noneLeft;
        setNoneLeft(item.id, next);
        noneLeft.classList.toggle('on', next);
        noneLeft.setAttribute('aria-pressed', String(next));
      },
    }, 'None left');

    host.append(
      el('div', { class: 'qty' },
        el('button', { class: 'qty-btn', type: 'button', 'aria-label': 'One fewer',
                       text: '−', onclick: nudge(-1) }),
        field,
        el('button', { class: 'qty-btn plus', type: 'button', 'aria-label': 'One more',
                       text: '+', onclick: nudge(1) })),
      unitLabel,
      noneLeft);
  }

  function repaintSectionCounts() {
    for (const node of body.querySelectorAll('.sect')) {
      const name = node.dataset.section;
      const group = state.inventory.filter(i => i.category === name);
      const picked = group.filter(i => isPicked(i.id)).length;
      const badge = node.querySelector('.sect-badge');
      if (picked && badge) badge.textContent = String(picked);
      else if (picked && !badge) {
        node.querySelector('.sect-count')
          .prepend(el('span', { class: 'sect-badge', text: String(picked) }));
      } else if (!picked && badge) badge.remove();
    }
  }

  (async () => {
    paint();
    try {
      const data = await api.inventory(state.branchId);
      state.inventory = data.items;
      state.belowPar = data.below_par;
    } catch {
      if (!state.inventory.length) toast('Could not load the list.', { bad: true });
    }
    paint();
  })();

  return screen;
}

function partOfDay() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

const capitalise = s => s[0].toUpperCase() + s.slice(1);
