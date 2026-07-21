---
status: accepted
---

# Bound decision research to fully closed K-lines

All decision-time features, similarity searches, and induced rules stop at a fully closed K-line. A current-bar-close decision uses the same bar for the Setup and decision; a next-bar-confirmation decision uses a later closed bar as its cutoff. When an imported order occurred inside a bar and no intrabar snapshots or trade data exist, the sample maps to the latest fully closed bar before execution and is marked as an intrabar timing approximation. This excludes some genuine intrabar behavior, but prevents look-ahead leakage and keeps research reproducible from the available data.
