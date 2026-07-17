---
status: accepted
---

# Make randomized research calculations reproducible by default

Bootstrap confidence intervals, permutation tests and other randomized research calculations will use a recorded random seed and record their simulation settings with the result. We choose repeatable default output over implicit fresh randomness because research conclusions must be reviewable later with the same data, parameters and application version.

## Consequences

Users may deliberately select a different seed when exploring sensitivity, but the changed seed becomes part of the result identity. Research manifests and user-facing reports must include the seed, iteration count and confidence settings when applicable.
