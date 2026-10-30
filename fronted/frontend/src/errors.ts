/**
 * 统一错误解释层（UX-12 / UX-19）。
 *
 * 后端已经区分 409 / 422 / 400 / 503 等语义，但界面此前只把它们当成一条红字。
 * 这里把「HTTP 状态 + 业务 code」翻译成可执行的下一步动作，供 App 与弹窗消费。
 */

export type ErrorAction = 'retry' | 'reconfirm' | 'refresh';

export type ErrorContext = 'run' | 'confirmation';

export interface ErrorExplanation {
  /** 给用户看的文案。 */
  message: string;
  /** 界面下一步动作：可重试 / 需重新发起 / 关闭并刷新。 */
  action: ErrorAction;
  /** 原始技术信息，放到「技术详情」里，不直接铺在正文。 */
  detail: string;
}

interface ErrorLike {
  status?: unknown;
  code?: unknown;
  message?: unknown;
}

function asErrorLike(error: unknown): ErrorLike {
  if (error !== null && typeof error === 'object') return error as ErrorLike;
  return {};
}

function statusOf(error: unknown): number {
  const value = asErrorLike(error).status;
  return typeof value === 'number' ? value : 0;
}

function codeOf(error: unknown): string {
  const value = asErrorLike(error).code;
  return typeof value === 'string' ? value : '';
}

function messageOf(error: unknown): string {
  const value = asErrorLike(error).message;
  if (typeof value === 'string' && value.trim()) return value.trim();
  return '请求失败，请稍后重试。';
}

export function isConfirmationExpiredError(error: unknown): boolean {
  const status = statusOf(error);
  const code = codeOf(error);
  return (status === 409 && !isInProgress(error)) || code.startsWith('ENVELOPE_');
}

function isInProgress(error: unknown): boolean {
  return ['ACTION_IN_PROGRESS', 'IDEMPOTENCY_IN_PROGRESS'].includes(codeOf(error));
}

/** 终态错误：弹窗应关闭并刷新，而不是让用户对着一个永远失败的重试按钮。 */
export function isTerminalConfirmationError(error: unknown): boolean {
  const status = statusOf(error);
  return !isInProgress(error) && (status === 409 || status === 400 || status === 422);
}

export function describeError(error: unknown, context: ErrorContext = 'run'): ErrorExplanation {
  const status = statusOf(error);
  const code = codeOf(error);
  const raw = messageOf(error);

  if (isInProgress(error)) {
    return { message: '原请求仍在处理中，请保留当前操作并查询原结果。', action: 'retry', detail: raw };
  }

  if (code.toLowerCase() === 'draft_version_conflict') {
    return {
      message: `旧确认已被新草稿替代（${code}），请改用最新确认或重新发起任务。`,
      action: 'reconfirm',
      detail: raw.includes(code) ? raw : `${raw}（${code}）`,
    };
  }

  if (status === 403 && /验证|OTP|token|生物识别|二次身份/i.test(raw)) {
    return { message: `验证未通过：${raw}`, action: 'retry', detail: raw };
  }
  if (code === 'IDEMPOTENCY_KEY_REUSED') {
    return {
      message: '提交内容已变化，不能复用上一次请求；请重新发起。',
      action: 'reconfirm',
      detail: raw,
    };
  }
  if (status === 409 || code.startsWith('ENVELOPE_')) {
    return {
      message: '这次确认已失效（计划、额度或状态已变化），需要重新发起。',
      action: 'reconfirm',
      detail: raw,
    };
  }
  if (status === 422) {
    return {
      message: `请求未完成：${raw}。请核对步骤记录和账户结果。`,
      action: context === 'confirmation' ? 'refresh' : 'retry',
      detail: raw,
    };
  }
  if (status === 400) {
    return { message: `请求未被接受：${raw}`, action: 'refresh', detail: raw };
  }
  if (status === 503) {
    return {
      message: '系统尚未就绪，写操作已被暂停；恢复后可以重试。',
      action: 'retry',
      detail: raw,
    };
  }
  if (status === 0) {
    return {
      message: '连接中断或超时，执行结果尚未确认；请使用原请求查询结果。',
      action: 'retry',
      detail: raw,
    };
  }
  return { message: raw, action: 'retry', detail: raw };
}
