import { describe, expect, it } from 'vitest';
import { formatCny, isHighRisk, riskRank } from './risk';

describe('risk helpers', () => {
  it('orders risk levels from green to red', () => {
    expect(riskRank('green')).toBeLessThan(riskRank('yellow'));
    expect(riskRank('yellow')).toBeLessThan(riskRank('red'));
  });

  it('only marks red as high risk', () => {
    expect(isHighRisk('red')).toBe(true);
    expect(isHighRisk('yellow')).toBe(false);
  });

  it('formats CNY values for the console', () => {
    expect(formatCny(880)).toContain('880.00');
  });
});
