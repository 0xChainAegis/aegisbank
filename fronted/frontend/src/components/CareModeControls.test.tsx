// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CareModeControls from './CareModeControls';
import { CARE_READING_HELP } from './careSpeech';
import ConfirmationModal from './ConfirmationModal';
import type { RunResponse } from '../types';

const KEY = 'aegisbank.care-mode.v1';
const localVoice = { name: '本机中文', voiceURI: 'local-zh', lang: 'zh-CN', localService: true, default: false } as SpeechSynthesisVoice;
const remoteVoice = { name: '在线中文', voiceURI: 'remote-zh', lang: 'zh-CN', localService: false, default: true } as SpeechSynthesisVoice;
const englishVoice = { name: 'Local English', voiceURI: 'local-en', lang: 'en-US', localService: true, default: false } as SpeechSynthesisVoice;

class FakeUtterance {
  text: string;
  voice: SpeechSynthesisVoice | null = null;
  lang = '';
  rate = 1;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

let voices: SpeechSynthesisVoice[];
let spoken: FakeUtterance[];
let engine: EventTarget & { getVoices: ReturnType<typeof vi.fn>; speak: ReturnType<typeof vi.fn>; cancel: ReturnType<typeof vi.fn> };
let root: Root | null;
let container: HTMLDivElement;
let business: HTMLElement;

beforeEach(() => {
  vi.restoreAllMocks();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  document.documentElement.removeAttribute('data-care-mode');
  voices = [remoteVoice, englishVoice, localVoice];
  spoken = [];
  engine = Object.assign(new EventTarget(), {
    getVoices: vi.fn(() => voices),
    speak: vi.fn((value: FakeUtterance) => spoken.push(value)),
    cancel: vi.fn(),
  });
  vi.stubGlobal('speechSynthesis', engine);
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance);
  business = document.createElement('main');
  business.innerHTML = '<p data-care-reading="true">转账金额八百八十元，请核对收款账户。</p>';
  document.body.append(business);
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = null;
  container.remove(); business.remove();
  document.querySelectorAll('[data-care-test-dialog]').forEach((element) => element.remove());
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function mount() { await act(async () => root!.render(<CareModeControls />)); }
async function click(label: string) {
  const button = [...container.querySelectorAll('button')].find((item) => item.textContent === label)!;
  await act(async () => button.click());
}
function button(label: string) {
  return [...container.querySelectorAll('button')].find((item) => item.textContent === label)!;
}
async function begin() { await mount(); await click('关怀模式'); await click('朗读当前内容'); }

describe('care mode controls', () => {
  it('persists the display switch without speaking automatically, including after remount', async () => {
    await mount();
    expect(button('关怀模式').getAttribute('aria-pressed')).toBe('false');
    await click('关怀模式');
    expect(button('关怀模式').getAttribute('aria-pressed')).toBe('true');
    expect(document.documentElement.getAttribute('data-care-mode')).toBe('true');
    expect(localStorage.getItem(KEY)).toBe('true');
    await act(async () => root!.unmount());
    root = createRoot(container);
    await mount();
    expect(button('关怀模式').getAttribute('aria-pressed')).toBe('true');
    expect(engine.speak).not.toHaveBeenCalled();
    await click('关怀模式');
    expect(localStorage.getItem(KEY)).toBe('false');
    expect(document.documentElement.getAttribute('data-care-mode')).toBe('false');
  });

  it('still toggles when local storage reads and writes throw', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('full'); });
    await mount(); await click('关怀模式');
    expect(document.documentElement.getAttribute('data-care-mode')).toBe('true');
    await click('关怀模式');
    expect(document.documentElement.getAttribute('data-care-mode')).toBe('false');
  });

  it('uses only a local Chinese voice after a click and can recover after ending', async () => {
    await begin();
    expect(engine.speak).toHaveBeenCalledTimes(1);
    expect(spoken[0].voice).toBe(localVoice);
    expect(spoken[0].text).toContain('转账金额八百八十元');
    expect(button('朗读当前内容').disabled).toBe(true);
    await act(async () => spoken[0].onend?.());
    expect(button('朗读当前内容').disabled).toBe(false);
    expect(container.textContent).toContain('朗读已结束');
    await click('朗读当前内容');
    expect(engine.speak).toHaveBeenCalledTimes(2);
  });

  it('updates on voiceschanged and never falls back to remote Chinese or local English', async () => {
    voices = [remoteVoice, englishVoice];
    await mount(); await click('关怀模式');
    expect(button('朗读当前内容').disabled).toBe(true);
    expect(container.textContent).toContain('未找到本机中文语音');
    expect(document.documentElement.getAttribute('data-care-mode')).toBe('true');
    voices = [localVoice];
    await act(async () => engine.dispatchEvent(new Event('voiceschanged')));
    expect(button('朗读当前内容').disabled).toBe(false);
    expect(engine.speak).not.toHaveBeenCalled();
    await click('朗读当前内容');
    expect(spoken[0].voice?.localService).toBe(true);
  });

