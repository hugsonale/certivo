# Web SDK architecture (P0-21)

Why these choices: `docs/adr/0021-web-sdk-architecture.md`. How to run it: `sdk-web/README.md`.

## How the packages fit

```
        partner's page
              |
        [ sdk ]  wires everything, one entry point (certivo-sdk.js)
        /  |  \  \
 [capture] [inference] [core] [ui]       each imports only [types]
   frames     scores     keys, packets,   indicator
   (memory    (worker,   buffer, network
    only)     numbers    (the ONLY place
              out)       that uses fetch)
```

A frame flows `capture -> inference` and stops there. Only a `ScoreResult` goes on to `core`.

```
frame = capture.grab()
  try:     result = inference.score(frame.image)     // image moved into the worker
  finally: frame.close()                              // always, before anything else
packet  = core.buildPacket(result)                    // refuses: no reason code, bad confidence, bad role
bytes   = codec.encodeForSigning(packet)              // supplied by P0-22
body    = codec.toWire(packet, signer.sign(bytes))
core.send(body)  or  buffer it if the platform is unreachable
```

## Rules the tests enforce (`sdk-web/test/architecture.test.ts`)

| Rule | Protects |
| :---- | :---- |
| `core`, `capture`, `inference`, `ui` import only `types`; only `sdk` imports the others | A picture cannot reach the network code by accident |
| `capture`, `inference`, `ui`, `types`: no network, no storage, nothing that turns a picture into bytes | Frames are never sent, kept or re-encoded |
| `fetch` appears only in `core/src/session-client.ts` | One place to review for everything that leaves the page |
| `core`, `ui`, `types`, `sdk` never name a picture type | Pictures stay inside capture and inference |
| `ScoreResult` has exactly `confidence`, `reasonCodes`, `modelVersion` | Only numbers and code words leave the model |

These are static checks. The runtime proof that no media leaves the page is P0-24.

## PROVISIONAL (settled by later steps)

| Item | Settled by |
| :---- | :---- |
| Packet field names, the range of `confidence`, the exact signed bytes | P0-22 (Spec 0 and its test vector) |
| Whether "self" packets omit the `role` field (so existing bytes do not change) | P0-22, with a Spec 0 amendment |
| Reason-code catalogue and the indicator wording | P0-38, P0-50 |
| Bundle budgets (30 KB, 10 KB, 36 KB gzip) | P0-27 and the first design partner |
