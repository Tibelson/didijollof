import { api, ApiError } from '../api.js';
import { el } from '../ui.js';

export function loginView({ onSignedIn }) {
  const error = el('div', { class: 'error', hidden: true, role: 'alert' });
  const email = el('input', {
    type: 'email', id: 'email', name: 'email', autocomplete: 'username',
    required: true, placeholder: 'chef@didijollof.com', inputmode: 'email',
  });
  const password = el('input', {
    type: 'password', id: 'password', name: 'password',
    autocomplete: 'current-password', required: true, placeholder: '••••••••',
  });
  const submit = el('button', { type: 'submit', class: 'cta', text: 'Log in' });

  const form = el('form', { class: 'login', novalidate: true },
    el('img', { class: 'mark', src: '/icons/mark.webp', alt: '', width: 72, height: 72 }),
    el('div', { class: 'brand', text: 'DIDI JOLLOF' }),
    el('h1', { text: 'Kitchen inventory' }),
    error,
    el('div', { class: 'field' }, el('label', { for: 'email', text: 'Email' }), email),
    el('div', { class: 'field' }, el('label', { for: 'password', text: 'Password' }), password),
    submit,
    el('button', {
      type: 'button', class: 'link',
      text: 'Forgot password?',
      onclick: () => show('Ask your manager to reset it for now.'),
    }),
  );

  function show(message) {
    error.textContent = message;
    error.hidden = false;
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    error.hidden = true;

    if (!email.value.trim() || !password.value) {
      show('Enter your email and password.');
      return;
    }

    submit.disabled = true;
    const label = submit.textContent;
    submit.textContent = 'Signing in…';
    try {
      const user = await api.login(email.value.trim(), password.value);
      onSignedIn(user);
    } catch (err) {
      // Never echo back which half was wrong.
      show(err instanceof ApiError && err.isOffline
        ? 'You appear to be offline. Check your connection and try again.'
        : 'Email or password is incorrect.');
      password.value = '';
      password.focus();
    } finally {
      submit.disabled = false;
      submit.textContent = label;
    }
  });

  return form;
}