  it('keeps large text available without browser speech support', async () => {
    vi.stubGlobal('speechSynthesis', undefined);
    await mount(); await click('关怀模式');
    expect(container.textContent).toContain('此浏览器不支持语音朗读');
    expect(button('朗读当前内容').disabled).toBe(true);
    expect(document.documentElement.getAttribute('data-care-mode')).toBe('true');
  });

  it('rechecks local voice availability when the user requests speech', async () => {
    await mount(); await click('关怀模式');
    voices = [remoteVoice];
    await click('朗读当前内容');
    expect(engine.speak).not.toHaveBeenCalled();
    expect(container.textContent).toContain('未找到本机中文语音');
  });

  it('excludes inputs, OTP, user requests, hidden nodes and technical content even inside markers', async () => {
    business.innerHTML = `<section data-care-reading="true">安全业务摘要
      <input value="input-secret"><textarea>textarea-secret</textarea>
      <div class="mfa-method">OTP-secret <code>246810</code></div>
      <div data-care-private="true">private-secret</div>
      <p class="submitted-request">user-request-secret</p>
      <details open><summary>技术详情</summary>technical-secret</details>
      <div hidden>hidden-secret</div><div style="display:none">display-secret</div>
      <div aria-hidden="true">aria-secret</div><div data-care-reading="false">excluded-secret</div>
      <button>button-secret</button><p data-care-reading="true">嵌套摘要</p>
    </section>`;
    await begin();
    expect(spoken[0].text).toContain('安全业务摘要');
    expect(spoken[0].text).toContain('嵌套摘要');
    expect(spoken[0].text.match(/嵌套摘要/g)).toHaveLength(1);
    expect(spoken[0].text).not.toMatch(/secret|246810|技术详情/);
  });

  it('reads only the current dialog and cancels when that dialog closes', async () => {
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog'); dialog.setAttribute('data-care-test-dialog', '');
    dialog.innerHTML = '<p data-care-reading="true">确认挂失尾号九九零二的卡片。</p>';
    document.body.append(dialog);
    await begin();
    expect(spoken[0].text).toContain('确认挂失');
    expect(spoken[0].text).not.toContain('转账金额');
    await act(async () => { dialog.remove(); await Promise.resolve(); });
    expect(engine.cancel).toHaveBeenCalledTimes(1);
    expect(button('朗读当前内容').disabled).toBe(false);
  });

  it('uses fixed help when no visible trusted marker is available instead of scanning the page', async () => {
    business.innerHTML = '<p>unmarked-secret</p><div hidden data-care-reading="true">hidden-secret</div>';
    await begin();
    expect(spoken[0].text).toBe(CARE_READING_HELP);
    expect(spoken[0].text).not.toContain('secret');
  });

  it.each(['stop', 'disable', 'hashchange', 'unmount'])('cancels owned speech on %s', async (action) => {
    await begin();
    if (action === 'stop') await click('停止朗读');
    if (action === 'disable') await click('关怀模式');
    if (action === 'hashchange') await act(async () => window.dispatchEvent(new Event('hashchange')));
    if (action === 'unmount') { await act(async () => root!.unmount()); root = null; }
    expect(engine.cancel).toHaveBeenCalledTimes(1);
    expect(spoken[0].onend).toBeNull();
    expect(spoken[0].onerror).toBeNull();
    expect(engine.speak).toHaveBeenCalledTimes(1);
  });

  it('cancels stale speech when business text changes and does not start new speech', async () => {
    await begin();
    await act(async () => { business.querySelector('p')!.textContent = '新的业务摘要'; await Promise.resolve(); });
    expect(engine.cancel).toHaveBeenCalledTimes(1);
    expect(engine.speak).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain('页面内容已变化');
  });

  it('recovers from speech errors and synchronous speech failure', async () => {
    await begin();
    await act(async () => spoken[0].onerror?.());
    expect(container.textContent).toContain('朗读未完成');
    expect(button('朗读当前内容').disabled).toBe(false);
    engine.speak.mockImplementationOnce(() => { throw new Error('unavailable'); });
    await click('朗读当前内容');
    expect(button('朗读当前内容').disabled).toBe(false);
    expect(container.textContent).toContain('朗读暂不可用');
  });
});

