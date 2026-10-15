# NS-V2 — Codex reviews, verbatim

## Review 1 — REQUEST-CHANGES (session `01a1418f-045e-7092-97fa-cc6d5e96bfdc`)

**REQUEST-CHANGES**

- **P2 — Early microphone survives unmount.** [RealtimeVoice.tsx:213](/Users/michaelrickards/dev/bh2-NS-V1-review/frontend/client/src/components/RealtimeVoice.tsx:213). Tap Talk, then navigate away while `getAccessToken()` is pending. Unmount cleanup never releases `micPromiseRef`; the microphone remains active. Token resolution also continues into socket creation after unmount. Reproduced with mocked promises. Release pending media on unmount and cancel the pending startup.

- **P2 — Audio setup exceptions bypass cleanup.** [RealtimeVoice.tsx:218](/Users/michaelrickards/dev/bh2-NS-V1-review/frontend/client/src/components/RealtimeVoice.tsx:218). If `new AudioContext(...)` throws after microphone acquisition starts, execution never reaches the `try`. The microphone remains active, progress timers continue, and `connecting` stays true, preventing retry. Reproduced with a throwing constructor. Put setup inside the guarded block and release resources on failure.

Within scope, no backend guarantee regression or shared-session poisoning defect found: gate → admission → committed heartbeat precedes OpenAI; refusals retain 4003 and their reasons. No ordinary repeat-tap double socket or new dependency-related stale closure found.

Verification: `./check.sh full` passed (**1,821 passed, 33 skipped**); voice suites **56 passed**. Browser findings used mocked control-flow checks, not a live browser. Working tree clean; no edits, commits or pushes.

## Review 2 — REQUEST-CHANGES (session `01a14192-0e7d-7a83-8793-30a6d6aa0f09`)

**REQUEST-CHANGES**

- **P2 — microphone can still survive unmount:** [RealtimeVoice.tsx:296](/Users/michaelrickards/dev/bh2-NS-V1-review/frontend/client/src/components/RealtimeVoice.tsx:296). If `ready` arrives while microphone permission is pending, then unmount occurs, `startAudioCapture()` resumes afterward and adopts the stream. `releaseEarlyMic()` skips stopping that adopted stream. The mocked control-flow check reproduced **zero track stops and a new live AudioContext after unmount**. Check cancellation after the await, stopping the stream before adopting it.

The startup audio-constructor exception fix passes: microphone released, timers cleared, connecting reset. Unmount before token resolution also passes.

No files changed. Browser testing and `check.sh` were not run.

## Review 3 — ACCEPT (session `01a14194-442a-7b30-9356-7ca0b33c740b`)

**ACCEPT** — `2fdbf2b3c4d8346cce376e85206fa09968f62553`.

- Mocked control-flow check reproduces the leak on the parent and confirms it is fixed here.
- Unmount during audio resume, normal capture/cleanup, and permission denial pass.
- `./check.sh full` green: 1,821 tests passed, 33 skipped; all five deploy traps passed.
- No findings or regressions detected. No edits, commits, or pushes.

Real-browser microphone behaviour remains unverified: start voice, navigate away while permission is pending, then allow it; the microphone should switch off.
