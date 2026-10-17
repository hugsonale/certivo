# Certivo

Trust infrastructure for live human interaction: an embeddable SDK that gives every
participant on a live call a continuously updated, signed trust signal about the others.

## Layout

- `platform/`   FastAPI backend (sessions, score events, attestation, trusted devices)
- `sdk-web/`    Web SDK (on-device inference, signed score packets)
- `demo-call/`  Two-person WebRTC demo app used to test and measure the SDK
- `docs/spec/`  The 18-document specification suite
- `legacy/`     Frozen reference code from the original prototype (tag `legacy-liveness-v0`).
                Port from here deliberately; delete when nothing is left worth porting.