describe('confirmation dialog care controls', () => {
  it('keeps U2 amount revision separate from speech and stops reading a superseded draft', async () => {
    localStorage.setItem(KEY, 'true');
    const onDecision = vi.fn();
    const onAmend = vi.fn();
    const pending = (amount: number, version: number): RunResponse => ({
      status: 'awaiting_confirmation', run_id: `run-${version}`, reason: '需要演示身份验证',
      risk_level: 'red',
      confirmation: { id: `confirm-${version}`, requires_reauth: true,
        expires_at: new Date(Date.now() + 300_000).toISOString() },
      draft: { draft_id: `draft-${version}`, session_id: 'session-care', version,
        status: 'awaiting_confirmation', amount_cny: amount },
      plan: { intent: 'transfer', planner: 'rule', confidence: 1, assumptions: [], steps: [
        { id: 'step-1', tool_name: 'transfer', depends_on: [],
          arguments: { from_account: 'ACC-1001', to_account: 'ACC-2002', amount_cny: amount,
            note: '自由输入私密备注' } },
      ] },
    });
    const render = async (amount: number, version: number, expired = false) => {
      const run = pending(amount, version);
      if (expired) run.confirmation!.expires_at = new Date(Date.now() - 10_000).toISOString();
      await act(async () => root!.render(<>
        <CareModeControls key="page" />
        <ConfirmationModal key="confirm" pending={run} busy={false}
          mfaToken="123456" setMfaToken={vi.fn()} mfaProvider="otp" setMfaProvider={vi.fn()}
          mfaProviders={[{ name: 'otp', kind: 'otp', title: '演示验证码', enabled: true }]}
          mfaProvidersLoading={false} mfaProvidersError="" onRefreshMfaProviders={vi.fn()}
          onDecision={onDecision} onAmend={onAmend} onClose={vi.fn()}
          writesBlocked={false} blockReason="" />
      </>));
    };
    await render(880, 2);
    await click('修改金额');
    expect(container.querySelector('.amend-form')).not.toBeNull();
    expect(engine.speak).not.toHaveBeenCalled();
    await click('朗读本次确认');
    expect(spoken[0].text).toContain('880');
    expect(spoken[0].text).not.toMatch(/123456|246810|自由输入私密备注|提交修改/);
    await render(500, 3);
    await act(async () => { await Promise.resolve(); });
    expect(engine.cancel).toHaveBeenCalledTimes(1);
    expect(engine.speak).toHaveBeenCalledTimes(1);
    expect(container.querySelector('.amend-form')).toBeNull();
    await click('朗读本次确认');
    expect(spoken[1].text).toContain('500');
    expect(spoken[1].text).not.toContain('880');
    await render(500, 3, true);
    await act(async () => { await Promise.resolve(); });
    expect(engine.cancel).toHaveBeenCalledTimes(2);
    expect(engine.speak).toHaveBeenCalledTimes(2);
    await click('朗读本次确认');
    expect(spoken[2].text).toContain('确认已过期');
    expect(spoken[2].text).toContain('不能继续执行');
    expect(onDecision).not.toHaveBeenCalled();
    expect(onAmend).not.toHaveBeenCalled();
  });

  it('stops its own speech when closed without resetting the page mode or stored setting', async () => {
    await act(async () => root!.render(<><CareModeControls key="page" /></>));
    await click('关怀模式');
    const writes = vi.spyOn(Storage.prototype, 'setItem');
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog'); dialog.setAttribute('data-care-test-dialog', '');
    dialog.innerHTML = '<p data-care-reading="true">请确认挂失卡片。</p>';
    document.body.append(dialog);
    await act(async () => root!.render(<>
      <CareModeControls key="page" /><CareModeControls key="dialog" surface="dialog" />
    </>));
    expect(container.querySelectorAll('.care-mode-toggle')).toHaveLength(1);
    expect(engine.speak).not.toHaveBeenCalled();
    await click('朗读本次确认');
    await act(async () => {
      root!.render(<><CareModeControls key="page" /></>);
      dialog.remove();
    });
    expect(engine.cancel).toHaveBeenCalledTimes(1);
    expect(document.documentElement.getAttribute('data-care-mode')).toBe('true');
    expect(button('关怀模式').getAttribute('aria-pressed')).toBe('true');
    expect(localStorage.getItem(KEY)).toBe('true');
    expect(writes).not.toHaveBeenCalled();
  });

  it('reads only the dialog business summary and does not cancel another instance on cleanup', async () => {
    localStorage.setItem(KEY, 'true');
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog'); dialog.setAttribute('data-care-test-dialog', '');
    dialog.innerHTML = `<section data-care-reading="true">确认向妈妈转账五百元。
      <div class="mfa-method">OTP-secret <code>246810</code><input value="123456"></div>
      <p data-care-private="true">private-secret</p>
    </section>`;
    document.body.append(dialog);
    await act(async () => root!.render(<>
      <CareModeControls key="page" /><CareModeControls key="dialog" surface="dialog" />
    </>));
    await click('朗读本次确认');
    expect(spoken[0].voice).toBe(localVoice);
    expect(spoken[0].text).toContain('确认向妈妈转账五百元');
    expect(spoken[0].text).not.toMatch(/八百八十|secret|246810|123456/);
    // A different care control may take ownership after an explicit click.
    await click('朗读当前内容');
    expect(engine.cancel).toHaveBeenCalledTimes(1);
    expect(engine.speak).toHaveBeenCalledTimes(2);
    await act(async () => root!.render(<><CareModeControls key="page" /></>));
    expect(engine.cancel).toHaveBeenCalledTimes(1);
    expect(spoken[1].onend).not.toBeNull();
    expect(document.documentElement.getAttribute('data-care-mode')).toBe('true');
  });
});
