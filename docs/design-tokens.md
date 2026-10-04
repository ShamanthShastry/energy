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
| `--yellow-200` | #FFFFC5 | Secondary: the selected day on the bill chart (v0.12) |
| `--yellow-100` | #FFFFE6 | Secondary tint: the open day box |
| `--yellow-700` | #8A6D0B | Text and outline on yellow |

## Mapping to TRS surfaces

- Spike panel (TRS-15-03, TRS-16-01) and CMP-12 alerts with severity `act` (TRS-12-06): `--warn`.
- CMP-12 severity `watch`: `--muted` text on a `--green-100` chip. Not amber.
- Failed actuation (CMP-19 error handling) and ingest gap/rejection surfaces (CMP-07 ingest log): `--crit`.
- "measured" / "estimated" / "simulated feed" / "synthetic HVAC" labels (TRS-SYS-02, TRS-16-07, TRS-09-09): `--muted`.
- Forecast range p50–p90 (TRS-16-05): band in `--green-100`, line in `--green-500`.
- Headline dollar figures: `--green-700`.

## Look (v0.12.1, after the Tesla energy app, light mode)

- Type: Figtree (Google Fonts), fallback system sans. Values large and light (`.hero` 56 px / 400, `.stat-value` 34 px / 500) set above a tiny uppercase caption (`.caption`: 11 px, 600, letter-spacing .09em, `--muted`). Section titles 15 px / 650.
- Sections, not cards: no boxes; each panel starts with a 1 px `--line` rule and generous padding. The page ground is `--bg`; `--surface` is kept for modals and inputs.
- Status captions (`.chip`): a 7 px dot plus uppercase text, coloured only by meaning (`--green-700` ok, `--warn` heads-up, `--crit` failure, `--muted` with a hollow dot for simulated).
- Bars: 6 px rounded tracks in `--line`, fills in `--green-500`; chart bars rounded, gridlines dotted, axis text as captions.
- Buttons: 6 px radius; primary `--green-700` on white, quiet outlined in `--line`. Inputs are underline-only.
- Tabs and the header: brand as small caps; the home's name as the page title with a live-status line (dot in `--green-500`).
- Mark: a vertical bolt (`components/Logo.tsx`), white on `--fg` in the header and sign-in; page-high in `--green-500` for the intro, where it grows from the bottom in a flash before the title fades in and sign-in appears (`components/Splash.tsx`).
