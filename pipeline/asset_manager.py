from __future__ import annotations

"""
asset_manager.py
Looks for an existing hero image for a product in the local assets folder.
Matches by product name (case-insensitive, ignoring spaces/underscores).
"""

import logging
from pathlib import Path


SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class AssetManager:
    def __init__(self, asset_dir: Path, logger: logging.Logger):
        self.asset_dir = asset_dir
        self.logger = logger
        asset_dir.mkdir(parents=True, exist_ok=True)

    def find(self, product_name: str) -> Path | None:
        """
        Search asset_dir for a file whose stem loosely matches product_name.
        Returns the Path if found, None otherwise.
        """
        normalised = _normalise(product_name)
        for f in self.asset_dir.iterdir():
            if f.suffix.lower() in SUPPORTED_EXTENSIONS:
                if _normalise(f.stem) == normalised:
                    self.logger.debug(f"Asset match: {f} for product '{product_name}'")
                    return f
        return None

    def list_all(self) -> list[Path]:
        return [
            f for f in self.asset_dir.iterdir()
            if f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]


def _normalise(name: str) -> str:
    return name.lower().replace(" ", "").replace("_", "").replace("-", "")
