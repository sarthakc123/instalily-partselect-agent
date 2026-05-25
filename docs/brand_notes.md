# Brand notes — slide theme research

These choices drive [slides.md](slides.md) and the SVG architecture diagram
([assets/architecture.svg](assets/architecture.svg)). Documented so the deck
can be re-rendered consistently and the visual choices are reviewable.

## Source

Research target: **instalily.ai** marketing site (May 2026 snapshot).

## Visual identity

- **Color**: high-contrast black-on-white minimalism. Black (`#0a0a0a`) on
  white (`#ffffff`). No gradients. No additional accent colors in the core
  brand. The deck adds a single functional accent (`#ff5722`, a deep orange
  similar to PartSelect's brand chip) reserved exclusively for verdict
  callouts and key numbers, so it reads as data, not decoration.
- **Typography**: modern geometric sans-serif. We use **Inter** (open-source,
  bundled with Marp themes by default) as the closest free analog. Display
  weights 600-800 for headers, 400-500 for body. No serif anywhere.
- **Layout**: substantial negative space, clean grid, sectional dividers as
  thin (1px) horizontal rules in `#e5e5e5`. Numbered callouts (`01`, `02`,
  `03`) for sequence lists — adopted as the motif for ordered roadmap items
  and design-choice numbering.
- **Iconography**: minimal. The deck uses no decorative icons. Diagrams use
  outlined rectangles and lines, never filled shapes.
- **Tone of voice**: direct, short declarative sentences ("Don't slow down.",
  "Sell faster."). The deck adopts this style: each slide caption is a
  single short clause whenever possible.

## Tokens (used in [slides.md](slides.md))

```css
--brand:        #0a0a0a;   /* primary text + headers */
--brand-fg:     #ffffff;   /* on-brand text */
--bg:           #ffffff;   /* slide background */
--surface:      #fafafa;   /* code blocks, callout cards */
--rule:         #e5e5e5;   /* hairline dividers */
--muted:        #6b6b6b;   /* secondary text */
--accent:       #ff5722;   /* functional only: verdict, metric, eval PASS */
--accent-dim:   #ffe0d3;   /* light accent fill for callout backgrounds */
```

## Attribution and disclaimer

- This is a **case-study submission**, not Instalily collateral. The deck
  footer carries "Instalily Case Study — Sarthak Chandarana" so it cannot
  be mistaken for first-party material.
- The Instalily logo is **not** placed on the deck (that would imply
  authorship attribution). The title page uses a textual wordmark only.

## Reference: PartSelect color note

The agent's frontend UI uses PartSelect blue (`#1c4587`) and orange
(`#ff7a00`) per the case study. The slide deck deliberately does **not**
match the PartSelect theme — the deck is *for Instalily*, not the
end-product UI. Frontend brand colors stay in the frontend.

## Rendering the deck

```bash
cd docs
npx --yes @marp-team/marp-cli@latest slides.md -o slides.pdf --allow-local-files
```

The `--allow-local-files` flag is required to embed
[assets/architecture.svg](assets/architecture.svg). Marp downloads on first
run (~50MB Chromium); subsequent runs are fast.
