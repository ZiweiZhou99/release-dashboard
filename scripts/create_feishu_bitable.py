#!/usr/bin/env python3
"""通过飞书开放平台 API 创建多维表格并导入数据。

前置（一次性，约 5 分钟）：
  1. 打开 https://open.feishu.cn/app 创建企业自建应用
  2. 权限：创建多维表格、查看/编辑多维表格
  3. 发布应用后，在飞书「工作台」安装该应用
  4. 将 App ID、App Secret 写入 .config/tokens/feishu.json：
     {"app_id": "cli_xxx", "app_secret": "xxx"}

用法:
  python3 scripts/export_feishu_voice_closure.py   # 先导出 CSV
  python3 scripts/create_feishu_bitable.py
  python3 scripts/create_feishu_bitable.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
FEISHU_CFG = WORKSPACE / '.config' / 'tokens' / 'feishu.json'
EXPORT_DIR = WORKSPACE / 'exports' / 'feishu'
API = 'https://open.feishu.cn/open-apis'

TABLE_SPECS = [
    {
        'name': '发版项台账',
        'csv_glob': '1_发版项台账_*.csv',
        'fields': [
            ('发版项ID', 1),
            ('版本号', 1),
            ('发版日期', 1),
            ('机型', 1),
            ('发版项名称', 1),
            ('来源', 1),
            ('自动初筛', 1),
            ('用户可感知', 1),
            ('用户价值一句话', 1),
            ('关联原声数', 2),
            ('备注', 1),
        ],
    },
    {
        'name': '用户原声关联',
        'csv_glob': '2_用户原声关联_*.csv',
        'fields': [
            ('关联ID', 1),
            ('发版项ID', 1),
            ('版本号', 1),
            ('发版项名称', 1),
            ('原声ID', 1),
            ('原声来源', 1),
            ('用户ID', 1),
            ('设备', 1),
            ('原声时间', 1),
            ('原声摘要', 1),
            ('原声链接', 15),
            ('匹配分', 2),
            ('匹配关键词', 1),
            ('关联类型', 1),
            ('关联已确认', 1),
            ('需要触达', 1),
            ('触达状态', 1),
            ('触达话术', 1),
            ('触达人', 1),
            ('触达时间', 1),
            ('备注', 1),
        ],
    },
    {
        'name': '触达清单',
        'csv_glob': '3_触达清单候选_*.csv',
        'fields': [
            ('关联ID', 1),
            ('版本号', 1),
            ('发版项名称', 1),
            ('用户ID', 1),
            ('设备', 1),
            ('原声摘要', 1),
            ('原声链接', 15),
            ('触达状态', 1),
            ('触达话术', 1),
            ('触达人', 1),
            ('触达时间', 1),
            ('备注', 1),
        ],
    },
]


def log(msg: str) -> None:
    print(msg, flush=True)


def load_cfg() -> dict:
    if not FEISHU_CFG.exists():
        raise FileNotFoundError(
            f'未找到 {FEISHU_CFG}\n'
            '请创建飞书自建应用，并写入 {"app_id":"...","app_secret":"..."}'
        )
    cfg = json.loads(FEISHU_CFG.read_text(encoding='utf-8'))
    if not cfg.get('app_id') or not cfg.get('app_secret'):
        raise ValueError('feishu.json 需包含 app_id 与 app_secret')
    return cfg


def api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    url = f'{API}{path}'
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json; charset=utf-8',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'HTTP {e.code}: {raw[:500]}') from e
    out = json.loads(raw)
    if out.get('code') != 0:
        raise RuntimeError(f"飞书 API 错误 {out.get('code')}: {out.get('msg')}")
    return out


def tenant_token(cfg: dict) -> str:
    url = f'{API}/auth/v3/tenant_access_token/internal'
    req = urllib.request.Request(
        url,
        data=json.dumps({'app_id': cfg['app_id'], 'app_secret': cfg['app_secret']}).encode(),
        method='POST',
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode())
    if out.get('code') != 0:
        raise RuntimeError(f"获取 token 失败: {out.get('msg')}")
    return out['tenant_access_token']


def latest_csv(pattern: str) -> Path:
    files = sorted(EXPORT_DIR.glob(pattern))
    if not files:
        raise FileNotFoundError(f'未找到 {EXPORT_DIR}/{pattern}，请先运行 export_feishu_voice_closure.py')
    return files[-1]


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def create_app(token: str, name: str) -> dict:
    out = api('POST', '/bitable/v1/apps', token, {'name': name, 'folder_token': ''})
    return out['data']['app']


def create_table(token: str, app_token: str, name: str, fields: list[tuple[str, int]]) -> str:
    body = {
        'table': {
            'name': name,
            'fields': [{'field_name': n, 'type': t} for n, t in fields],
        }
    }
    out = api('POST', f'/bitable/v1/apps/{app_token}/tables', token, body)
    return out['data']['table_id']


def batch_insert(token: str, app_token: str, table_id: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    total = 0
    chunk = 400
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        records = [{'fields': {k: (v if v != '' else None) for k, v in row.items()}} for row in part]
        api(
            'POST',
            f'/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create',
            token,
            {'records': records},
        )
        total += len(part)
        time.sleep(0.3)
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', default='学练机·发版用户声音闭环')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if args.dry_run:
        for spec in TABLE_SPECS:
            path = latest_csv(spec['csv_glob'])
            rows = read_csv(path)
            log(f"[dry-run] {spec['name']}: {len(rows)} 行 ← {path.name}")
        log('配置就绪。写入 feishu.json 后去掉 --dry-run 即可创建。')
        return 0

    cfg = load_cfg()
    token = tenant_token(cfg)
    log('已获取 tenant_access_token')

    app = create_app(token, args.name)
    app_token = app['app_token']
    app_url = app.get('url') or f'https://feishu.cn/base/{app_token}'
    log(f'已创建多维表格: {app_url}')

    # 默认有一张「数据表」，改名为第一张或忽略
    for spec in TABLE_SPECS:
        csv_path = latest_csv(spec['csv_glob'])
        rows = read_csv(csv_path)
        table_id = create_table(token, app_token, spec['name'], spec['fields'])
        n = batch_insert(token, app_token, table_id, rows)
        log(f"  ✓ {spec['name']}: {n} 条")

    meta_path = WORKSPACE / 'exports' / 'feishu' / 'bitable_created.json'
    meta_path.write_text(json.dumps({
        'app_token': app_token,
        'url': app_url,
        'name': args.name,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    log(f'\n完成！打开链接: {app_url}')
    log('若链接打不开，在飞书云文档搜索表格名称，或把应用加为文档协作者。')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as e:
        log(f'错误: {e}')
        raise SystemExit(1)
