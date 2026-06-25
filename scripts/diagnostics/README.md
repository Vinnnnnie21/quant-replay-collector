# Diagnostics scripts

One-off, throwaway diagnostic scripts kept for future theme/UI debugging. They are
**not** part of the application and are not imported by it.

Each script resolves the repo root from its own location, so it can be run from
anywhere:

```powershell
cd D:\Trading
.\.venv\Scripts\python.exe scripts\diagnostics\theme_button_probe.py
```

| Script | Purpose |
| --- | --- |
| `theme_button_probe.py` | Build the real main window, apply the OKX/black preset, dump each role button's role / local stylesheet / graphics effect / rendered centre pixel. |
| `theme_button_probe2.py` | Minimal standalone QSS experiment: which stylesheet writing actually paints a button fill. |
| `theme_button_probe3.py` | In the real window tree, compare button fill from window-level QSS vs a local stylesheet (proves the local-stylesheet fix). |
| `theme_button_probe4.py` | Verify a drop shadow over a local stylesheet preserves the button background. |

These were used to diagnose the "buttons render with no fill on Fusion" issue;
the fix lives in `ui_style.role_button_local_qss` + `views.main_window_presentation.apply_role_button_styles`.
