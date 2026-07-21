---
status: accepted
---

# Validate v1.6 entry behavior by market episode and time

The v1.6 entry-behavior model never uses random train/test splits. Samples remain grouped by independent market episode, earlier data supplies at least three expanding-window validation folds, and the latest contiguous 20% of episodes stays untouched as a one-time final test. Reaching 30 ENTRY and 30 REJECT labels permits only an exploratory model; final validation additionally requires the test segment to contain at least 10 labels and five independent episodes from each class. Inspecting the final test and then changing features, parameters, or thresholds consumes that test and requires a later holdout. This applies the temporal-contamination principles of ADR-0004 specifically to the v1.6 behavior model while keeping ADR-0004's broader rule-search work separate.
