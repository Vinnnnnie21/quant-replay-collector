---
status: accepted
---

# Version entry-behavior models as immutable snapshots

Entry-behavior training runs only after an explicit user action and always creates a new immutable model version. Each version records its Setup version, reference annotations and market episodes, feature and formula versions, data ranges, normalization parameters, regularization settings, coefficients, research threshold, application version, and random seed. New or corrected labels mark an existing model as having newer evidence but never retrain or overwrite it automatically. This requires retaining more local artifacts, but keeps candidate scores and reports reproducible and makes behavior changes attributable to a specific training run.
