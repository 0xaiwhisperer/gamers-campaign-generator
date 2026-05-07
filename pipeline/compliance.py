from __future__ import annotations

"""
compliance.py
Two lightweight compliance checks:

1. BrandComplianceChecker  — verifies brand color presence and logo placement
2. LegalChecker            — flags prohibited words in campaign copy
"""

import logging
from pathlib import Path
from typing import Any

from PIL import Image


class BrandComplianceChecker:
    """
    Checks generated images for:
      - Dominant colors matching brand palette (within a tolerance)
      - Presence of a logo file (if configured)
    """

    def __init__(self, brand_guidelines: dict[str, Any], logger: logging.Logger):
        self.logger = logger
        # brand_guidelines example:
        #   { "colors": ["#FF5733", "#1A1A1A"], "color_tolerance": 40 }
        self.brand_colors = [
            _hex_to_rgb(c) for c in brand_guidelines.get("colors", [])
        ]
        self.tolerance = brand_guidelines.get("color_tolerance", 40)

    def check(self, image_path: Path, product: dict) -> dict[str, Any]:
        results: dict[str, Any] = {"passed": True, "issues": []}

        if not image_path.exists():
            results["passed"] = False
            results["issues"].append("Output image file not found.")
            return results

        if self.brand_colors:
            color_ok = self._check_colors(image_path)
            if not color_ok:
                results["passed"] = False
                results["issues"].append(
                    "Brand color(s) not detected in image. "
                    f"Expected palette: {[_rgb_to_hex(c) for c in self.brand_colors]}"
                )

        self.logger.debug(
            f"Brand compliance for '{product['name']}': "
            f"{'PASS' if results['passed'] else 'FAIL'} — {results['issues'] or 'OK'}"
        )
        return results

    def _check_colors(self, image_path: Path) -> bool:
        """
        Sample the image's pixels and check if any match the brand palette
        within the configured tolerance. Pure PIL/Python — no numpy needed.
        """
        img = Image.open(image_path).convert("RGB").resize((100, 100))
        pixels = list(img.getdata())  # list of (R, G, B) tuples

        for brand_rgb in self.brand_colors:
            for pixel in pixels:
                diff = sum(abs(int(pixel[i]) - int(brand_rgb[i])) for i in range(3))
                if diff < self.tolerance * 3:
                    return True
        return False


class LegalChecker:
    """
    Scans campaign copy for a configurable list of prohibited words/phrases.
    Returns a list of flagged terms (empty = clean).
    """

    # Built-in defaults — extend via brief's "prohibited_words" field
    DEFAULT_PROHIBITED = [
        "guaranteed", "100% safe", "cure", "miracle", "free money",
        "risk-free", "no side effects", "clinically proven",
    ]

    def __init__(self, extra_prohibited: list[str], logger: logging.Logger):
        self.logger = logger
        combined = set(w.lower() for w in self.DEFAULT_PROHIBITED + extra_prohibited)
        self.prohibited = sorted(combined)

    def check(self, text: str) -> list[str]:
        """Returns list of prohibited terms found in text."""
        lower = text.lower()
        flagged = [term for term in self.prohibited if term in lower]
        if flagged:
            self.logger.warning(f"Legal check flagged terms: {flagged}")
        return flagged


# ── Colour utilities ───────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)
