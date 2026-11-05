# Reference machines and device tiers

The overhead harness (P0-27, `sdk-web/overhead`) is run on the machines listed here, so reports can be compared over time and a partner can be told exactly what was measured.

## Device tiers

**These definitions are placeholders.** I did not have NFR-C.2 or ML section 10.2 text to take the tiers from. Confirm or replace them before any report is shown outside the company.

| Tier | Stands for | How it is measured today |
| :-- | :-- | :-- |
| T1 high | A recent desktop or laptop | Run natively on a machine of that class. |
| T2 mid | A mainstream laptop or recent mid-range phone | Run natively if such a machine is listed; the harness's 2x slowdown is only an approximation. |
| T3 budget | A budget phone or an old laptop | **Not measured yet.** Needs a real device. The 4x slowdown is only an approximation and does not slow the worker. |

## Machines

| ID | Tier | What it is | Status |
| :-- | :-- | :-- | :-- |
| RM-1 | T1 high (dev desktop) | The founder's development computer (Windows). The report records its processor, memory, operating system and browser. | First report to be run (P0-27) |
| RM-2 | T2 mid | A mainstream laptop. | To be chosen |
| RM-3 | T3 budget | A budget Android phone or an old laptop. | To be chosen, needs the native SDK (P1-08) or a way to run the harness on it |

## Rules

- One report per machine and per run is kept in `docs/reports/overhead/`. Reports are never edited afterwards.
- A machine's setup stays the same between reports (browser channel, power plugged in, other programs closed), or the change is written in the report.
- The pass budget is NOT defined here. It is agreed with the first partner (P0-71) and added to the pilot success criteria.
