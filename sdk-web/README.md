# Certivo Web SDK (P0-21 skeleton)

The code a partner puts on their web page so that each person's device can score a video call and sign the result.
This is the **skeleton**: the structure, the rules that protect people, and the parts whose design is already decided.
There is no model yet (P0-37) and the packet byte format is not final (P0-22).

## What is in it

| Package | Job | May use |
| :---- | :---- | :---- |
| `types` | A few shared words (signing algorithm, packet role, score result). No code runs from it. | nothing |
| `core` | Device key and signing, packet building, the offline buffer, talking to the platform. The only place that touches the network. | `types` |
| `capture` | Reads video frames. Frames exist in memory only and are closed straight away. | `types` |
| `inference` | Scores a frame inside a worker. Only numbers and code words come out. | `types` |
| `ui` | The in-call trust indicator (reference version). | `types` |
| `sdk` | The one entry point. Wires capture, inference and core together. | all of them |

`npm test` includes **architecture guards** that read the source and fail if a rule is broken (for example, if the capture
code starts using the network). See `docs/adr/0021-web-sdk-architecture.md` for why.

## How to run it on your computer

You need **Node 24 or newer** (it includes npm 11). Older npm (10) crashes on the test runner we pinned.

1. Check what you have, in Git Bash:
   ```
   node --version
   npm --version
   ```
   You want `v24.x` or higher, and npm `11.x` or higher.
2. If Node is missing or old: install the **LTS** version from https://nodejs.org (accept the defaults), then close and reopen Git Bash and check again.
3. If Node is 22 or newer but npm shows 10.x, this fixes just npm: `npm install -g npm@11`
4. Then, from this folder:
   ```
   npm ci
   npm run check
   ```
   `npm ci` installs exactly the versions in `package-lock.json`. `npm run check` runs everything below, in order.

| Command | What it does |
| :---- | :---- |
| `npm run lint` | Style and common mistakes (Biome) |
| `npm run typecheck` | TypeScript checks for the code and the tests |
| `npm test` | All tests, including the architecture guards |
| `npm run build` | Makes `dist/certivo-sdk.js` and `dist/certivo-inference-worker.js` |
| `npm run size` | Fails if a built file is bigger than its budget in `size-budget.json` |

## Rules for changing dependencies

Versions are exact (no `^`), pinned to releases at least 14 days old (guide P0-61), and `npm audit` must stay clean at "high".
`vitest` is pinned to 5.0.4: the older 4.x releases have known security advisories, and 4.1.x and 5.x crash npm 10. Re-check when npm 10 is no longer a concern.
