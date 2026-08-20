"""Contrast of the dashboard palette, enforced rather than commented.

``src/web.py`` carries a note that its colours "were solved for, not
eyeballed; nudging them lighter will quietly drop below the line". A comment
cannot stop anyone, and adding a gradient did exactly that: brightening the
button fill 14% toward peach took it from 4.50:1 to 4.00:1, which is invisible
to the eye and a real failure for the 13px semibold text sitting on it.

So the rule is a test. It parses the palette out of the stylesheet, so it
checks the colours actually served rather than a copy that can drift.
"""

from __future__ import annotations

import re

import pytest

from src.web import PAGE

#: WCAG AA for normal text. The button labels are 13px semibold, which does
#: NOT reach the 18.66px bold / 24px threshold for the 3:1 large-text
#: allowance, so this is the bar for them too.
AA_NORMAL = 4.5


def _linear(channel: int) -> float:
    c = channel / 255
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.03928 else c / 12.92


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def mix(a: tuple[int, int, int], b: tuple[int, int, int], portion: float):
    """color-mix(in srgb, a <portion>%, b) — close enough in sRGB."""
    return tuple(round(a[i] * portion + b[i] * (1 - portion)) for i in range(3))


def palette(block: str) -> dict[str, tuple[int, int, int]]:
    """Pull `--name:#hex` pairs out of one CSS rule body."""
    return {
        name: hex_to_rgb(value)
        for name, value in re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,6})", block)
    }


def theme(selector: str) -> dict[str, tuple[int, int, int]]:
    """The palette declared under one selector in the served stylesheet."""
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\}", PAGE, re.S)
    assert match, f"no {selector} block in the stylesheet"
    found = palette(match.group(1))
    assert found, f"no hex colours under {selector}"
    return found


THEMES = {
    "dark": theme(':root[data-theme="dark"]'),
    "light": theme(':root[data-theme="light"]'),
}


@pytest.mark.parametrize("name", sorted(THEMES))
class TestPaletteContrast:
    def test_body_text_on_the_page(self, name: str) -> None:
        p = THEMES[name]
        assert contrast(p["ink"], p["bg"]) >= AA_NORMAL

    def test_secondary_text_on_panels(self, name: str) -> None:
        p = THEMES[name]
        assert contrast(p["ink-2"], p["panel"]) >= AA_NORMAL

    def test_dim_labels_on_panels(self, name: str) -> None:
        """The 11px labels get no size allowance either."""
        p = THEMES[name]
        assert contrast(p["ink-3"], p["panel"]) >= AA_NORMAL

    def test_button_text_on_the_accent(self, name: str) -> None:
        p = THEMES[name]
        assert contrast((255, 255, 255), p["accent"]) >= AA_NORMAL

    @pytest.mark.parametrize("token", ["up", "down", "warn"])
    def test_semantic_colours_on_panels(self, name: str, token: str) -> None:
        p = THEMES[name]
        assert contrast(p[token], p["panel"]) >= AA_NORMAL


@pytest.mark.parametrize("name", sorted(THEMES))
class TestAccentGradient:
    """The rule that a comment could not enforce.

    --grad-accent carries white text, so every stop along it has to clear the
    same bar the flat accent does. Since the accent is already *at* the bar,
    the only safe direction is darker.
    """

    def stops(self, accent: tuple[int, int, int]):
        black = (0, 0, 0)
        return [accent, mix(accent, black, 0.93), mix(accent, black, 0.84)]

    def test_every_stop_clears_aa_against_white(self, name: str) -> None:
        accent = THEMES[name]["accent"]
        worst = min(contrast((255, 255, 255), s) for s in self.stops(accent))
        assert worst >= AA_NORMAL, f"{name}: worst stop is {worst:.2f}:1"

    def test_no_stop_is_lighter_than_the_accent(self, name: str) -> None:
        """The accent sits exactly on the limit, so lighter is always a fail —
        and it is the tempting direction, because it looks better."""
        accent = THEMES[name]["accent"]
        base = luminance(accent)
        assert all(luminance(s) <= base + 1e-9 for s in self.stops(accent))

    def test_the_stylesheet_does_not_lighten_the_accent(self, name: str) -> None:
        """Guards the declaration itself, not just the numbers above."""
        block = re.search(r"--grad-accent:(.*?);", PAGE, re.S)
        assert block, "no --grad-accent declaration"
        mixes = re.findall(
            r"color-mix\(in srgb,\s*var\(--accent\)\s*\d+%,\s*([^)]+)\)",
            block.group(1),
        )
        assert mixes, "expected the gradient to be built from the accent"
        for other in mixes:
            other = other.strip()
            assert other in ("#000", "black"), (
                f"--grad-accent mixes the accent toward {other!r}; only black "
                f"is safe, since the accent already sits at the AA floor"
            )
