import '@testing-library/jest-dom';

// xterm.js draws on a canvas, which jsdom does not have. The tests use this small stand-in:
// what the app writes is collected in `text`, and `type()` plays the user's keys.
import { vi } from 'vitest';
vi.mock('@xterm/xterm/css/xterm.css', () => ({}));
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }));
vi.mock('@xterm/xterm', () => {
  class Terminal {
    constructor() { this.text = ''; this.cols = 100; this.rows = 30; this.listeners = [];
      globalThis.__xterm = this; (globalThis.__xterms ||= []).push(this); }
    loadAddon() {} open(el) { this.el = el; } focus() { this.focused = true; } dispose() {}
    write(s) { this.text += s; if (this.el) this.el.textContent = this.text; }
    reset() { this.text = ''; } clear() { this.text = ''; }
    onData(fn) { this.listeners.push(fn); return { dispose() {} }; }
    onResize() { return { dispose() {} }; }
    type(keys) { this.listeners.forEach((fn) => fn(keys)); }
  }
  return { Terminal };
});
