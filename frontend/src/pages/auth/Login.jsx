import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { BUILD, errMsg } from '../../services/api';
import { ErrorBox, Field } from '../../components/ui';
import { HOME } from '../../utils/format';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const notice = useLocation().state?.notice;     // e.g. after a password reset
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try { const user = await login(email, password); navigate(HOME[user.role], { replace: true }); }
    catch (err) { setError(errMsg(err)); } finally { setBusy(false); }
  };

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <div className="brand" style={{ padding: 0, marginBottom: 20 }}><div className="logo">WC</div><div><b>WORKCODE</b><small>DEV PLATFORM</small></div></div>
        <p className="muted" style={{ marginTop: 0 }}>Sign in to your workspace</p>
        {notice && !error && <div className="notice ok" role="status">{notice}</div>}
        <ErrorBox error={error} />
        <Field label="Email or username"><input type="text" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email or username"
          autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder="you@company.com or WC-E0005" /></Field>
        <Field label="Password"><input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} aria-label="Password" autoComplete="current-password" /></Field>
        <div style={{ textAlign: 'right', margin: '-6px 0 14px', fontSize: 13 }}><Link to="/forgot-password">Forgot password?</Link></div>
        <button className="btn primary" style={{ width: '100%' }} disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <div className="muted" style={{ textAlign: 'center', marginTop: 12, fontSize: 11 }}>{BUILD}</div>
      </form>
    </div>
  );
}
