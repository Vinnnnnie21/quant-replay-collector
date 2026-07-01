"""Reusable Qt widget effects.

Qt style sheets cannot render ``box-shadow``. A native drop shadow attached to
each button proved unsafe in this Qt build:

1. Over a window-level QSS fill it strips the button background (black buttons),
   and
2. a widget that still owns a graphics effect can abort (native crash) when it is
   torn down via ``deleteLater`` / ``DeferredDelete`` - which happens whenever the
   analysis window is closed or the test suite isolates Qt between tests.

Because the effect crashes on teardown, these helpers are intentional NO-OPS. The
dark "pill" buttons already separate from the near-black chrome on their own. A
real drop shadow would require wrapping each button in a container widget and
applying the effect to the wrapper, so no button ever owns an effect. That is a
structural change and is deliberately not done here.
"""

from __future__ import annotations


SHADOW_BUTTON_ROLES = (
    "primaryButton",
    "secondaryButton",
    "successButton",
    "dangerButton",
    "intervalChip",
    "compactButton",
    "dangerGhostButton",
    "tagChip",
    "timeframeChip",
)


def apply_button_shadow(button, **_kwargs) -> None:
    """Intentional no-op (a graphics effect crashes on widget teardown)."""
    return None


def apply_role_button_shadows(root) -> int:
    """Intentional no-op. Returns 0 (no shadows attached)."""
    return 0


__all__ = ["apply_button_shadow", "apply_role_button_shadows", "SHADOW_BUTTON_ROLES"]
