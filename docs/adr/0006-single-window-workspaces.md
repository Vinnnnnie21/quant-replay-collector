---
status: accepted
---

# Use a single-window workspace shell

Quant Replay Collector will present 行情回放 and 数据分析 as workspaces inside one main window instead of opening analysis as a separate dialog. This preserves one research session and its replay state across navigation, gives the application a consistent top-level information architecture, and accepts the added shell/navigation complexity in exchange for a less fragmented research workflow.

## Consequences

Switching workspaces must not pause or reset replay. Entering 数据分析 refreshes the current session once, returning to 行情回放 restores its prior layout state, and existing analysis calculations remain behind their current interfaces rather than moving into the navigation layer.
