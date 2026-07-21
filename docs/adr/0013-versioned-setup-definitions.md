---
status: accepted
---

# Keep historical Setup definitions versioned and immutable

Changing a Setup's judgment protocol creates a new version instead of silently reinterpreting historical samples. Past samples remain bound to the version used when they were judged and move only through explicit relabeling; display-name corrections may update without a new version because they do not change research meaning. This adds version-management work but preserves reproducibility and allows different definitions to be compared honestly.
