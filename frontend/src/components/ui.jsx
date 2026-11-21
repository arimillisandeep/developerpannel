import { createPortal } from 'react-dom';
import { cloneElement, isValidElement, useId, useState } from 'react';
import { label, tone } from '../utils/format';

export const Badge = ({ value, children }) => <span className={`badge ${tone(value)}`}>{children || label(value)}</span>;

export const Stat = ({ title, value, sub, ico }) => (
  <div className="stat">{ico && <div className="ico" aria-hidden="true">{ico}</div>}<div className="label">{title}</div><div className="value">{value}</div>{sub && <div className="sub">{sub}</div>}</div>
);

export const PageHead = ({ title, sub, eyebrow, children }) => (
  <div className="page-head"><div>{eyebrow && <div className="eyebrow" style={{ marginBottom: 6 }}>{eyebrow}</div>}<h1>{title}</h1>{sub && <p>{sub}</p>}</div><div className="row">{children}</div></div>
);

export function Modal({ title, onClose, wide, children }) {
  // Rendered directly under <body>: a dialog opened from the top bar would otherwise be trapped inside it
  // (the bar uses backdrop-filter, which makes "position: fixed" relative to the bar instead of the window).
  return createPortal(
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-label={title}>
        <div className="row spread" style={{ marginBottom: 12 }}><h2 style={{ margin: 0 }}>{title}</h2>
          <button className="btn small" onClick={onClose} aria-label="Close">✕</button></div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function PromptModal({ title, label: fieldLabel, initial = '', hint, onSubmit, onClose }) {
  const [v, setV] = useState(initial);
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (v.trim()) onSubmit(v.trim()); }}>
        <div className="field"><label>{fieldLabel}</label><input autoFocus value={v} onChange={(e) => setV(e.target.value)} />
          {hint && <small className="muted">{hint}</small>}</div>
        <div className="modal-foot"><button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!v.trim()}>OK</button></div>
      </form>
    </Modal>
  );
}

export function ConfirmModal({ title, text, danger, confirmLabel = 'Confirm', onConfirm, onClose }) {
  return (
    <Modal title={title} onClose={onClose}>
      <p>{text}</p>
      <div className="modal-foot"><button className="btn" onClick={onClose}>Cancel</button>
        <button className={`btn ${danger ? 'danger' : 'primary'}`} onClick={onConfirm}>{confirmLabel}</button></div>
    </Modal>
  );
}

/** A label with its input. The label is linked to the input, so screen readers read it and a click on the label focuses the field. */
export function Field({ label: l, children }) {
  const id = useId();
  const single = isValidElement(children) && typeof children.type === 'string';
  const inputId = single ? children.props.id || id : undefined;
  return <div className="field"><label htmlFor={inputId}>{l}</label>{single ? cloneElement(children, { id: inputId }) : children}</div>;
}
export const ErrorBox = ({ error }) => (error ? <div className="error" role="alert">{error}</div> : null);

/** Daily hours bar chart. data: [{day, hours}] */
export function HoursChart({ data }) {
  const max = Math.max(1, ...data.map((d) => d.hours));
  const step = Math.ceil(data.length / 14);
  return (
    <div>
      <div className="bars">{data.map((d) => (
        <div key={d.day} className="bar" style={{ height: `${(d.hours / max) * 100}%` }} title={`${d.day}: ${d.hours} h`} />))}
      </div>
      <div className="bars-x">{data.map((d, i) => <span key={d.day}>{i % step === 0 ? d.day.slice(5) : ''}</span>)}</div>
    </div>
  );
}

/** Horizontal distribution. rows: [[label, count]] */
export function Distribution({ rows }) {
  const total = rows.reduce((a, [, n]) => a + n, 0);
  if (!total) return <div className="empty">No tasks yet.</div>;
  return rows.filter(([, n]) => n > 0).map(([name, n]) => (
    <div key={name} style={{ marginBottom: 10 }}>
      <div className="row spread"><span>{label(name)}</span><b>{n}</b></div>
      <div className="hbar"><i style={{ width: `${(n / total) * 100}%` }} /></div>
    </div>
  ));
}
