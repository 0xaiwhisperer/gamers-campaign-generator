"""
web/app.py — Flask web server for the Creative Automation Pipeline UI.

Run from the repo root:
    python web/app.py

Or via the helper script:
    python run_web.py
"""
from __future__ import annotations

import base64
import json
import os
import queue
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

# .resolve() is critical on Windows — expands symlinks and normalises drive letter.
_THIS_FILE = Path(__file__).resolve()  # e.g. C:\...\cap2\web\app.py
ROOT       = _THIS_FILE.parent.parent  # e.g. C:\...\cap2
STATIC_DIR = _THIS_FILE.parent / "static"
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from pipeline import (
    load_brief, AssetManager, ImageGenerator,
    BrandComplianceChecker, LegalChecker,
)

RUNS_DIR  = ROOT / "outputs"
META_FILE = "run_meta.json"

app = Flask(__name__)  # no static_folder — we handle it manually

runs: dict = {}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_run(run_id: str):
    run  = runs[run_id]
    meta = {
        "run_id":     run_id,
        "status":     run["status"],
        "brief":      run["brief"],
        "product":    run.get("product"),
        "started_at": run["started_at"],
        "output_dir": run["output_dir"],
        "error":      run["error"],
        "results": [{k: v for k, v in r.items() if k != "image_b64"} for r in run["results"]],
    }
    out = Path(run["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    (out / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _load_image_b64(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return base64.b64encode(p.read_bytes()).decode()


def _load_past_runs():
    if not RUNS_DIR.exists():
        return
    for meta_path in sorted(RUNS_DIR.glob(f"*/{META_FILE}"), reverse=True):
        try:
            meta   = json.loads(meta_path.read_text(encoding="utf-8"))
            run_id = meta["run_id"]
            results = []
            for r in meta.get("results", []):
                r["image_b64"] = _load_image_b64(r.get("path", ""))
                results.append(r)
            runs[run_id] = {
                "status":     meta.get("status", "done"),
                "log_queue":  queue.Queue(),
                "results":    results,
                "brief":      meta.get("brief", ""),
                "product":    meta.get("product"),
                "output_dir": meta.get("output_dir", ""),
                "started_at": meta.get("started_at", ""),
                "error":      meta.get("error"),
                "restored":   True,
            }
        except Exception as e:
            print(f"[startup] Could not load {meta_path}: {e}")


# ---------------------------------------------------------------------------
# Routes — static
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    index_path = STATIC_DIR / "index.html"
    app.logger.info(f"Serving index from: {index_path}")
    return send_file(str(index_path))


# ---------------------------------------------------------------------------
# Routes — inputs
# ---------------------------------------------------------------------------

@app.route("/api/briefs")
def list_briefs():
    d = ROOT / "inputs"
    files = [f.name for f in d.glob("*.json")] + [f.name for f in d.glob("*.yaml")]
    return jsonify(sorted(files))


@app.route("/api/brief/<filename>")
def get_brief(filename):
    p = ROOT / "inputs" / filename
    return send_file(p, mimetype="application/json") if p.exists() else (jsonify({"error": "Not found"}), 404)


@app.route("/api/upload-asset", methods=["POST"])
def upload_asset():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f    = request.files["file"]
    dest = ROOT / "inputs" / "assets" / f.filename
    f.save(dest)
    return jsonify({"saved": f.filename})


# ---------------------------------------------------------------------------
# Routes — runs
# ---------------------------------------------------------------------------

@app.route("/api/run", methods=["POST"])
def start_run():
    data           = request.json or {}
    brief_file     = data.get("brief", "brief.json")
    product        = data.get("product")
    dry_run        = data.get("dry_run", False)
    selected_games = data.get("selected_games")
    run_id         = str(uuid.uuid4())[:8]
    ts             = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir     = RUNS_DIR / f"run_{ts}_{run_id}"

    log_q = queue.Queue()
    runs[run_id] = {
        "status":     "running",
        "log_queue":  log_q,
        "results":    [],
        "brief":      brief_file,
        "product":    product,
        "output_dir": str(output_dir),
        "started_at": datetime.now().isoformat(),
        "error":      None,
        "restored":   False,
    }

    def worker(selected_games=selected_games):
        import logging

        class QueueHandler(logging.Handler):
            def emit(self, record):
                log_q.put({"type": "log", "msg": self.format(record)})

        handler = QueueHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

        try:
            brief = load_brief(str(ROOT / "inputs" / brief_file))

            if product:
                matched = [p for p in brief["products"] if p["name"].lower() == product.lower()]
                if matched:
                    brief["products"] = matched

            if selected_games:
                brief["selected_games"] = selected_games

            output_dir.mkdir(parents=True, exist_ok=True)
            asset_dir   = ROOT / "inputs" / "assets"
            asset_mgr   = AssetManager(asset_dir, logging.getLogger("asset"))
            img_gen     = ImageGenerator(logging.getLogger("imggen"), dry_run=dry_run)
            brand_check = BrandComplianceChecker(brief.get("brand_guidelines", {}), logging.getLogger("brand"))
            legal_check = LegalChecker(brief.get("prohibited_words", []), logging.getLogger("legal"))
            results     = []

            for product_obj in brief["products"]:
                pname   = product_obj["name"]
                message = product_obj.get("campaign_message", brief.get("campaign_message", ""))
                log_q.put({"type": "log", "msg": f"Processing: {pname}"})

                legal_issues = legal_check.check(message)
                existing     = asset_mgr.find(pname)

                if existing:
                    log_q.put({"type": "log", "msg": f"Reusing asset: {existing.name}"})
                    base_path = existing
                else:
                    log_q.put({"type": "log", "msg": f"Generating hero image for {pname}..."})
                    base_path = img_gen.generate(
                        prompt=img_gen.build_prompt(product_obj, brief),
                        output_path=asset_dir / f"{pname}_hero.png",
                    )

                themes = product_obj.get("gaming_themes") or brief.get("game_worlds", [])
                sel    = brief.get("selected_games")
                if themes and sel:
                    themes = [t for t in themes if t["game"] in sel]
                iterations = themes if themes else [None]

                for theme in iterations:
                    game      = theme["game"] if theme else None
                    theme_dir = game.replace(" ", "_") if game else "default"

                    for ratio in ["1x1", "9x16", "16x9"]:
                        log_q.put({"type": "log", "msg":
                            f"  Generating {ratio}" + (f" [{game}]" if game else "") + "..."})

                        final, canvas = img_gen.create_variation(
                            source_path=base_path,
                            ratio_label=ratio,
                            product=product_obj,
                            brief=brief,
                            output_path=output_dir / pname / theme_dir / ratio / "final.png",
                            gaming_theme=theme,
                        )

                        compliance = brand_check.check(final, product_obj)
                        with open(final, "rb") as fh:
                            img_b64 = base64.b64encode(fh.read()).decode()

                        entry = {
                            "product":          pname,
                            "game":             game,
                            "ratio":            ratio,
                            "path":             str(final),
                            "image_b64":        img_b64,
                            "legal_issues":     legal_issues,
                            "brand_compliance": compliance,
                            "canvas_size":      list(canvas),
                        }
                        results.append(entry)
                        runs[run_id]["results"] = list(results)
                        log_q.put({"type": "image", "data": entry})
                        log_q.put({"type": "log", "msg":
                            f"  Saved {pname}" + (f" / {game}" if game else "") + f" / {ratio}"})

            runs[run_id]["status"] = "done"
            _save_run(run_id)
            log_q.put({"type": "done", "results": results})

        except Exception as e:
            runs[run_id]["status"] = "error"
            runs[run_id]["error"]  = str(e)
            _save_run(run_id)
            log_q.put({"type": "error", "msg": traceback.format_exc()})
        finally:
            root_logger.removeHandler(handler)

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"run_id": run_id})


