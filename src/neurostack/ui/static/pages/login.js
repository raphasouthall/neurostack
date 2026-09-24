import { html, useState } from '../lib.js';
import { api } from '../api.js';
import { Alert, AlertDescription, Button, Card, CardTitle, Input, Label } from '../components/ui.js';

// Module code runs once per page load, so the style is injected once.
document.head.insertAdjacentHTML('beforeend', `<style>
.login { display: grid; place-items: center; min-height: calc(100vh - 64px); }
.login .card { width: min(400px, 100%); }
.login form { display: flex; flex-direction: column; gap: 16px; padding: 32px; }
.login .logo { padding: 0 0 8px; font-size: 22px; }
.login .logo-mark { width: 32px; height: 32px; }
.login-field { display: grid; gap: 8px; }
.login .input { height: 56px; font-size: 16px; }
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
      <${Card}>
        <form onSubmit=${submit}>
          <${CardTitle} class="logo"><img class="logo-mark" src="logo.svg" alt="" />NeuroStack<//>
          <div class="login-field">
            <${Label} for="login-username">Username<//>
            <${Input} id="login-username" name="username" autocomplete="username" autofocus required />
          </div>
          <div class="login-field">
            <${Label} for="login-password">Password<//>
            <${Input} id="login-password" name="password" type="password" autocomplete="current-password" required />
          </div>
          ${err && html`<${Alert} variant="destructive"><${AlertDescription}>${err}<//><//>`}
          <${Button} type="submit" disabled=${busy}>Sign in<//>
        </form>
      <//>
    </div>`;
}
