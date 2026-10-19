import type { RiskLevel } from './types';

export const riskLabels: Record<RiskLevel, string> = {
  green: '绿色 · 直接执行',
  yellow: '黄色 · 轻量确认',
  red: '红色 · 二次校验',
};

export function riskRank(risk: RiskLevel): number {
  return { green: 0, yellow: 1, red: 2 }[risk];
}

export function isHighRisk(risk: RiskLevel): boolean {
  return risk === 'red';
}

export function formatCny(value: unknown): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return '—';
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    maximumFractionDigits: 2,
  }).format(amount);
}
