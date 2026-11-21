import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import api, { wsUrl } from '../services/api';
import { useAuth } from './AuthContext';

const Ctx = createContext(null);
export const useNotifications = () => useContext(Ctx);

export function NotificationProvider({ children }) {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [live, setLive] = useState(false);
  const [version, setVersion] = useState(0); // bumps on every live event so pages can refetch
  const [chatEvent, setChatEvent] = useState(null); // last live chat message
  const wsRef = useRef(null);

  const load = useCallback(async () => {
    try { const { data } = await api.get('/notifications'); setItems(data.items); setUnread(data.unread); } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!user) { setItems([]); setUnread(0); return undefined; }
    load();
    let closed = false, retry = 1000, timer, ping;
    const connect = () => {
      const ws = new WebSocket(wsUrl('/ws'));
      wsRef.current = ws;
      ws.onopen = () => { setLive(true); retry = 1000; ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 25000); };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.event === 'notification') {
          setItems((prev) => [msg.data, ...prev].slice(0, 50));
          setUnread((n) => n + 1);
          setVersion((v) => v + 1);
        } else if (msg.event === 'chat') {
          setChatEvent(msg.data);
        }
      };
      ws.onclose = () => {
        setLive(false); clearInterval(ping);
        if (!closed) { timer = setTimeout(connect, retry); retry = Math.min(retry * 2, 30000); }
      };
    };
    connect();
    const poll = setInterval(load, 60000); // fallback if the socket is blocked
    return () => { closed = true; clearTimeout(timer); clearInterval(ping); clearInterval(poll); wsRef.current?.close(); };
  }, [user, load]);

  const markRead = async (id) => {
    await api.post(`/notifications/${id}/read`);
    setItems((prev) => prev.map((n) => (n.id === id && !n.is_read ? { ...n, is_read: true } : n)));
    setUnread((n) => Math.max(0, n - 1));
  };
  const markAll = async () => { await api.post('/notifications/read-all'); setItems((p) => p.map((n) => ({ ...n, is_read: true }))); setUnread(0); };

  return <Ctx.Provider value={{ items, unread, live, version, chatEvent, markRead, markAll }}>{children}</Ctx.Provider>;
}
