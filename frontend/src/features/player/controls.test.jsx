import { describe, expect, it, vi, afterEach } from 'vitest';
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { qualityLabel, qualityOptions, sameLanguage, trackLabels } from './engines/tracks';
import { applyPreferences } from './prefs';
import { keyName, resolveShortcuts } from './shortcuts';
import { useChannelEntry } from './hooks/useChannelEntry';
import { useEndgame } from './hooks/useEndgame';
import { SettingsMenu, ShortcutHelp } from './components/PlayerMenus';

describe('track model', () => {
  it('one option per height, highest bitrate wins, nothing above the plan ceiling, best first', () => {
    const levels = [
      { height: 720, bitrate: 2_000_000 },
      { height: 1080, bitrate: 5_000_000 },
      { height: 720, bitrate: 3_000_000 },
      { height: 360, bitrate: 600_000 },
      { height: 0, bitrate: 64_000 }, // audio-only rendition: not a picture quality
    ];
    expect(qualityOptions(levels)).toEqual([
      { id: 1, height: 1080, bitrate: 5_000_000 },
      { id: 2, height: 720, bitrate: 3_000_000 },
      { id: 3, height: 360, bitrate: 600_000 },
    ]);
    expect(qualityOptions(levels, 720).map((q) => q.height)).toEqual([720, 360]);
    expect(qualityLabel(1080)).toBe('1080p HD');
    expect(qualityLabel(2160)).toBe('2160p 4K');
  });

  it('labels tracks by language in Turkish; a shared language is told apart by its name', () => {
    const tracks = [{ lang: 'tr' }, { lang: 'en', name: 'English' }, { lang: 'en', name: 'Commentary' }, {}];
    expect(trackLabels(tracks, { locale: 'tr', unnamed: (n) => `Parça ${n}` })).toEqual(['Türkçe', 'İngilizce (English)', 'İngilizce (Commentary)', 'Parça 4']);
    expect(trackLabels(tracks, { locale: 'en' }).slice(0, 2)).toEqual(['Turkish', 'English']); // the viewer's language, not the track's
    expect(sameLanguage('en-US', 'en')).toBe(true);
    expect(sameLanguage('tr', null)).toBe(false);
  });
});

describe('remembered languages', () => {
  const engine = () => ({ select: vi.fn() });
  const snap = { text: [{ id: 0, lang: 'en' }, { id: 1, lang: 'tr' }], textId: 0, audio: [{ id: 0, lang: 'en' }, { id: 1, lang: 'tr' }], audioId: 0 };

  it('picks the remembered subtitle and audio language once per source', () => {
    const e = engine();
    const applied = { text: false, audio: false };
    applyPreferences(e, snap, { textLang: 'tr', audioLang: 'tr-TR' }, applied);
    applyPreferences(e, snap, { textLang: 'tr', audioLang: 'tr-TR' }, applied); // later track events: no fight with the viewer
    expect(e.select.mock.calls).toEqual([
      ['text', 1],
      ['audio', 1],
    ]);
  });

  it('"off" on purpose stays off; an unavailable language changes nothing', () => {
    const e = engine();
    applyPreferences(e, snap, { textLang: 'off' }, { text: false, audio: false });
    expect(e.select).toHaveBeenCalledWith('text', -1);
    const f = engine();
    applyPreferences(f, snap, { textLang: 'de' }, { text: false, audio: false });
    expect(f.select).not.toHaveBeenCalled();
  });
});

describe('shortcuts', () => {
  it('extra shortcuts take over keys; the help lists what each key really does', () => {
    const vol = vi.fn();
    const { byKey, list } = resolveShortcuts(
      [{ keys: ['ArrowUp', '+'], label: 'Sesi aç', run: vol }],
      [{ keys: ['ArrowUp'], label: 'Sonraki kanal', run: () => {} }],
    );
    expect(byKey.get('ArrowUp').label).toBe('Sonraki kanal');
    expect(byKey.get('+').run).toBe(vol);
    expect(list).toEqual([
      { keys: ['+'], label: 'Sesi aç' },
      { keys: ['↑'], label: 'Sonraki kanal' },
    ]);
    expect([keyName(' ', { space: 'Boşluk' }), keyName('N'), keyName('i')]).toEqual(['Boşluk', 'Shift+N', 'İ']);
    expect(keyName('i', { locale: 'en' })).toBe('I'); // Turkish dotted İ only in Turkish
  });
});

