---
status: accepted
---

# Use matched ENTRY-versus-REJECT comparisons for entry event study

The primary entry-event comparison matches ENTRY judgments to REJECT judgments from the same Setup version, direction, symbol, and decision timeframe using decision-time structural features only. Outcome returns, MFE, and MAE are joined after matching, and inference aggregates by independent market episode. Unmatched distributions remain visible as descriptive context, but raw mean differences are not the main behavioral conclusion. This specializes the matched-baseline principle from ADR-0003 for the v1.6 human-decision labels and accepts fewer usable pairs in exchange for less regime and instrument confounding.
