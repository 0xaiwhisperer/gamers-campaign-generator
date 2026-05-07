"""
run_web.py — starts the web UI from the repo root.

Usage:
    python run_web.py
"""
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    web_app = Path(__file__).parent / "web" / "app.py"
    print("Creative Automation Pipeline UI -> http://localhost:5000")
    subprocess.run([sys.executable, str(web_app)])