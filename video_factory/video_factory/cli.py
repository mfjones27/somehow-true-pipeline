import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .api import MAX_BODY_BYTES, create_app, strict_json
from .errors import FactoryError
from .jobs import JobStore
from .models import parse_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local-only explicit-manifest video renderer")
    subparsers = parser.add_subparsers(dest="command", required=True)
    render = subparsers.add_parser("render")
    render.add_argument("manifest", type=Path)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if args.command == "serve":
        if not 1024 <= args.port <= 65535:
            parser.error("Port must be 1024–65535")
        import uvicorn
        uvicorn.run(create_app(), host="127.0.0.1", port=args.port, workers=1,
                    proxy_headers=False, limit_concurrency=8, timeout_keep_alive=5,
                    timeout_graceful_shutdown=610)
        return 0
    try:
        with args.manifest.open("rb") as handle:
            raw = handle.read(MAX_BODY_BYTES + 1)
        if len(raw) > MAX_BODY_BYTES:
            raise ValueError("Manifest exceeds 128 KiB")
        manifest = parse_manifest(strict_json(raw))
        print(json.dumps(JobStore().render(manifest), indent=2))
        return 0
    except (FactoryError, ValidationError, OSError, ValueError, RecursionError) as exc:
        print(f"Render rejected or failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

