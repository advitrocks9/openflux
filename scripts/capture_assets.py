#!/usr/bin/env python3
"""Capture dashboard screenshots for the README.

Starts ``openflux serve`` locally, takes 1440x900 screenshots of each
dashboard tab using headless Chrome, saves to ``assets/screenshots/``.

Requires:
    - Chrome or Chromium installed (autodetected; macOS app bundle works)
    - openflux installed (``uv run scripts/capture_assets.py`` from a checkout
      uses the local source; ``pip install openflux`` works too)
    - ``~/.openflux/traces.db`` populated with at least one trace; for the
      Sessions tab to show outcome rows (instead of the empty state), at
      least one Claude Code session must have run with the wedge hooks
      installed and ``OPENFLUX_TEST_CMD`` configured.

Usage:
    uv run scripts/capture_assets.py
    uv run scripts/capture_assets.py --port 5174 --asset-dir docs/assets

Light-mode capture is on the roadmap. Today the script captures dark mode
only. To capture light mode manually: run ``openflux serve``, toggle the
theme button in the header, screenshot at 1440x900.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 5179  # off the global :5173 herd
DEFAULT_ASSET_DIR = Path("assets/screenshots")
SERVER_HEALTH_TIMEOUT_S = 30.0
SERVER_HEALTH_POLL_S = 0.5
PER_TAB_RENDER_MS = 3000

TABS: list[tuple[str, str]] = [
    ("sessions", "#sessions"),
    ("traces", "#traces"),
    ("stats", "#stats"),
]


def find_chrome() -> str | None:
    """Locate Chrome/Chromium/Brave/Edge/Arc on PATH or in macOS /Applications.

    Override with CHROME_PATH env var or --chrome flag.
    """
    import os

    explicit = os.environ.get("CHROME_PATH")
    if explicit and Path(explicit).exists():
        return explicit

    for cmd in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "microsoft-edge",
        "chrome",
    ):
        path = shutil.which(cmd)
        if path:
            return path

    mac_apps = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Arc.app/Contents/MacOS/Arc",
    )
    for candidate in mac_apps:
        if Path(candidate).exists():
            return candidate
    return None


def wait_for_server(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    health_url = f"http://localhost:{port}/api/stats"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(SERVER_HEALTH_POLL_S)
    return False


def capture(chrome: str, port: int, hash_route: str, out: Path) -> None:
    url = f"http://localhost:{port}/{hash_route}"
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        f"--screenshot={out}",
        "--window-size=1440,900",
        f"--virtual-time-budget={PER_TAB_RENDER_MS}",
        url,
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument(
        "--chrome",
        type=str,
        default=None,
        help="Path to Chrome/Chromium/Brave/Edge/Arc. Overrides autodetection.",
    )
    parser.add_argument(
        "--skip-server",
        action="store_true",
        help="Assume openflux serve is already running on --port",
    )
    args = parser.parse_args()

    chrome = args.chrome or find_chrome()
    if not chrome:
        print(
            "error: no Chromium-based browser found.\n"
            "  Tried: google-chrome, chromium, brave-browser, microsoft-edge\n"
            "  Override with: --chrome /path/to/browser  or  CHROME_PATH=/path",
            file=sys.stderr,
        )
        return 1

    args.asset_dir.mkdir(parents=True, exist_ok=True)

    server: subprocess.Popen[bytes] | None = None
    if not args.skip_server:
        print(f"starting openflux serve on :{args.port}")
        server = subprocess.Popen(
            ["openflux", "serve", "--port", str(args.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    try:
        if not wait_for_server(args.port, SERVER_HEALTH_TIMEOUT_S):
            print(
                f"error: server did not respond on :{args.port} within "
                f"{SERVER_HEALTH_TIMEOUT_S}s",
                file=sys.stderr,
            )
            return 1

        for tab_name, hash_route in TABS:
            out = args.asset_dir / f"{tab_name}-dark.png"
            try:
                capture(chrome, args.port, hash_route, out)
            except subprocess.CalledProcessError as exc:
                print(
                    f"error: chrome capture failed for {tab_name}: "
                    f"{exc.stderr.decode(errors='replace')[:200]}",
                    file=sys.stderr,
                )
                return 1
            print(f"  captured {out} ({out.stat().st_size // 1024}KB)")
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()

    print(f"\ndone. {len(TABS)} screenshots in {args.asset_dir}/")
    print("light mode capture is a TODO; toggle theme manually for now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
