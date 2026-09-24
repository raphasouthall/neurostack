import { html, useState } from '../lib.js';
import { api } from '../api.js';

// Module code runs once per page load, so the style is injected once.
document.head.insertAdjacentHTML('beforeend', `<style>
.login { display: grid; place-items: center; min-height: calc(100vh - 64px); }
.login form { width: 400px; display: flex; flex-direction: column; gap: 16px; padding: 32px; }
.login .logo { padding: 0 0 8px; font-size: 22px; }
.login .logo-mark { width: 32px; height: 32px; }
.login .input { height: 56px; font-size: 16px; }
.login .btn { justify-content: center; }
</style>`);

export default function Login({ onDone }) {
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  // A form submit, so Enter in either field signs in.
  const submit = async (e) => {
    e.preventDefault();
    const f = e.currentTarget.elements;
    setBusy(true);
    try {
      await api('login', { username: f.username.value, password: f.password.value });
      onDone();
    } catch (x) {
      setErr(x.message);
      setBusy(false);
    }
  };

  return html`
    <div class="login">
      <form class="card card-body" onSubmit=${submit}>
        <div class="logo"><img class="logo-mark" src="logo.svg" alt="" />NeuroStack</div>
        <input class="input" name="username" placeholder="Username" aria-label="Username"
          autocomplete="username" autofocus required />
        <input class="input" name="password" type="password" placeholder="Password" aria-label="Password"
          autocomplete="current-password" required />
        ${err && html`<div class="error" role="alert">${err}</div>`}
        <button class="btn btn-primary" disabled=${busy}>Sign in</button>
      </form>
    </div>`;
}
