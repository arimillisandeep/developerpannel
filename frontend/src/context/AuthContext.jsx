import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import api, { getToken, report, setToken } from '../services/api';

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadMe = useCallback(async () => {
    if (!getToken()) { setUser(null); setLoading(false); return; }
    try { setUser((await api.get('/auth/me')).data); } catch { setUser(null); } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    loadMe();
    const out = () => setUser(null);
    window.addEventListener('workcode:unauthorized', out);
    return () => window.removeEventListener('workcode:unauthorized', out);
  }, [loadMe]);

  const login = async (email, password) => {
    const { data } = await api.post('/auth/login', { email, password });
    setToken(data.access_token);
    report('after-login', { gotToken: !!data.access_token, tokenReadBack: !!getToken() });
    setUser(data.user);
    return data.user;
  };

  const logout = async () => {
    try { await api.post('/auth/logout'); } catch { /* token may already be invalid */ }
    setToken(null);
    setUser(null);
  };

  return <AuthContext.Provider value={{ user, loading, login, logout, reload: loadMe }}>{children}</AuthContext.Provider>;
}
