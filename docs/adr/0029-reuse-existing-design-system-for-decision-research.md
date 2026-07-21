---
status: accepted
---

# Reuse the existing design system for decision research

The v1.6 decision-research workspace reuses the application's existing theme tokens, typography, spacing, semantic colors, chart styling, and shared interaction components. Entry and exit research share the same layout grid and component family; they differ only where their decision semantics and data require it. Page-specific hard-coded colors, font sizes, radii, and spacing are not allowed.

High structural similarity and high behavior-model scores use informational rather than profit colors because they are research measurements, not trading signals. Warning colors indicate missing data or insufficient evidence, while red and green remain reserved for direction, market movement, or explicitly defined adverse and favorable results. Every status also has a textual or iconographic cue.

This decision preserves the compact desktop trading-terminal density and requires all supported application themes to render the workspace correctly. It adds upfront shared-component work, but prevents the research workspace from becoming a separate visual product whose colors imply unsupported trading conclusions.
