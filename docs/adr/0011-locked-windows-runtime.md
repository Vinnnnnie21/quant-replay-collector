---
status: accepted
---

# Support a locked Windows Python runtime first

The stability hardening phase supports Windows 64-bit computers running Python 3.13 with a locked dependency set. We choose one verified local runtime before cross-platform support so a reinstall or a second Windows machine reproduces the tested application environment instead of resolving newer, untested library versions.

## Consequences

Runtime and dependency upgrades become deliberate maintenance work with their own validation run. macOS, Linux, cloud deployment and unplanned runtime upgrades are outside the current support commitment.
