#!/usr/bin/env python3
"""从 release-dashboard.html 提取内嵌数据，导出到 data/ 目录。

用法:
  python3 scripts/export_embedded_data.py
  python3 scripts/export_embedded_data.py --html release-dashboard.html --out data
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


import argparse
import json
import re
from pathlib import Path


def extract_const(html: str, name: str):
    m = re.search(rf"const\s+{re.escape(name)}\s*=\s*([\[{{])", html)
    if not m:
        raise ValueError(f"未找到 const {name}")
    i = m.start(1)
    opener = html[i]
    if opener not in "{[":
        raise ValueError(f"const {name} 格式不支持")
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for j in range(i, len(html)):
        ch = html[j]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return json.loads(html[i : j + 1])
    raise ValueError(f"const {name} 解析失败")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default="release-dashboard.html")
    parser.add_argument("--out", default="data")
    args = parser.parse_args()

    html_path = Path(args.html)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    html = html_path.read_text(encoding="utf-8")

    exports = {
        "releases.json": extract_const(html, "R"),
        "tickets.json": extract_const(html, "TK"),
        "feedback.json": extract_const(html, "FB_RAW"),
        "store.json": extract_const(html, "SF_RAW"),
        "feature_keywords.json": extract_const(html, "FK_DEFAULT"),
    }

    for filename, data in exports.items():
        path = out_dir / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ {path} ({len(data)} records, {path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
