import { useCallback, useEffect, useRef, useState } from 'react';
import { careReadingSnapshot, localChineseVoice } from './careSpeech';

const STORAGE_KEY = 'aegisbank.care-mode.v1';
let activeSpeech: { owner: symbol; utterance: SpeechSynthesisUtterance; stop: () => void } | null = null;

interface Props {
  surface?: 'page' | 'dialog';
}

function savedMode(): boolean {
  try { return window.localStorage.getItem(STORAGE_KEY) === 'true'; }
  catch { return false; }
}

export default function CareModeControls({ surface = 'page' }: Props) {
  const [enabled, setEnabled] = useState(savedMode);
  const [supported, setSupported] = useState(false);
  const [voice, setVoice] = useState<SpeechSynthesisVoice | null>(null);
  const [reading, setReading] = useState(false);
  const [message, setMessage] = useState('');
  const mounted = useRef(true);
  const synth = useRef<SpeechSynthesis | null>(null);
  const utterance = useRef<SpeechSynthesisUtterance | null>(null);
  const observer = useRef<MutationObserver | null>(null);
  const owner = useRef(Symbol('care-speech-owner'));

  const stopReading = useCallback((notice = '') => {
    observer.current?.disconnect();
    observer.current = null;
    const current = utterance.current;
    utterance.current = null;
    if (current) {
      current.onend = null;
      current.onerror = null;
      if (activeSpeech?.owner === owner.current && activeSpeech.utterance === current) {
        activeSpeech = null;
        try { synth.current?.cancel(); } catch { /* The display controls still work. */ }
      }
    }
    if (mounted.current) {
      setReading(false);
      setMessage(notice);
    }
  }, []);

  useEffect(() => {
    if (surface === 'dialog') return;
    document.documentElement.setAttribute('data-care-mode', String(enabled));
    try { window.localStorage.setItem(STORAGE_KEY, String(enabled)); }
    catch { /* Storage is optional; the current page can still change mode. */ }
    if (!enabled) stopReading();
  }, [enabled, stopReading, surface]);

  useEffect(() => {
    mounted.current = true;
    let engine: SpeechSynthesis | null = null;
    try {
      if (typeof window.SpeechSynthesisUtterance === 'function' && window.speechSynthesis) {
        engine = window.speechSynthesis;
      }
    } catch { /* Some browsers expose an unavailable speech service. */ }
    synth.current = engine;
    setSupported(Boolean(engine));
    const updateVoices = () => {
      let next: SpeechSynthesisVoice | null = null;
      try { next = engine ? localChineseVoice(engine.getVoices()) : null; } catch { /* No usable voice. */ }
      setVoice(next);
      if (utterance.current && !next) stopReading('本机中文语音已不可用，朗读已停止；大字模式仍可使用。');
    };
    updateVoices();
    engine?.addEventListener('voiceschanged', updateVoices);
    const onPageChange = () => {
      if (utterance.current) stopReading('页面已切换，朗读已停止。');
    };
    window.addEventListener('hashchange', onPageChange);
    return () => {
      mounted.current = false;
      engine?.removeEventListener('voiceschanged', updateVoices);
      window.removeEventListener('hashchange', onPageChange);
      stopReading();
      synth.current = null;
      if (surface === 'page') document.documentElement.setAttribute('data-care-mode', 'false');
    };
  }, [stopReading, surface]);

  function readCurrent() {
    if (!enabled || !voice || !synth.current || reading) return;
    setMessage('');
    try {
      // Recheck the local-only voice at the user gesture, not just at mount.
      const available = synth.current.getVoices().filter((item) =>
        item.voiceURI === voice.voiceURI && item.localService === true && /^zh(?:[-_]|$)/i.test(item.lang));
      const selected = localChineseVoice(available);
      if (!selected) {
        setVoice(null);
        setMessage('未找到本机中文语音；大字模式仍可使用。');
        return;
      }
      const snapshot = careReadingSnapshot();
      const current = new window.SpeechSynthesisUtterance(snapshot.text);
      current.voice = selected;
      current.lang = selected.lang;
      current.rate = 0.85;
      activeSpeech?.stop();
      utterance.current = current;
      activeSpeech = { owner: owner.current, utterance: current,
        stop: () => stopReading('已切换朗读内容。') };
      setReading(true);
      current.onend = () => {
        if (utterance.current !== current) return;
        utterance.current = null;
        if (activeSpeech?.owner === owner.current && activeSpeech.utterance === current) activeSpeech = null;
        observer.current?.disconnect();
        observer.current = null;
        setReading(false);
        setMessage('朗读已结束。');
      };
      current.onerror = () => {
        if (utterance.current === current) stopReading('朗读未完成，请重试；大字模式仍可使用。');
      };
      observer.current = new MutationObserver(() => {
        const latest = careReadingSnapshot();
        if (latest.scope !== snapshot.scope || latest.text !== snapshot.text) {
          stopReading('页面内容已变化，朗读已停止。');
        }
      });
      observer.current.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
      synth.current.speak(current);
    } catch {
      stopReading('朗读暂不可用，请重试；大字模式仍可使用。');
    }
  }

  const availability = !supported
    ? '此浏览器不支持语音朗读；大字模式仍可使用。'
    : !voice ? '未找到本机中文语音；大字模式仍可使用。'
      : reading ? '正在使用本机中文语音朗读。' : '点击后使用本机中文语音朗读当前业务摘要。';

  if (surface === 'dialog' && !enabled) return null;

  return (
    <section className={`care-mode-controls${surface === 'dialog' ? ' care-dialog-controls' : ''}`}
      aria-label={surface === 'dialog' ? '本次确认朗读' : '关怀模式设置'}>
      {surface === 'page' && (
        <button type="button" className="care-mode-toggle ghost-button small-button" aria-pressed={enabled}
          onClick={() => setEnabled((value) => !value)}>关怀模式</button>
      )}
      {enabled && (
        <>
          {surface === 'page' && <p>已开启大字显示。朗读由您点击后开始，只读业务摘要；不朗读输入内容、验证码和技术详情。</p>}
          <div className="care-speech-controls">
            <button type="button" className="ghost-button small-button" disabled={!supported || !voice || reading}
              onClick={readCurrent}>{surface === 'dialog' ? '朗读本次确认' : '朗读当前内容'}</button>
            <button type="button" className="ghost-button small-button" disabled={!reading}
              onClick={() => stopReading('朗读已停止。')}>停止朗读</button>
          </div>
          <p className="care-mode-status" role="status" aria-live="polite">{message || availability}</p>
        </>
      )}
    </section>
  );
}
