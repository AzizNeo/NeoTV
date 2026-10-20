# ADR-0012 — Catch-up TV: recording is opt-in per channel, the plan sets the window, storage behind a port

- Status: Accepted (2026-10)
- Area: modules `live` (channel archive settings, recorder, archive playlists), `billing`
  (entitlement `catchup_days`), `playback` (the same gate), `xtream` (timeshift)

## Context

Viewers want to watch a programme that has already aired, or restart one in progress. Today
nothing is kept: external live channels pass through the media proxy, and NeoTV's own (ingest)
channels are transcoded only while someone watches, with a 12-second rolling window in tmpfs.
Catch-up therefore needs a recording pipeline, a retention policy, a rule for who may watch how
far back, and a storage that can grow beyond one disk.

Recording a stream copies it: whether that is allowed is a question of rights, not of code.

## Decision

1. **Opt-in per channel, off by default.** A live channel has `archive_days` (0 = off, at most
   `ARCHIVE_MAX_DAYS`, 7). Only the live module's channels can be archived — they are the curated
   channels with a programme guide; bulk-imported catalogue channels have no guide to catch up on.
   - NeoTV's own (ingest) channels: the administrator switches it on.
   - External channels: switching it on requires the administrator to confirm that the operator
     holds the rights to record that stream. Who confirmed it and when is stored with the channel.
     Changing an external channel's source URL turns its archive off and clears the confirmation —
     the rights were confirmed for the old stream.
2. **The plan sets the window.** Billing entitlement `catchup_days`: Free 0, Personal 3, Duo 3,
   Family 7. A viewer can go back `min(channel archive_days, plan catchup_days)`. The rule lives in
   the playback gate, so the web player, TV apps and the Xtream API apply the same limit; no client
   decides on its own.
3. **Storage behind a port.** Recordings are written through an archive storage interface; the
   first adapter is a local directory (`ARCHIVE_ROOT`, a volume). Segments are named by their UTC
   start time, so any window can be listed from names alone — no database row per segment. An
   S3-compatible adapter can replace the local one without touching the recorder or playback.
4. **Retention by a job, never in the playback path.** A periodic task deletes what is older than
   each channel's window (all of it for a channel switched off). At 80 % disk use an alert fires;
   at 90 % no new recording starts, existing archives are kept and keep playing.
5. **Same delivery and rules as live.** An archive window is played through a normal playback
   session (entitlements, kids rating, stream limit) and served by nginx from the archive volume
   after the API has checked the grant (`X-Accel-Redirect`, as live HLS today).

## Delivery

| Step | Scope |
| --- | --- |
| C1 | This ADR; `archive_days` + rights confirmation on live channels (admin API); entitlement `catchup_days` |
| C2 | Recorder: continuous recording of archived channels; segment layout; retention task; disk guard; metrics, alerts, runbook |
| C3 | Archive playlists for a time window; playback content type; signed delivery through nginx |
| C4 | Web: past programmes in the guide play; start over; the admin switch; plans show the window |
| C5 | Xtream: `tv_archive`, `tv_archive_duration`, `has_archive`, `/timeshift/…` |
| C6 | End-to-end and load tests, README |

## Consequences

- Recording costs disk continuously for every archived channel (roughly bitrate × window); the
  default is off and the window is capped, so the cost is always an explicit operator choice.
- The recorder runs whether or not anyone watches — a new long-running worker role in the
  deployment, with its own health check and metrics.
- A missed recording (source down) is a gap in the archive, shown as such; nothing is invented.
- Not in scope: personal recordings (cloud DVR per viewer), ad replacement in archives.
