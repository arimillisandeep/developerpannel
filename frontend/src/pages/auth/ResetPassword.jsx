import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import api, { errMsg, setToken } from '../../services/api';
import { useAuth } from '../../context/AuthContext';
import { ErrorBox, Field } from '../../components/ui';

/** Same rules as password_problems() on the server (the server checks again). */
export const PASSWORD_RULES = [
  ['At least 8 characters', (p) => p.length >= 8],
  ['A small letter', (p) => /\p{Ll}/u.test(p)],
  ['A capital letter', (p) => /\p{Lu}/u.test(p)],
  ['A number', (p) => /\d/.test(p)],
  ['A symbol like @ # !', (p) => /[^\p{L}\p{N}]/u.test(p)],
];

/** Step 2: opened from the link in the e-mail (/reset-password#token=...).
 *  The token is read from the part after "#", which browsers never send to a server, and removed from the address bar. */
export default function ResetPassword() {
  const navigate = useNavigate();
  const { reload } = useAuth();
  const token = useRef('');
  const [stage, setStage] = useState('checking');     // checking | form | bad | done
  const [problem, setProblem] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [seconds, setSeconds] = useState(4);

  useEffect(() => {
    const found = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token')
      || new URLSearchParams(window.location.search).get('token') || '';
    // React runs this twice in development (StrictMode). The first run already took the token out of the address bar:
    // the second run must not replace it with nothing.
    if (!found && token.current) return;
    token.current = found;
    if (found) window.history.replaceState(null, '', window.location.pathname);   // keep it out of the history and of screenshots
    if (!found) { setProblem('This page must be opened from the link in the password reset e-mail.'); setStage('bad'); return; }
    api.post('/auth/reset-password/validate', { token: found })
      .then(() => setStage('form'))
      .catch((err) => { setProblem(errMsg(err)); setStage('bad'); });
  }, []);

  useEffect(() => {   // after success: back to the sign-in page by itself
    if (stage !== 'done') return undefined;
    if (seconds <= 0) { navigate('/login', { replace: true, state: { notice: 'Password reset successfully. Sign in with your new password.' } }); return undefined; }
    const timer = setTimeout(() => setSeconds((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [stage, seconds, navigate]);

  const failed = PASSWORD_RULES.filter(([, ok]) => !ok(password));
  const mismatch = confirm.length > 0 && confirm !== password;
  const ready = failed.length === 0 && confirm === password;

  const submit = async (e) => {
    e.preventDefault();
    if (!ready) { setError(failed.length ? 'The password is not strong enough yet.' : 'The two passwords are not the same.'); return; }
    setBusy(true); setError('');
    try {
      await api.post('/auth/reset-password', { token: token.current, new_password: password });
      token.current = '';
      setToken(null);            // every earlier sign-in of this account is revoked by the server: forget ours too
      await reload?.();
      setStage('done');
    } catch (err) {
      if (err?.response?.status === 400) { setProblem(errMsg(err)); setStage('bad'); } else setError(errMsg(err));
    } finally { setBusy(false); }
  };

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <div className="brand" style={{ padding: 0, marginBottom: 20 }}><div className="logo">WC</div><div><b>WORKCODE</b><small>DEV PLATFORM</small></div></div>
        <h2 style={{ margin: '0 0 6px', fontSize: 18 }}>Create new password</h2>
        {stage === 'checking' && <p className="muted">Checking the link…</p>}
        {stage === 'bad' && (<>
          <div className="notice bad" role="alert">{problem}</div>
          <Link className="btn primary" style={{ width: '100%', display: 'block', textAlign: 'center', boxSizing: 'border-box' }} to="/forgot-password">Request a new link</Link>
        </>)}
        {stage === 'done' && (<>
          <div className="notice ok" role="status"><b>Password Reset Successfully</b></div>
          <p className="muted">You are taken to the sign-in page in {seconds} second{seconds === 1 ? '' : 's'}…</p>
          <Link className="btn primary" style={{ width: '100%', display: 'block', textAlign: 'center', boxSizing: 'border-box' }} to="/login" replace
            state={{ notice: 'Password reset successfully. Sign in with your new password.' }}>Go to sign in now</Link>
        </>)}
        {stage === 'form' && (<>
          <p className="muted" style={{ marginTop: 0 }}>Choose a new password for your account.</p>
          <ErrorBox error={error} />
          <Field label="New password"><input type={show ? 'text' : 'password'} required autoFocus value={password} onChange={(e) => setPassword(e.target.value)} aria-label="New password" autoComplete="new-password" /></Field>
          <ul className="pw-rules" aria-label="Password rules">
            {PASSWORD_RULES.map(([label, ok]) => <li key={label} className={ok(password) ? 'ok' : ''}>{ok(password) ? '✓' : '○'} {label}</li>)}
          </ul>
          <Field label="Confirm new password"><input type={show ? 'text' : 'password'} required value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-label="Confirm new password" autoComplete="new-password" aria-invalid={mismatch} /></Field>
          {mismatch && <div className="pw-mismatch" role="alert">The two passwords are not the same.</div>}
          <label className="row" style={{ gap: 8, margin: '4px 0 14px', fontSize: 13 }}>
            <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} style={{ width: 'auto' }} /> Show password
          </label>
          <button className="btn primary" style={{ width: '100%' }} disabled={busy || !ready}>{busy ? 'Saving…' : 'Save password'}</button>
        </>)}
        {stage !== 'done' && <div style={{ textAlign: 'center', marginTop: 14 }}><Link to="/login">← Back to sign in</Link></div>}
      </form>
    </div>
  );
}
