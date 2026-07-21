---
status: accepted
---

# Use matched EXIT_NOW-versus-HOLD comparisons for exit event study

Exit-event research uses one-to-one, non-reused matches within the same Setup version, direction, symbol, and decision timeframe, based on decision-time market structure and position state. It inherits the 75-point primary caliper, 70/80 sensitivity checks, evidence-stage sample gates, episode-clustered bootstrap and sign-flip inference, and 15-outcome FDR correction from entry-event research. Effects are oriented as `HOLD continuation minus EXIT_NOW continuation`, so positive values consistently support discriminating favorable holds from timely exits. This preserves a common evidence standard while keeping exit semantics separate from entry outcomes.
