/**
 * 极简 hash 路由（UX-03 / UX-29）。
 *
 * 7 个页面此前都挂在 `/`：不能深链、刷新回概览、浏览器后退无效。
 * 这里不引入 react-router，只把 page 与 `#/console` 这类 hash 双向同步，
 * 并顺带更新 document.title，便于多标签与录屏。
 */

import { useCallback, useEffect, useState } from 'react';

export type Page =
  | 'overview'
  | 'scenarios'
  | 'console'
  | 'permissions'
  | 'capabilities'
  | 'ops'
  | 'audit';

export const PAGES: readonly Page[] = [
  'overview',
  'scenarios',
  'console',
  'permissions',
  'capabilities',
  'ops',
  'audit',
];

export const PAGE_TITLES: Record<Page, string> = {
  overview: '银行概览',
  scenarios: '场景数据（只读）',
  console: '任务控制台',
  permissions: '权限控制台',
  capabilities: '2A 能力',
  ops: '运维面板',
  audit: '操作审计',
};

export function isPage(value: unknown): value is Page {
  return typeof value === 'string' && (PAGES as readonly string[]).includes(value);
}

export function pageFromHash(hash: string): Page | null {
  const match = /^#\/?([a-z-]+)$/.exec((hash || '').trim());
  if (!match) return null;
  const candidate = match[1];
  return isPage(candidate) ? candidate : null;
}

export function pageHash(page: Page): string {
  return `#/${page}`;
}

export function useHashRoute(fallback: Page = 'overview') {
  const [page, setPage] = useState<Page>(() => {
    if (typeof window === 'undefined') return fallback;
    return pageFromHash(window.location.hash) ?? fallback;
  });

  useEffect(() => {
    const onHashChange = () => {
      setPage(pageFromHash(window.location.hash) ?? fallback);
    };
    window.addEventListener('hashchange', onHashChange);
    // 首次进入时把 `#/overview` 写进地址栏，保证 URL 始终可复制。
    if (!pageFromHash(window.location.hash)) {
      window.history.replaceState(null, '', pageHash(page));
    }
    return () => window.removeEventListener('hashchange', onHashChange);
    // fallback / page 只在挂载时用于初始化，避免重复监听。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fallback]);

  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.title = `AegisBank · ${PAGE_TITLES[page]}`;
    }
  }, [page]);

  const navigate = useCallback((next: Page) => {
    setPage(next);
    if (typeof window !== 'undefined' && window.location.hash !== pageHash(next)) {
      window.location.hash = pageHash(next);
    }
    if (typeof window !== 'undefined') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, []);

  return { page, navigate };
}
