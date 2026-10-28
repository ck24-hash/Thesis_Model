"""Open the thesis model interface in your browser.

    python interface/app.py     (add --no-browser to only print the address, --port to choose the port)

It starts a small web server on this computer (Python standard library, nothing to install beyond the models' own
requirements) and opens http://127.0.0.1:8775. The models are not changed: the interface only imports them.
Keep this window open while you use the page; close it (Ctrl+C) to stop.
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import warnings
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the project root: interface/ and common/

from interface.server import serve  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open the thesis model interface in your browser.")
    parser.add_argument("--port", type=int, default=8775)
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)
    warnings.filterwarnings("ignore")
    for name in ("pypsa", "linopy"):
        logging.getLogger(name).setLevel(logging.WARNING)

    server = serve(args.port)
    address = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Thesis model interface: {address}\nKeep this window open while you use it. Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(address,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
