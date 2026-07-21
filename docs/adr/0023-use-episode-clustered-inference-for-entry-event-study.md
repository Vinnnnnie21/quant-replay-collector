---
status: accepted
---

# Use episode-clustered robust inference for entry event study

Matched ENTRY-versus-REJECT outcome differences are reduced within each independent market episode before inference. The primary effect is the median episode-level paired difference with a 5,000-resample cluster-bootstrap 95% interval and paired rank-biserial correlation; mean difference is secondary. A 10,000-draw episode-level sign-flip test records its seed. The 15 primary outcomes formed by five fixed horizons and direction-adjusted close return, MFE, and MAE receive Benjamini-Hochberg correction within each Setup version and direction. Evidence is marked only when `q < 0.05` and the interval excludes zero. This brings multiple-testing control into the v1.6 entry-event scope without claiming strategy profitability.
