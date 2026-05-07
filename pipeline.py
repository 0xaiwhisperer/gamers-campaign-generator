"""
pipeline.py — CLI entry point for the Creative Automation Pipeline.

Usage:
    python pipeline.py --brief inputs/brief.json
    python pipeline.py --brief inputs/brief.json --product "FruityBurst Gummies"
    python pipeline.py --brief inputs/brief.json --dry-run
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pipeline import (
    load_brief, AssetManager, ImageGenerator,
    BrandComplianceChecker, LegalChecker, CampaignReporter,
)

BASE_DIR = Path(__file__).parent


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    fmt = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"

    fh = logging.FileHandler(log_dir / f"pipeline_{ts}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt))

    sh = logging.StreamHandler(
        io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    )
    sh.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(sh)

    logger = logging.getLogger("pipeline")
    logger.info(f"Logging -> {log_dir / f'pipeline_{ts}.log'}")
    return logger


def run_pipeline(
    brief_path: str,
    output_dir: str,
    dry_run: bool = False,
    product_filter: str | None = None,
) -> list[dict]:
    logger = setup_logging(BASE_DIR / "logs")
    brief  = load_brief(brief_path)
    logger.info(f"Brief loaded - {len(brief['products'])} product(s), region={brief['region']}")

    if product_filter:
        matched = [p for p in brief["products"] if p["name"].lower() == product_filter.lower()]
        if not matched:
            raise ValueError(f"Product '{product_filter}' not found. Available: {[p['name'] for p in brief['products']]}")
        brief["products"] = matched
        logger.info(f"Product filter: {product_filter}")

    out_root  = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    asset_dir = BASE_DIR / "inputs" / "assets"

    asset_mgr   = AssetManager(asset_dir, logger)
    img_gen     = ImageGenerator(logger, dry_run=dry_run)
    brand_check = BrandComplianceChecker(brief.get("brand_guidelines", {}), logger)
    legal_check = LegalChecker(brief.get("prohibited_words", []), logger)
    reporter    = CampaignReporter(logger)
    results: list[dict] = []

    for product in brief["products"]:
        name    = product["name"]
        message = product.get("campaign_message", brief.get("campaign_message", ""))
        logger.info("=" * 60)
        logger.info(f"Processing: {name}")

        legal_issues = legal_check.check(message)
        if legal_issues:
            logger.warning(f"Legal issues: {legal_issues}")

        existing = asset_mgr.find(name)
        base_path = existing if existing else img_gen.generate(
            prompt=img_gen.build_prompt(product, brief),
            output_path=asset_dir / f"{name}_hero.png",
        )
        if existing:
            logger.info(f"Reusing asset: {existing.name}")
        else:
            logger.info("Generated new hero image")

        # Support both product-level gaming_themes and brief-level game_worlds
        themes = product.get("gaming_themes") or brief.get("game_worlds", [])
        sel    = brief.get("selected_games")
        if themes and sel:
            themes = [t for t in themes if t["game"] in sel]
        iterations = themes if themes else [None]

        for theme in iterations:
            game      = theme["game"] if theme else None
            theme_dir = game.replace(" ", "_") if game else "default"
            if game:
                logger.info(f"  Theme: {game}")

            for ratio in ["1x1", "9x16", "16x9"]:
                logger.info(f"    Generating {ratio}" + (f" [{game}]" if game else "") + "...")
                final, canvas = img_gen.create_variation(
                    source_path=base_path,
                    ratio_label=ratio,
                    product=product,
                    brief=brief,
                    output_path=out_root / name / theme_dir / ratio / "final.png",
                    gaming_theme=theme,
                )
                results.append({
                    "product": name, "game": game, "aspect_ratio": ratio,
                    "output": str(final), "legal_issues": legal_issues,
                    "brand_compliance": brand_check.check(final, product),
                })
                logger.info(f"    Saved -> {final}")

    reporter.write(results, brief, out_root / "campaign_report.json")
    logger.info("=" * 60)
    logger.info(f"Done. {len(results)} creatives -> {out_root}")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Creative Automation Pipeline")
    p.add_argument("--brief",   required=True)
    p.add_argument("--output",  default="outputs")
    p.add_argument("--product", default=None)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    run_pipeline(a.brief, a.output, dry_run=a.dry_run, product_filter=a.product)


if __name__ == "__main__":
    main()