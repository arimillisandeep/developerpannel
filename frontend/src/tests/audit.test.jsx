// Tests added by the API audit (build 19).
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Field } from '../components/ui';

vi.mock('axios', () => {
  const instance = { get: vi.fn(), post: vi.fn(), interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } };
  return { default: { create: () => instance }, __instance: instance };
});

describe('Field', () => {
  it('links the label to its input, so the input can be found and focused by its label', () => {
    render(<Field label="Full name"><input defaultValue="Asha" /></Field>);
    expect(screen.getByLabelText('Full name').value).toBe('Asha');
  });

  it('keeps an id that the input already has, and leaves groups of several controls alone', () => {
    render(<><Field label="Email"><input id="my-email" /></Field><Field label="Days"><><input aria-label="from" /><input aria-label="to" /></></Field></>);
    expect(screen.getByLabelText('Email').id).toBe('my-email');
    expect(screen.getByLabelText('from')).toBeTruthy();
  });
});

describe('change password', () => {
  beforeEach(() => localStorage.clear());

  it('stores the new token that the server returns, because the old one stops working', async () => {
    const axios = await import('axios');
    const { setToken, getToken } = await import('../services/api');
    setToken('old-token');
    axios.__instance.post.mockResolvedValue({ data: { ok: true, access_token: 'new-token' } });
    vi.doMock('../context/AuthContext', () => ({ useAuth: () => ({ user: { id: 7 } }) }));
    const { ChangePassword } = await import('../pages/profile/Profile');
    render(<ChangePassword />);
    fireEvent.change(await screen.findByLabelText('Current password'), { target: { value: 'Old@12345' } });
    fireEvent.change(screen.getByLabelText(/New password/), { target: { value: 'New@123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }));
    await waitFor(() => expect(getToken()).toBe('new-token'));
    expect(axios.__instance.post).toHaveBeenCalledWith('/auth/change-password', { current_password: 'Old@12345', new_password: 'New@123456' });
    expect(screen.getByText(/Password changed/)).toBeTruthy();
  });
});
