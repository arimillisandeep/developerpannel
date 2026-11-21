import api from '../services/api';

/** Download a protected file through the API (the token travels in the header, not in the address). */
export async function downloadFile(url, filename) {
  const r = await api.get(url, { responseType: 'blob' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(r.data);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