@app.route("/api/run/<run_id>/stream")
def stream_run(run_id):
    if run_id not in runs:
        return jsonify({"error": "Not found"}), 404
    run = runs[run_id]

    if run.get("restored") or run["status"] != "running":
        def replay():
            for r in run["results"]:
                yield f"data: {json.dumps({'type': 'image', 'data': r})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return Response(replay(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def generate():
        while True:
            try:
                event = run["log_queue"].get(timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ("done", "error"):
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/runs")
def list_runs():
    return jsonify([
        {
            "run_id":     rid,
            "status":     r["status"],
            "brief":      r["brief"],
            "product":    r.get("product"),
            "started_at": r["started_at"],
            "count":      len(r["results"]),
            "restored":   r.get("restored", False),
        }
        for rid, r in sorted(runs.items(), key=lambda x: x[1].get("started_at", ""), reverse=True)
    ])


@app.route("/api/image")
def serve_image():
    path = request.args.get("path")
    if not path or not Path(path).exists():
        return "Not found", 404
    return send_file(path, mimetype="image/png")


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

_load_past_runs()
print(f"[startup] Loaded {len(runs)} past run(s) from disk.")

if __name__ == "__main__":
    print("Creative Automation Pipeline UI -> http://localhost:5000")
    app.run(debug=False, port=5000, threaded=True)