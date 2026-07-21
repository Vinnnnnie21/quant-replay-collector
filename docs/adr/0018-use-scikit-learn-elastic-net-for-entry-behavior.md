---
status: accepted
---

# Use scikit-learn elastic-net logistic regression for entry behavior

v1.6 models explicit ENTRY versus REJECT judgments with elastic-net regularized logistic regression. Coefficients remain traceable to a capped set of named behavior features, while combined L1 and L2 penalties support selection among correlated indicators. The application adds scikit-learn and its locked runtime dependencies instead of implementing an optimizer locally; the larger desktop bundle is accepted in exchange for tested numerical behavior. Random forests, boosted trees, neural networks, and other opaque alternatives are outside the v1.6 behavior-model path.
