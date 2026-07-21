---
status: accepted
---

# Bind each Setup version to a three-timeframe profile

Each Setup version uses exactly one decision timeframe and two higher context timeframes. The decision timeframe locates observations and decisions; the higher timeframes contribute only fully closed context available at the decision cutoff. The application recommends an exchange-supported, strictly increasing pair of context timeframes, but the user may change them before saving the version. During similarity retrieval, higher-timeframe context is a soft contribution and cannot exclude a candidate; only later behavior induction and out-of-sample validation may promote such context to a hard rule. Samples and structural-similarity scores from different profiles are not pooled, and changing any timeframe after saving creates a new Setup version. This fragments samples more than a timeframe-agnostic pattern, but avoids treating structures with materially different time horizons as equivalent.