describe('channel number entry', () => {
  afterEach(() => vi.useRealTimers());

  it('commits at once when no longer number is possible, after a pause otherwise', () => {
    vi.useFakeTimers();
    const onPick = vi.fn();
    const { result } = renderHook(() => useChannelEntry(40, onPick));
    act(() => result.current.press('1'));
    act(() => result.current.press('2'));
    expect(onPick).toHaveBeenLastCalledWith(11); // "12" of 40: two digits, done

    act(() => result.current.press('7')); // 70 > 40: no second digit can follow
    expect(onPick).toHaveBeenLastCalledWith(6);

    act(() => result.current.press('3'));
    expect(onPick).toHaveBeenCalledTimes(2);
    act(() => vi.advanceTimersByTime(1500));
    expect(onPick).toHaveBeenLastCalledWith(2);
  });

  it('a number that does not exist says so and clears', () => {
    vi.useFakeTimers();
    const onPick = vi.fn();
    const { result } = renderHook(() => useChannelEntry(40, onPick));
    act(() => result.current.press('4'));
    act(() => result.current.press('5'));
    expect(result.current).toMatchObject({ digits: '45', invalid: true });
    act(() => vi.advanceTimersByTime(1500));
    expect(result.current.digits).toBe('');
    expect(onPick).not.toHaveBeenCalled();
  });
});

describe('post-play phases', () => {
  const fakeVideo = (duration) => Object.assign(new EventTarget(), { duration, currentTime: 0, ended: false });

  it('credits in the closing seconds, ended at the end, back to watching after seeking back', () => {
    const video = fakeVideo(600);
    const { result } = renderHook(() => useEndgame(video, { enabled: true }));
    const at = (t, ended = false) => act(() => Object.assign(video, { currentTime: t, ended }).dispatchEvent(new Event('timeupdate')));
    at(100);
    expect(result.current).toBeNull();
    at(585);
    expect(result.current).toBe('credits');
    at(600, true);
    expect(result.current).toBe('ended');
    at(300);
    expect(result.current).toBeNull();
  });

  it('uses the exact credits start when known; short clips get no post-play', () => {
    const video = fakeVideo(600);
    const { result } = renderHook(() => useEndgame(video, { enabled: true, creditsAt: 540 }));
    act(() => Object.assign(video, { currentTime: 545 }).dispatchEvent(new Event('timeupdate')));
    expect(result.current).toBe('credits');
    const clip = fakeVideo(30);
    const short = renderHook(() => useEndgame(clip, { enabled: true }));
    act(() => Object.assign(clip, { currentTime: 25 }).dispatchEvent(new Event('timeupdate')));
    expect(short.result.current).toBeNull();
  });
});

describe('settings menu', () => {
  const tracks = {
    quality: [{ id: 2, height: 1080 }, { id: 1, height: 720 }],
    qualityId: -1,
    playingHeight: 720,
    audio: [{ id: 0, lang: 'en' }],
    audioId: 0,
    text: [{ id: 0, lang: 'tr' }, { id: 1, lang: 'en' }],
    textId: -1,
  };

  it('shows each setting with its current value and switches it from a sub-list', () => {
    const onSelect = vi.fn();
    render(<SettingsMenu tracks={tracks} speed={1} speeds={[1, 2]} onSelect={onSelect} onSpeed={() => {}} onHelp={() => {}} onClose={() => {}} />);
    expect(screen.getByRole('menuitem', { name: /Kalite.*Otomatik \(720p\)/ })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: /^Ses/ })).toBeNull(); // one audio track: nothing to choose
    fireEvent.click(screen.getByRole('menuitem', { name: /Altyazı.*Kapalı/ }));
    expect(screen.getByRole('menuitemradio', { name: 'Kapalı' })).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'Türkçe' }));
    expect(onSelect).toHaveBeenCalledWith('text', 0);
  });

  it('Esc in a sub-list goes back; on the main list it closes', () => {
    const onClose = vi.fn();
    render(<SettingsMenu tracks={tracks} speed={1} speeds={[1, 2]} isLive onSelect={() => {}} onSpeed={() => {}} onHelp={() => {}} onClose={onClose} />);
    expect(screen.queryByRole('menuitem', { name: /Oynatma hızı/ })).toBeNull(); // live: no speed
    fireEvent.click(screen.getByRole('menuitem', { name: /Kalite/ }));
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('the help lists the shortcuts it is given', () => {
    render(<ShortcutHelp shortcuts={[{ keys: ['Boşluk', 'K'], label: 'Oynat / duraklat' }]} onClose={() => {}} />);
    expect(screen.getByRole('dialog', { name: 'Klavye kısayolları' })).toHaveTextContent('BoşlukKOynat / duraklat');
  });
});
