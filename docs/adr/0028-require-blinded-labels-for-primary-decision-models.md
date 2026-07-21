---
status: accepted
---

# Require blinded annotations for primary decision models

Candidate review hides all bars, outcomes, realized performance, and future trade markers after the decision cutoff until the user saves a judgment. It also hides candidate source, whether a real action occurred, structural-similarity and behavior-model scores, and the queue-selection reason. Revealing source, scores, and future data is explicit and happens only after the judgment. Any annotation created or changed after reveal is versioned as a post-outcome relabel: it remains available for retrospective review but cannot enter the primary behavior model or formal matched inference. Original acted-event timestamps remain immutable facts and later judgments do not overwrite them. This reduces the amount of model-eligible retrospective labeling, but prevents hindsight or model suggestions from being presented as decision-time behavior.
