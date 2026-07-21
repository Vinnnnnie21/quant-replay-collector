---
status: accepted
---

# Keep v1.6 on the Python desktop stack

QRC v1.6 remains a single Windows desktop application implemented with Python 3.13, PySide6, SQLite, NumPy, pandas, and scikit-learn. Research formulas and domain services are kept independent of Qt widgets, long-running operations use the established cancellable background-task lifecycle, dependencies are locked, and database migrations remain append-only and backward compatible.

The release does not introduce a separately deployed backend or rewrite the application in Rust. Language replacement would not address the principal stability risks—duplicated research implementations, UI/calculation coupling, task lifecycle, migration discipline, dependency control, and regression coverage—and would add a second build and debugging boundary before the product behavior is validated.

Rust may be reconsidered only for an isolated, pure calculation kernel that materially misses an explicit performance budget after profiling and reasonable Python-side vectorization, indexing, and caching. Such a component must preserve the existing domain model, persistence semantics, and UI architecture. This keeps the option open for measured optimization without turning architectural anxiety into a speculative rewrite.
