# 0026. The demo call app and its stand-in scorer (P0-26)

**Date:** 3 November 2026
**Status:** Proposed

## Context

P0-26 asks for a two-person WebRTC call with a small signalling server and a mock partner backend that starts sessions and hands the SDK token to the client, with the reference indicator wired in and a way to feed a pre-recorded video in place of the camera, so that a swap can be triggered mid-call and the indicator watched.
There is no model yet (P0-37), so a swap cannot be detected. Showing an indicator that changes when the video is swapped is still needed, and the guide forbids implying an accuracy we have not measured (Part 3, "never claim unsubstantiated accuracy").

## Decision (proposed)

1. **A stand-in scorer, labelled as such.** `public/standin-worker.js` reports whatever the buttons say (about 880 normally; 560, 220, 210 after a swap; failure when "switched off"). It never looks at the picture. Every page carries a banner saying that no detection happens. The scorer is chosen in `public/config.js`: the real model replaces it by changing one line, and the banner turns off with `STAND_IN = false`.
2. **Everything else is real:** WebRTC between the windows, the real SDK bundle (`sdk-web/dist`), device registration, signed packets sent to the real platform, the platform's policy turning scores into outcomes, and the SDK's reference indicator.
3. **The swap is a virtual camera.** What is sent in the call, and what the SDK scores, is a canvas stream whose source can be switched (camera, built-in pattern, or a chosen video file). The stream itself never changes, which is how a real injection attack looks to an application.
4. **One small server, no dependencies** (`demo-call/server.mjs`, Node's own modules). It serves the pages and the SDK, relays call set-up over server-sent events, and is the mock partner backend: it keeps the API key (never sent to a browser, tested), starts ONE platform session per room for the two people, registers each window's public key, hands both the same SDK token, and polls the platform's status so every window can show everyone's indicator.
   It listens on 127.0.0.1 only. The pages carry a content-security policy that allows connections only to the demo server and the platform (tested in a real browser: a request to another site is blocked).
5. **Two origins for two people.** The windows are opened at `localhost` and `127.0.0.1`, so each gets its own device key and tab storage. The platform's dev CORS setting must list both.
6. **A score that stops is not a good score.** The platform's status holds the last outcome with no time on it. The demo server shows a person as "paused" when no new score has arrived for three intervals plus three seconds (at least ten). Before this, a window whose scoring had stalled kept showing "steady" to the other person.
7. **Indicators for everyone.** Both windows show both indicators. How a real partner shows one participant's status to another is decision D-17 and stays on hold: this demo does not settle it.
8. **A placeholder for consent.** A short notice and a checkbox gate the camera. It is not the consent flow (P0-51).
9. **Video only.** No sound is captured (D-08).

## Verification

- `npm test` in `demo-call` (26 tests, no dependencies): rooms, one session per call, the API key never reaching a browser, device registration, call-set-up relay, status to indicator mapping, stalled scores, end of call, safe file serving.
- Run by hand in two real Chromium windows against a stand-in platform built from the platform's schemas and policy thresholds: the call connects and video arrives in both, the swap moves the indicator steady, checking, needs a look in both windows, swapping back recovers, switching the model off pauses both and recovery is automatic, a reload carries the sequence numbers on, the end-of-call summary appears in both windows, and an outside request is blocked.

## Not verified, and known limits

- Not run against the real platform, with the real signer and key store, or with a real camera, on Firefox or Safari, on a phone, or between two computers (there is no relay server, so only the same computer or network works).
- A pre-recorded file as the swapped source is implemented and its failure path is tested, but the browser used for testing could not play any video file, so playing one was not exercised.
- The test machine had a single CPU core, where the second window sometimes starved for frames. On a normal computer this should not occur; if it does, "No new video frame arrived" appears in the log.
- **Found, not fixed (it belongs to the pipeline, not the demo):** when the frame source itself fails, `pipeline.runInterval()` throws and is not counted as a missed interval, so the SDK never tells the platform that verification is paused. The platform later discloses the hole as a missing-packets gap, but not as a pause. Proposed follow-up: count a failed grab as a missed interval, like a failed score.

## Related

P0-21 to P0-25 (ADRs 0021 to 0025), P0-37 (the real model), P0-38 (real indicator wording), P0-50 and P0-51 (design system and consent flow), decisions D-08 and D-17.
