#!/usr/bin/env python3
"""从 JUST 工单系统拉取「产研-学练机」工单，写入 data/tickets.json。

依赖浏览器登录态 Cookie（与当初内嵌 HTML 时相同做法）。

用法:
  python3 scripts/fetch_tickets.py --days 1          # 拉最近 1 天，与现有数据合并
  python3 scripts/fetch_tickets.py --days 30       # 拉最近 30 天
  python3 scripts/fetch_tickets.py --days 1 --replace  # 仅保留本次拉取结果
  python3 scripts/fetch_tickets.py --check           # 只验证 Cookie

凭证: .config/tokens/work-order.cookie（登录 https://work-order.zhenguanyu.com 后复制）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

WORKSPACE = os.environ.get('RELEASE_PLATFORM_HOME', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COOKIE_PATH = os.path.join(WORKSPACE, '.config/tokens/work-order.cookie')
OUTPUT_PATH = os.path.join(WORKSPACE, 'data/tickets.json')
BASE_URL = 'https://work-order.zhenguanyu.com'
BIZ_ID = 'znyj'
LIST_API = f'{BASE_URL}/turing/api/{BIZ_ID}/ticket'
DETAIL_API = f'{BASE_URL}/turing/api/{BIZ_ID}/ticket'
MENU_ID = 5  # 全部工单
PAGE_SIZE = 50
CLASSIFY_KEYWORD = '产研-学练机'
# znyj 分类树中「产研-学练机(新)」根节点 ID（/turing/api/znyj/classify）
CLASSIFY_ROOT_IDS = [9790]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_cookie() -> str:
    if not os.path.exists(COOKIE_PATH):
        raise FileNotFoundError(
            f'未找到工单 Cookie: {COOKIE_PATH}\n'
            '请登录 https://work-order.zhenguanyu.com 后在开发者工具 Network 里复制 Cookie 整行写入该文件。'
        )
    cookie = open(COOKIE_PATH, encoding='utf-8').read().strip()
    if not cookie:
        raise ValueError(f'Cookie 文件为空: {COOKIE_PATH}')
    return cookie


def api_get(path: str, params: dict | None = None, cookie: str | None = None) -> dict:
    cookie = cookie or load_cookie()
    qs = urllib.parse.urlencode(params or {}, doseq=True)
    url = f'{path}?{qs}' if qs else path
    req = urllib.request.Request(
        url,
        headers={
            'Cookie': cookie,
            'Accept': 'application/json',
            'User-Agent': 'release-dashboard-fetch/1.0',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        snippet = e.read(300).decode('utf-8', errors='replace')
        if e.code in (401, 403):
            raise RuntimeError(
                f'工单 API 认证失败 (HTTP {e.code})，请更新 {COOKIE_PATH}\n{snippet}'
            ) from e
        raise RuntimeError(f'工单 API 错误 HTTP {e.code}: {snippet}') from e
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f'工单 API 返回非 JSON（Cookie 可能过期）: {body[:200]}') from e
    if isinstance(data, dict) and data.get('status') == 401:
        raise RuntimeError(f'工单 API 未登录，请更新 Cookie: {data.get("message", "")}')
    return data


def unwrap_payload(resp: dict) -> dict:
    """列表/详情接口直接返回 {pageInfo, list} 或 {data: ...}。"""
    if not isinstance(resp, dict):
        return {}
    if 'list' in resp or 'pageInfo' in resp:
        return resp
    inner = resp.get('data')
    return inner if isinstance(inner, dict) else resp


def unwrap_ticket(resp: dict) -> dict:
    if not isinstance(resp, dict):
        return {}
    if 'id' in resp and ('classify' in resp or 'template' in resp or 'values' in resp):
        return resp
    inner = resp.get('data')
    return inner if isinstance(inner, dict) else resp


def sanitize(s: str) -> str:
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s or '')


def build_desc(ticket: dict) -> str:
    fields = (ticket.get('template') or {}).get('fields') or []
    values = ticket.get('values') or {}
    if not isinstance(values, dict):
        return sanitize(str(ticket.get('description') or ''))
    parts: list[str] = []
    for field in fields:
        fid = field.get('id')
        key = str(fid) if fid is not None else ''
        val = values.get(fid, values.get(key))
        if val is None or val == '':
            continue
        if isinstance(val, list):
            text = '、'.join(str(x) for x in val)
        elif isinstance(val, dict):
            text = json.dumps(val, ensure_ascii=False)
        else:
            text = str(val)
        name = field.get('name') or ''
        parts.append(f'【{name}】{text}')
    if parts:
        return sanitize('\n'.join(parts))
    return sanitize(str(ticket.get('description') or ticket.get('classify') or ''))


def extract_field(desc: str, label: str) -> str:
    m = re.search(rf'【{re.escape(label)}】\s*(.*?)(?=\n【|\Z)', desc, re.S)
    return m.group(1).strip() if m else ''


def normalize_device(raw: str) -> str:
    raw = (raw or '').strip()
    if not raw:
        return ''
    if 'S2（' in raw or 'S2(' in raw:
        return 'S2（S2、S2N、S2A）'
    # order matters: longer codes first
    for code in ('T6Pro', 'P40', 'S6', 'E1', 'S1', 'S2'):
        if re.search(rf'(?i){re.escape(code)}', raw.replace(' ', '')):
            return 'S2（S2、S2N、S2A）' if code == 'S2' and ('S2N' in raw or 'S2A' in raw) else code
    return raw[:40]


def normalize_status(status) -> str:
    if status is None:
        return ''
    if isinstance(status, str):
        return status
    mapping = {
        0: 'pending',
        1: 'processing',
        2: 'processing',
        3: 'closed',
        4: 'finished',
        5: 'finished',
    }
    return mapping.get(int(status), str(status))


def fmt_time(ts) -> str:
    if not ts:
        return ''
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
        return dt.strftime('%m-%d %H:%M')
    return str(ts)


def to_record(ticket: dict) -> dict | None:
    classify = sanitize(str(ticket.get('classify') or ''))
    if CLASSIFY_KEYWORD not in classify:
        return None
    desc = build_desc(ticket)
    creator = ticket.get('creator') or {}
    creator_name = creator.get('name') if isinstance(creator, dict) else str(creator or '')
    tid = ticket.get('id')
    if not tid:
        return None
    device_raw = extract_field(desc, '设备型号')
    return {
        'id': int(tid),
        'time': fmt_time(ticket.get('createTime')),
        'creator': sanitize(creator_name),
        'classify': classify,
        'status': normalize_status(ticket.get('status')),
        'desc': desc,
        'device': normalize_device(device_raw),
        'grade': sanitize(extract_field(desc, '年级')),
        'problem': sanitize(extract_field(desc, '用户问题描述')),
        'url': f'{BASE_URL}/next/#/znyj/ticket/detail/{tid}',
    }


def fetch_ticket_list(cookie: str, start_ms: int, end_ms: int) -> list[dict]:
    items: list[dict] = []
    page = 0
    total_page = None
    q = json.dumps({
        'createTimeBegin': start_ms,
        'createTimeEnd': end_ms,
        'filterDeletedClassify': 'false',
        'classifies': CLASSIFY_ROOT_IDS,
    }, ensure_ascii=False)

    while True:
        params = {
            'page': page,
            'pageSize': PAGE_SIZE,
            'menuId': MENU_ID,
            'q': q,
        }
        resp = api_get(LIST_API, params, cookie=cookie)
        data = unwrap_payload(resp)
        batch = data.get('list') or []
        page_info = data.get('pageInfo') or {}
        if total_page is None:
            total_page = page_info.get('totalPage', 0)
            total_item = page_info.get('totalItem', len(batch))
            log(f'列表第 0 页: 本页 {len(batch)} 条，合计约 {total_item} 条')
        items.extend(batch)
        page += 1
        if not batch or (total_page and page >= total_page):
            break
        time.sleep(0.15)
    return items


def fetch_ticket_detail(ticket_id: int, cookie: str) -> dict:
    resp = api_get(f'{DETAIL_API}/{ticket_id}', cookie=cookie)
    return unwrap_ticket(resp)


def merge_records(existing: list[dict], new_items: list[dict]) -> list[dict]:
    by_id = {int(x['id']): x for x in existing if x.get('id')}
    for item in new_items:
        by_id[int(item['id'])] = item

    def sort_key(x: dict):
        tid = int(x.get('id') or 0)
        return tid

    return sorted(by_id.values(), key=sort_key, reverse=True)


def check_auth() -> None:
    cookie = load_cookie()
    resp = api_get(f'{BASE_URL}/turing/api/{BIZ_ID}/users/current', cookie=cookie)
    user = unwrap_ticket(resp)
    name = user.get('nickname') or user.get('ldapId') or user.get('name') or user
    log(f'JUST 登录 OK ({BIZ_ID}): {name}')


def main() -> int:
    parser = argparse.ArgumentParser(description='拉取 JUST 产研-学练机工单')
    parser.add_argument('--days', type=int, default=1, help='拉取最近 N 天（默认 1）')
    parser.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD', help='起始日期（含）')
    parser.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD', help='结束日期（含当天）')
    parser.add_argument('--replace', action='store_true', help='不合并旧数据，输出仅含本次拉取')
    parser.add_argument('--no-detail', action='store_true', help='不拉详情（更快但 desc 可能不完整）')
    parser.add_argument('--check', action='store_true', help='仅验证 Cookie')
    parser.add_argument('--output', default=OUTPUT_PATH, help='输出 JSON 路径')
    args = parser.parse_args()

    if args.check:
        check_auth()
        return 0

    cookie = load_cookie()
    if args.date_from or args.date_to:
        if not args.date_from or not args.date_to:
            parser.error('指定日期区间时需同时提供 --from 与 --to')
        start = datetime.strptime(args.date_from, '%Y-%m-%d')
        end = datetime.strptime(args.date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    else:
        end = datetime.now()
        start = end - timedelta(days=max(args.days, 1))
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    log(f'拉取区间: {start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M}')

    raw_list = fetch_ticket_list(cookie, start_ms, end_ms)
    need_detail = not args.no_detail and any(
        not (x.get('template') and x.get('values')) for x in raw_list
    )
    log(f'列表共 {len(raw_list)} 条，{"拉取详情" if need_detail else "使用列表字段（跳过详情）"}…')

    records: list[dict] = []
    for i, item in enumerate(raw_list, 1):
        tid = item.get('id')
        if not tid:
            continue
        ticket = item
        if not args.no_detail and not (item.get('template') and item.get('values')):
            try:
                ticket = fetch_ticket_detail(int(tid), cookie)
            except Exception as e:
                log(f'  详情 {tid} 失败: {e}')
            time.sleep(0.08)
        rec = to_record(ticket)
        if rec:
            records.append(rec)
        if i % 20 == 0:
            log(f'  已处理 {i}/{len(raw_list)}')

    log(f'过滤后产研-学练机工单: {len(records)} 条')

    if args.replace:
        merged = records
    elif os.path.exists(args.output):
        with open(args.output, encoding='utf-8') as f:
            existing = json.load(f)
        merged = merge_records(existing, records)
        log(f'与现有 {len(existing)} 条合并 → {len(merged)} 条')
    else:
        merged = records

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    log(f'已写入 {args.output} ({os.path.getsize(args.output)/1024:.1f} KB)')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as e:
        log(f'错误: {e}')
        raise SystemExit(1)
