// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchContacts, resolveConfirmation, runAgent } from '../api';
import type { Contact, ContactsResponse } from '../types';
import ContactBook from './ContactBook';

vi.mock('../api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../api')>(),
  fetchContacts: vi.fn(), runAgent: vi.fn(), resolveConfirmation: vi.fn(),
}));

const contact: Contact = {
  contact_id: 'CT-TEST-1', name: '周女士', alias: '小周', phone: '138****5678',
  account_id: 'ACC-****88', relation: 'friend', birthday: null, status: 'active',
};
const response = (contacts: Contact[] = [contact]): ContactsResponse => ({
  contacts, count: contacts.length, simulated: true,
});

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  vi.mocked(fetchContacts).mockResolvedValue(response());
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

function button(label: string): HTMLButtonElement {
  return [...container.querySelectorAll<HTMLButtonElement>('button')]
    .find((item) => item.textContent === label)!;
}

describe('read-only contact book', () => {
  it('shows actual API names, aliases and masked details with reading boundaries', async () => {
    await act(async () => root.render(<ContactBook />));
    expect(container.querySelector('#contact-book h2')?.textContent).toBe('联系人');
    expect(container.textContent).toContain('周女士');
    expect(container.textContent).toContain('小周');
    expect(container.textContent).toContain('好友');
    expect(container.textContent).toContain('138****5678');
    expect(container.textContent).toContain('ACC-****88');
    expect(container.textContent).not.toContain('妈妈');
    const readable = [...container.querySelectorAll('[data-care-reading="true"]')]
      .map((item) => item.textContent).join(' ');
    expect(readable).toContain('周女士');
    expect(readable).toContain('小周');
    expect(readable).not.toContain('138****5678');
    expect(readable).not.toContain('ACC-****88');
    expect(container.querySelectorAll('[data-care-private="true"]')).toHaveLength(2);
    expect(fetchContacts).toHaveBeenCalledOnce();
    expect(runAgent).not.toHaveBeenCalled();
    expect(resolveConfirmation).not.toHaveBeenCalled();
    expect(container.querySelector('form')).toBeNull();
  });

  it('shows loading and disables refresh until the API reply arrives', async () => {
    let finish!: (value: ContactsResponse) => void;
    vi.mocked(fetchContacts).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    await act(async () => root.render(<ContactBook />));
    expect(container.textContent).toContain('正在加载数据');
    expect(button('刷新联系人').disabled).toBe(true);
    expect(container.querySelector('.contact-card')).toBeNull();
    await act(async () => { finish(response()); });
    expect(container.textContent).toContain('周女士');
    expect(button('刷新联系人').disabled).toBe(false);
  });

  it('retains a visible API error and retries the same read-only loader', async () => {
    vi.mocked(fetchContacts).mockRejectedValueOnce(new Error('联系人服务暂不可用'));
    await act(async () => root.render(<ContactBook />));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('联系人服务暂不可用');
    expect(container.textContent).not.toContain('暂无联系人');
    await act(async () => button('重试').click());
    expect(fetchContacts).toHaveBeenCalledTimes(2);
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.textContent).toContain('周女士');
    expect(runAgent).not.toHaveBeenCalled();
  });

  it('shows an empty book without seed contacts and refreshes from the API', async () => {
    vi.mocked(fetchContacts).mockResolvedValueOnce(response([]));
    await act(async () => root.render(<ContactBook />));
    expect(container.textContent).toContain('暂无联系人');
    expect(container.querySelector('.contact-card')).toBeNull();
    expect(button('刷新联系人').disabled).toBe(false);
    await act(async () => button('刷新联系人').click());
    expect(fetchContacts).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain('周女士');
    expect(container.querySelectorAll('.contact-card')).toHaveLength(1);
  });

  it('does not invent missing aliases or private details and handles unknown relations', async () => {
    vi.mocked(fetchContacts).mockResolvedValue(response([{
      ...contact, alias: null, phone: null, account_id: '', relation: 'unsupported_relation',
    }]));
    await act(async () => root.render(<ContactBook />));
    expect(container.textContent).toContain('未设置');
    expect(container.textContent).toContain('关系未分类');
    expect(container.textContent).not.toContain('unsupported_relation');
    expect(container.textContent).not.toContain('138****5678');
    expect(container.textContent).not.toContain('ACC-****88');
    const privateText = [...container.querySelectorAll('[data-care-private="true"]')]
      .map((item) => item.textContent).join(' ');
    expect(privateText.match(/未返回/g)).toHaveLength(2);
  });
});
