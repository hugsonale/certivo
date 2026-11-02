# P0-20 browser capability spike

A single test page. It checks, in the browser you open it with, the things the Certivo Web SDK depends on:

1. **Signing:** Ed25519 in WebCrypto (and ECDSA P-256 as the fallback), with a private key that cannot be exported, that still works after being stored and reloaded, and that matches the official RFC 8032 test vectors. This settles decision **D-01**.
2. **Frame access:** reading video frames (from a local video and from the received side of a call) as pixels, as raw frames, inside a worker, and as encoded frames (Insertable Streams). This feeds step P0-21 and decision **D-02**.
3. **Platform facts** the on-device model will need (WebAssembly SIMD, threads, WebGPU).

It has no network access (its own security policy blocks it), stores nothing except throw-away test keys that it deletes, and never saves or sends a video frame.

## Run it

```
cd ~/desktop/exclusive/certivo/sdk-web/spikes/p0-20-browser-capability
python -m http.server 8080
```

Leave that window open. In the browser, open **http://localhost:8080** (it must say `localhost`, not an IP address: browsers only allow WebCrypto on localhost or https). Click **Run all tests**, keep the tab in front for about 30 seconds, then click **Download results**. Stop the server with Ctrl+C.

Save each downloaded file into `docs/spec/browser-results/`. One file per browser.

## What counts as evidence

The guide asks for tests "on real machines". Every browser you test on a real computer counts. Results from automated or headless browsers do not count towards the P0-20 exit; they are only dry runs.

## Reading a result

| Label | Meaning |
| :---- | :---- |
| PASS | The feature is there and behaved correctly |
| FAIL | The feature is there but behaved wrongly. This is the important one: tell us |
| NOT SUPPORTED | The feature does not exist in this browser |
| COULD NOT RUN | The test itself could not run (for example the loopback call did not connect). It is not a verdict on the browser |
| SKIPPED | Not run because an earlier test it needs did not pass |
| INFO | A fact, not a pass or fail |
