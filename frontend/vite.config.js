import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The browser only ever calls relative /api and /ws; Vite forwards them to FastAPI.
const backend = process.env.WORKCODE_API || 'http://127.0.0.1:8000';
const proxy = {
  '/api': { target: backend, changeOrigin: true },
  '/ws': { target: backend, ws: true, changeOrigin: true },
};
// WORKCODE_WS: where WebSockets really live (e.g. http://localhost:8000 in Docker). Empty = same address as the
// page, forwarded by this dev server's proxy. Vite's proxy drops WebSocket upgrades now and then, so Docker sets it.
const wsBase = process.env.WORKCODE_WS || '';
const common = { host: '0.0.0.0', port: 5173, strictPort: true, allowedHosts: true, proxy };

export default defineConfig({
  plugins: [react()],
  server: common,
  preview: { ...common, headers: { 'Cache-Control': 'no-store' } },
  define: { __WC_WS_BASE__: JSON.stringify(wsBase) },      // read by services/api.js (wsBase/wsUrl)
  build: { chunkSizeWarningLimit: 5000 },
  test: { environment: 'jsdom', setupFiles: './src/setupTests.js', globals: true },
});
