from __future__ import annotations

"""
reporter.py
Writes a structured JSON report summarising pipeline results.
"""

import json
import logging
from datetime import datetime
from pathlib import Path


class CampaignReporter:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def write(self, results: list[dict], brief: dict, output_path: Path):
        report = {
            "generated_at": datetime.now().isoformat(),
            "campaign": {
                "region": brief.get("region"),
                "target_audience": brief.get("target_audience"),
                "products": [p["name"] for p in brief.get("products", [])],
            },
            "summary": {
                "total_creatives": len(results),
                "products": len({r["product"] for r in results}),
                "aspect_ratios": len({r["aspect_ratio"] for r in results}),
                "legal_issues_found": sum(1 for r in results if r.get("legal_issues")),
                "brand_compliance_failures": sum(
                    1 for r in results
                    if not r.get("brand_compliance", {}).get("passed", True)
                ),
            },
            "creatives": results,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

        self._print_summary(report)

    def _print_summary(self, report: dict):
        s = report["summary"]
        self.logger.info("-" * 43)
        self.logger.info("         CAMPAIGN PIPELINE REPORT         ")
        self.logger.info("-" * 43)
        self.logger.info(f"  Creatives generated : {s['total_creatives']}")
        self.logger.info(f"  Products processed  : {s['products']}")
        self.logger.info(f"  Aspect ratios       : {s['aspect_ratios']}")
        self.logger.info(f"  Legal issues found  : {s['legal_issues_found']}")
        self.logger.info(f"  Brand comp. failures: {s['brand_compliance_failures']}")
        self.logger.info("-" * 43)
