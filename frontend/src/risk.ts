import type { RiskLevel } from './types';

export const riskLabels: Record<RiskLevel, string> = {
  green: '绿色 · 直接执行',
  yellow: '黄色 · 轻量确认',
  red: '红色 · MFA 校验',
};

export const riskShortLabels: Record<RiskLevel, string> = {
  green: '低风险',
  yellow: '中风险',
  red: '高风险',
};

export const riskDescriptions: Record<RiskLevel, string> = {
  green: '只读或无资金变动的查询操作，满足最小权限即可执行。',
  yellow: '会修改账户或卡片设置的轻量变更，需要一次明确确认。',
  red: '涉及资金变动或高风险卡操作，需要 MFA/OTP 二次校验。',
};

export function riskRank(risk: RiskLevel): number {
  return { green: 0, yellow: 1, red: 2 }[risk];
}

export function highestRisk(risks: RiskLevel[]): RiskLevel {
  return risks.reduce<RiskLevel>(
    (highest, current) => (riskRank(current) > riskRank(highest) ? current : highest),
    'green',
  );
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

export function formatCompactCny(value: number): string {
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}
