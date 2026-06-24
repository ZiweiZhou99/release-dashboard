#!/usr/bin/env python3
"""为 data/*.json 生成 .gz 侧车文件（可选；upload_server 也会在线 gzip）。"""

from __future__ import annotations

import gzip
import os
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
DATA_DIR = WORKSPACE / 'data'


def compress_file(path: Path) -> int:
    raw = path.read_bytes()
    gz_path = path.with_suffix(path.suffix + '.gz')
    with gzip.open(gz_path, 'wb', compresslevel=6) as f:
        f.write(raw)
    return len(raw), gz_path.stat().st_size


def main() -> int:
    total_raw = 0
    total_gz = 0
    for path in sorted(DATA_DIR.glob('*.json')):
        raw, gz = compress_file(path)
        total_raw += raw
        total_gz += gz
        print(f'{path.name}: {raw/1024:.1f} KB → {gz/1024:.1f} KB')
    print(f'合计: {total_raw/1024/1024:.2f} MB → {total_gz/1024/1024:.2f} MB')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
