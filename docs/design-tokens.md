# Design tokens (CMP-16)

Canonical file: `dashboard/src/styles/tokens.css`. Nothing in the dashboard uses a hex literal.

| Token | Hex | Use |
|---|---|---|
| `--bg` | #F7F8F5 | Page ground (off-white with a hint of green, not cream) |
| `--surface` | #FFFFFF | Cards |
| `--line` | #E1E6DF | Borders, grid lines |
| `--fg` | #17201B | Primary text |
| `--muted` | #5C6B62 | Secondary text, labels |
| `--green-700` | #1F6B45 | Primary buttons, links, headline numbers |
| `--green-500` | #2E9E63 | Accent, active states, chart line |
| `--green-100` | #DDF2E6 | Tints, selected tile, chip backgrounds |
| `--warn` | #B8772A | Spike alerts, "act" severity (amber, not red) |
| `--crit` | #A33D2E | Only for failed actuations and data errors |

## Mapping to TRS surfaces

- Spike panel (TRS-15-03, TRS-16-01) and CMP-12 alerts with severity `act` (TRS-12-06): `--warn`.
- CMP-12 severity `watch`: `--muted` text on a `--green-100` chip. Not amber.
- Failed actuation (CMP-19 error handling) and ingest gap/rejection surfaces (CMP-07 ingest log): `--crit`.
- "measured" / "estimated" / "simulated feed" / "synthetic HVAC" labels (TRS-SYS-02, TRS-16-07, TRS-09-09): `--muted`.
- Forecast range p50–p90 (TRS-16-05): band in `--green-100`, line in `--green-500`.
- Headline dollar figures: `--green-700`.
