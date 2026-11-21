import { useState } from 'react';
import { Link } from 'react-router-dom';
import api, { errMsg } from '../../services/api';
import { ErrorBox, Field } from '../../components/ui';

/** Step 1 of "forgot password": the person types the address of their account.
 *  The server mails a reset link to that account's own address; an address without an account gets "Email not found". */
export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try { setSent((await api.post('/auth/forgot-password', { email: email.trim() })).data.message); }
    catch (err) { setError(errMsg(err)); } finally { setBusy(false); }
  };

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <div className="brand" style={{ padding: 0, marginBottom: 20 }}><div className="logo">WC</div><div><b>WORKCODE</b><small>DEV PLATFORM</small></div></div>
        <h2 style={{ margin: '0 0 6px', fontSize: 18 }}>Forgot password</h2>
        {sent ? (
          <>
            <div className="notice ok" role="status">{sent}</div>
            <p className="muted" style={{ fontSize: 13 }}>Open the e-mail and press <b>Create new password</b>. The link works once, for 30 minutes. Not there? Look in Spam, then try again.</p>
            <button type="button" className="btn" style={{ width: '100%' }} onClick={() => setSent('')}>Send again</button>
          </>
        ) : (
          <>
            <p className="muted" style={{ marginTop: 0 }}>Enter the e-mail address of your WORKCODE account. We send a link to create a new password to that address.</p>
            <ErrorBox error={error} />
            <Field label="Email address"><input type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email address" autoComplete="email" /></Field>
            <button className="btn primary" style={{ width: '100%' }} disabled={busy}>{busy ? 'Sending…' : 'Send reset link'}</button>
          </>
        )}
        <div style={{ textAlign: 'center', marginTop: 14 }}><Link to="/login">← Back to sign in</Link></div>
      </form>
    </div>
  );
}
