#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_id")
    parser.add_argument("local_dir")
    args = parser.parse_args()

    from huggingface_hub import snapshot_download

    path = snapshot_download(
        repo_id=args.repo_id,
        local_dir=str(Path(args.local_dir).expanduser()),
        local_dir_use_symlinks=False,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
