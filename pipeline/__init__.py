"""
pipeline — core creative automation logic.

Importable by both the CLI (pipeline.py) and the web server (web/app.py).
"""

from .brief_loader import load_brief
from .asset_manager import AssetManager
from .image_generator import ImageGenerator
from .compliance import BrandComplianceChecker, LegalChecker
from .reporter import CampaignReporter

__all__ = [
    "load_brief",
    "AssetManager",
    "ImageGenerator",
    "BrandComplianceChecker",
    "LegalChecker",
    "CampaignReporter",
]
