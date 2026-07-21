---
status: accepted
---

# Consolidate event study into one decision-research workspace

v1.6 exposes a single authoritative `数据分析 → 决策研究` workspace with `开仓研究` and `平仓研究` tabs. Existing event-study entry points either disappear or navigate to this workspace and retain no independent state. New calculations use one canonical decision-research service; legacy event records remain readable but duplicate legacy implementations do not produce new results. This removes convenient duplicate shortcuts, but prevents divergent labels, formulas, and reports from presenting themselves as the same research feature.
