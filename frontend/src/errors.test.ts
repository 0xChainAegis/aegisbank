import { describe, expect, it } from 'vitest';
import {
  describeError,
  isConfirmationExpiredError,
  isTerminalConfirmationError,
} from './errors';

function apiError(status: number, message: string, code?: string): Error {
  return Object.assign(new Error(message), { status, code });
}

describe('describeError (UX-12 / UX-19)', () => {
  it('maps envelope conflicts to "reconfirm" instead of a retry loop', () => {
    const result = describeError(
      apiError(409, 'ActionEnvelope 已过期', 'ENVELOPE_EXPIRED'),
      'confirmation',
    );
    expect(result.action).toBe('reconfirm');
    expect(result.message).toContain('重新发起');
    expect(result.detail).toContain('已过期');
  });

  it('keeps the modal open for MFA failures', () => {
    const result = describeError(
      apiError(403, '二次身份校验失败：OTP 校验失败，请检查演示验证码。'),
      'confirmation',
    );
    expect(result.action).toBe('retry');
    expect(result.message).toContain('验证未通过');
  });

  it('closes the dialog for terminal 422 / 400 errors', () => {
    const failed = describeError(apiError(422, '工具执行失败：余额不足'), 'confirmation');
    expect(failed.action).toBe('refresh');
    expect(failed.message).toContain('操作未执行');

    const duplicate = describeError(apiError(400, '确认请求已处理：expired'), 'confirmation');
    expect(duplicate.action).toBe('refresh');
    expect(duplicate.message).toContain('请求未被接受');
  });

  it('treats 503 and network failures as retryable with readable copy', () => {
    const notReady = describeError(apiError(503, '服务未就绪'), 'run');
    expect(notReady.action).toBe('retry');
    expect(notReady.message).toContain('尚未就绪');

    const offline = describeError({ status: 0, message: '无法连接后端服务' }, 'run');
    expect(offline.action).toBe('retry');
    expect(offline.message).toContain('无法连接');
  });

  it('classifies terminal vs recoverable confirmation errors', () => {
    expect(isConfirmationExpiredError(apiError(409, 'expired'))).toBe(true);
    expect(isTerminalConfirmationError(apiError(409, 'expired'))).toBe(true);
    expect(isTerminalConfirmationError(apiError(422, 'failed'))).toBe(true);
    expect(isTerminalConfirmationError(apiError(403, 'otp'))).toBe(false);
    expect(isTerminalConfirmationError(apiError(503, 'not ready'))).toBe(false);
  });
});
