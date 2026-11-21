import { describe, it, expect, vi, beforeEach } from 'vitest';

// The real axios client (not mocked): checks what actually leaves the browser.
describe('api client', () => {
  beforeEach(() => { localStorage.clear(); vi.resetModules(); vi.unstubAllEnvs(); });

  const sent = async (env) => {
    if (env) vi.stubEnv('VITE_QUERY_TOKEN', '1');
    const mod = await import('../services/api');
    let seen;
    mod.default.defaults.adapter = async (config) => { seen = config; return { data: {}, status: 200, statusText: 'OK', headers: {}, config }; };
    return { mod, get: async (url, opts) => { await mod.default.get(url, opts); return seen; } };
  };

  it('sends no credentials before login', async () => {
    const { get } = await sent();
    const c = await get('/tasks');
    expect(c.headers.Authorization).toBeUndefined();
    expect(c.params).toBeUndefined();
  });

  it('sends the token in both headers after setToken', async () => {
    const { mod, get } = await sent();
    mod.setToken('abc');
    const c = await get('/tasks', { params: { scope: 'mine' } });
    expect(c.headers.Authorization).toBe('Bearer abc');
    expect(c.headers['X-Workcode-Token']).toBe('abc');
    expect(c.params).toEqual({ scope: 'mine' });   // no token in the URL by default
  });

  it('keeps working when browser storage is unavailable', async () => {
    const { mod, get } = await sent();
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    mod.setToken('mem');
    expect((await get('/tasks')).headers.Authorization).toBe('Bearer mem');
    spy.mockRestore(); vi.restoreAllMocks();
  });

  it('adds the token to the path only in a hosted-preview build', async () => {
    const { mod, get } = await sent(true);
    mod.setToken('abc');
    const c = await get('/tasks', { params: { scope: 'mine' } });
    expect(c.url).toBe('/_t/abc/tasks');
    expect(c.params.scope).toBe('mine');
  });
});
