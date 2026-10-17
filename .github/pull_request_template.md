## What and why

<!-- One or two plain sentences. -->

**Build step ID(s):** <!-- e.g. P0-03. Use "none" only for tiny fixes. -->

## What changed

-

## How it was tested

- [ ] Automated tests added or updated, and they pass
- [ ] Checked by hand (describe how):

## Constitution checklist (Master Build Guide, Part 3)

- [ ] Does this collect, store or transmit anything new about a person? If yes, it is in the data inventory.
- [ ] No raw video or audio can leave the device through this change.
- [ ] Every decision or score it produces carries a confidence value and an explanation.
- [ ] It adds or changes no claim about accuracy, speed or privacy. Or the evidence is linked below and the claims register is updated.
- [ ] It does not change authentication, cryptography or the consent flow. Or a written security note is attached below.
- [ ] Tests, documentation and the tracker are updated.

## Definition of done

- [ ] The relevant spec or document is updated in this same pull request
- [ ] No secrets, personal data or raw media are in the diff
- [ ] The tracker row for the step ID is updated, with this PR as evidence

## Security note, evidence links, rollback plan

<!-- Required if you changed auth, crypto or consent, touched a claim, or this affects a deployed system.
     For deployed changes: say how to undo it. -->
