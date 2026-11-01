export const CARE_READING_HELP = '先填写银行业务需求，再提交任务。涉及转账或卡片修改时，请核对操作对象和金额，并在页面完成确认。朗读仅提供帮助，不会代替您确认或执行操作。';

const excluded = [
  'input', 'textarea', 'select', 'option', 'button', 'code', 'pre', 'details', 'script', 'style',
  '[data-care-private]', '[data-care-reading="false"]', '.tech-details', '.system-details',
  '.developer-panel', '.care-mode-controls', '.submitted-request', '.command-form',
  '.mfa-method', '.mfa-banner', '.mfa-token-field', '.otp-field',
].join(',');

function visible(element: Element): boolean {
  for (let current: Element | null = element; current; current = current.parentElement) {
    if (current.hasAttribute('hidden') || current.hasAttribute('inert') ||
      current.getAttribute('aria-hidden') === 'true') return false;
    const style = window.getComputedStyle(current);
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false;
  }
  return element.isConnected;
}

function businessText(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? '';
  if (!(node instanceof Element) || node.matches(excluded) || !visible(node)) return '';
  return Array.from(node.childNodes).map(businessText).filter(Boolean).join(' ');
}

export function careReadingSnapshot(): { scope: Element | null; text: string } {
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"]')).filter(visible);
  const scope = dialogs.at(-1) ?? Array.from(document.querySelectorAll('main')).find(visible) ?? null;
  if (!scope) return { scope: null, text: CARE_READING_HELP };
  const markers = Array.from(scope.querySelectorAll('[data-care-reading="true"]'));
  if (scope.matches('[data-care-reading="true"]')) markers.unshift(scope);
  const text = markers.filter((element) =>
    !element.closest(excluded) && !markers.some((parent) => parent !== element && parent.contains(element)))
    .map(businessText).join(' ').replace(/\s+/g, ' ').trim();
  return { scope, text: text || CARE_READING_HELP };
}

export function localChineseVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const local = voices.filter((voice) => voice.localService === true && /^zh(?:[-_]|$)/i.test(voice.lang));
  return local.find((voice) => /^zh[-_]CN$/i.test(voice.lang)) ?? local[0] ?? null;
}
