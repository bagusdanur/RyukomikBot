"""Subprocess entrypoint for RAW page joining.

The join allocates a 15k-row RGB canvas plus a lossless WebP encoder, which can
spike several hundred MB. Running it in its own process keeps the dashboard API
(the PM2-managed uvicorn) small, so a heavy chapter can no longer restart the
server and surface as nginx 502.
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
from pathlib import Path

from .raw_join import prepare_inputs

LIMIT_BYTES = 1600 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths-json", required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--max-height", type=int, default=15000)
    args = parser.parse_args()
    try:
        resource.setrlimit(resource.RLIMIT_AS, (LIMIT_BYTES, LIMIT_BYTES))
    except (ValueError, OSError):
        pass
    paths = [Path(p) for p in json.loads(Path(args.paths_json).read_text())]
    outputs = prepare_inputs(paths, Path(args.directory), max_height=args.max_height)
    print(json.dumps([str(p) for p in outputs]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
