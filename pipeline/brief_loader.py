from __future__ import annotations

"""
brief_loader.py
Loads and validates a campaign brief from JSON or YAML.
Raises clear errors for missing required fields.
"""

import json
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = {"products", "region", "target_audience"}
REQUIRED_PER_PRODUCT = {"name"}


def load_brief(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Brief not found: {path}")

    suffix = p.suffix.lower()

    if suffix == ".json":
        with open(p) as f:
            data = json.load(f)

    elif suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML is required for YAML briefs — pip install pyyaml")
        with open(p) as f:
            data = yaml.safe_load(f)

    else:
        raise ValueError(f"Unsupported brief format: {suffix}. Use .json or .yaml")

    _validate(data, path)
    return data


def _validate(data: dict, path: str):
    missing_top = REQUIRED_TOP_LEVEL - set(data.keys())
    if missing_top:
        raise ValueError(f"Brief '{path}' is missing required fields: {missing_top}")

    if not isinstance(data["products"], list) or len(data["products"]) < 1:
        raise ValueError("Brief must contain at least one product under 'products'.")

    for i, product in enumerate(data["products"]):
        missing_prod = REQUIRED_PER_PRODUCT - set(product.keys())
        if missing_prod:
            raise ValueError(
                f"Product #{i} in brief is missing required fields: {missing_prod}"
            )

        # Ensure each product has a campaign_message (fallback to top-level)
        if "campaign_message" not in product and "campaign_message" not in data:
            raise ValueError(
                f"Product '{product.get('name', i)}' has no 'campaign_message' "
                "and no top-level 'campaign_message' fallback."
            )
