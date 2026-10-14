# ADR-0001 — Player: one track model for every engine; time-based post-play

- Status: Accepted (2026-10)
- Area: frontend / `features/player`

## Context

The player runs on three engines chosen per source: hls.js (HLS over MediaSource), Shaka (EME DRM)
and the browser itself (Safari/iOS HLS, MP4). Viewers expect what every streaming service offers:
quality, audio-language and subtitle choice, remembered between episodes, and a "next episode"
flow at the end of an episode. Each engine exposes renditions differently — hls.js by array
index, Shaka as video × audio *variants*, the browser as `TextTrack`/`AudioTrack` lists — and
the catalogue has no credits timestamps yet.

## Decision

1. **One track model** (`engines/tracks.js`): every engine implements `tracks()` → `{ quality,
   qualityId, playingHeight, audio, audioId, text, textId }` and `select(kind, id)`, and calls
   `onTracks()` when that may have changed. The UI (settings menu, CC button, shortcuts) only
   knows this model. An engine that cannot switch something returns no options for it (native
   HLS: no quality list) and the menu hides that row.
2. **Quality is shown the way people think about it**: one entry per height (highest bitrate wins),
   never above the plan's ceiling (`maxHeight`), plus "Otomatik (720p)" showing what ABR picked.
   hls.js switches with `nextLevel` (at the next fragment — no buffer flush, no stall).
3. **Remembered choices** (`prefs.js`, browser storage, failure-tolerant): subtitle language
   (or "off" on purpose), audio language, volume. Applied *once per source*, the first time it
   lists tracks of that kind, so the viewer's later choice is never fought.
4. **Post-play is time-based** (`hooks/useEndgame.js`): the next-episode card appears in the last
   20 s (or from `item.creditsAt` when the catalogue knows the credits start); the centred
   10-second countdown appears when the episode ends. Clips under 45 s get neither.
5. **One shortcut list** (`shortcuts.js`) drives both the key handler and the "?" help, so the help
   cannot drift from behaviour; screens add their own keys (live TV: ↑/↓ channels, digits for
   channel numbers) and win on conflicts.

## Consequences

- Adding an engine means implementing four functions; no UI change.
- Shaka's audio/quality interplay is resolved inside the engine (quality options are listed for
  the active audio only, so picking 720p never silently changes the language).
- Without credits data the card can appear during the last scene of an episode whose credits are
  shorter than 20 s, or late for long credits. A nullable `credits_start_s` on episodes (admin-set
  or detected) removes this with no player change.
- Subtitles are rendered by the browser (`::cue` styling); cues without their own position are
  moved three lines up so they clear the control bar. A fully custom subtitle renderer is not
  needed until styled formats (TTML/IMSC with regions) are in scope.
