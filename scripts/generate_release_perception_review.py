#!/usr/bin/env python3
"""从 releases.json 生成「用户可感知发版项」确认清单。

用法:
  python3 scripts/generate_release_perception_review.py
  python3 scripts/generate_release_perception_review.py --months 6 --out data/release_perception_review.json
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
RELEASES_PATH = WORKSPACE / 'data' / 'releases.json'
DEFAULT_OUT = WORKSPACE / 'data' / 'release_perception_review.json'
DEFAULT_MD = WORKSPACE / 'docs' / 'release_perception_review.md'

SKIP_RE = re.compile(
    r'修复|bugfix|BugFix|BUGFIX|later ?bug|laterbug|JIRA:|MEGREZ-|crash|ANR|npe|oom|'
    r'内存泄|崩溃|日志|log|frog|lua|sdk|SDK|埋点|优化接口|接口字段|序列号|域名|ping|'
    r'缓存优化|下掉|删除日志|正常回测|研发自测|工厂版本|占用|合入|分支|回退|重新发布|'
    r'合规|耗时|轮询|异步调用|序列化|参数|通用参数|版本号|^\d[\d.]*$|\[JIRA',
    re.I,
)
BIZ_RE = re.compile(
    r'练习|学习|复习|考试|试卷|作文|阅读|绘本|听写|教材|同步|点读|书包|课程|分级|'
    r'AI|助手|精准|诊断|真题|计划|备考|寒假|暑假|删除|上新|外化|优化|功能|管控|家长|学生|年级'
)
INTERNAL_RE = re.compile(
    r'崩溃|crash|ANR|npe|oom|内存|适配\(|暂定|JIRA|MEGREZ-|bug|修复\d|问题修复|'
    r'回测|研发自测|合入|分支|合规|埋点|sdk|SDK|序列号|域名|工厂',
    re.I,
)
SHIMO_SKIP_RE = re.compile(r'^覆盖范围|^介绍PPT|^《|版本范围|机型[:：]|上线预告', re.I)


def is_biz_feat(name: str) -> bool:
    name = (name or '').strip()
    if len(name) < 3:
        return False
    if SKIP_RE.search(name):
        return False
    return bool(BIZ_RE.search(name))


def classify(name: str, source: str) -> str:
    """返回 suggested_yes | suggested_no | uncertain"""
    name = (name or '').strip()
    if not name or len(name) < 2:
        return 'suggested_no'
    if SHIMO_SKIP_RE.search(name):
        return 'suggested_no'
    if INTERNAL_RE.search(name) and not BIZ_RE.search(name):
        return 'suggested_no'
    if is_biz_feat(name):
        return 'suggested_yes'
    if source == 'shimo' and len(name) >= 4 and re.search(r'[\u4e00-\u9fa5]{2,}', name):
        return 'uncertain'
    if '修复' in name or '崩溃' in name:
        return 'suggested_no'
    return 'uncertain'


def shimo_product_features(release: dict) -> list[str]:
    shimo = release.get('shimo') or {}
    names: list[str] = []
    for feat in shimo.get('features') or []:
        name = (feat.get('name') or '').strip()
        if not name or SHIMO_SKIP_RE.search(name):
            continue
        if len(name) < 4 or not re.search(r'[\u4e00-\u9fa5]{2,}', name):
            continue
        if name not in names:
            names.append(name)
    return names


def collect_items(release: dict) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()

    def add(name: str, source: str, extra: dict | None = None):
        name = (name or '').strip()
        if not name:
            return
        key = f'{source}::{name}'
        if key in seen:
            return
        seen.add(key)
        items.append({
            'name': name,
            'source': source,
            'auto': classify(name, source),
            'user_perceivable': None,
            'note': '',
            **(extra or {}),
        })

    for feat in release.get('features') or []:
        add(feat.get('name') or '', 'confluence', {
            'rd': feat.get('rd') or '',
            'qa': feat.get('qa') or '',
            'status': feat.get('status') or '',
        })

    for name in shimo_product_features(release):
        add(name, 'shimo')

    order = {'suggested_yes': 0, 'uncertain': 1, 'suggested_no': 2}
    items.sort(key=lambda x: (order.get(x['auto'], 9), x['name']))
    return items


def build_review(months: int) -> dict:
    releases = json.loads(RELEASES_PATH.read_text(encoding='utf-8'))
    cutoff = datetime.now() - timedelta(days=months * 30)
    selected = []
    for r in releases:
        date_str = (r.get('date') or '')[:10]
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            continue
        if dt < cutoff:
            continue
        items = collect_items(r)
        stats = {
            'suggested_yes': sum(1 for i in items if i['auto'] == 'suggested_yes'),
            'uncertain': sum(1 for i in items if i['auto'] == 'uncertain'),
            'suggested_no': sum(1 for i in items if i['auto'] == 'suggested_no'),
        }
        selected.append({
            'version': r.get('version') or '',
            'date': date_str,
            'model': r.get('model') or '',
            'type': r.get('type') or '',
            'stats': stats,
            'items': items,
        })
    selected.sort(key=lambda x: x['date'], reverse=True)
    return {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'months': months,
        'cutoff_date': cutoff.strftime('%Y-%m-%d'),
        'release_count': len(selected),
        'releases': selected,
    }


def render_markdown(review: dict) -> str:
    lines = [
        '# 近半年发版 · 用户可感知确认清单',
        '',
        f'> 生成时间：{review["generated_at"]}  ',
        f'> 范围：{review["cutoff_date"]} 至今，共 **{review["release_count"]}** 个版本  ',
        '> 请在每行 `[ ]` 前打 `x` 表示「用户可感知」；留空表示暂不认；可在 JSON 里写 `note`',
        '',
        '**图例**：🟢 建议可感知 · 🟡 待确认 · ⚪ 建议内部/不可感知',
        '',
    ]
    total_yes = total_unc = total_no = 0
    for rel in review['releases']:
        s = rel['stats']
        total_yes += s['suggested_yes']
        total_unc += s['uncertain']
        total_no += s['suggested_no']
        lines += [
            f'## v{rel["version"]} · {rel["date"]} · {rel["model"]}',
            '',
            f'Confluence + 石墨合计 {len(rel["items"])} 项（🟢{s["suggested_yes"]} 🟡{s["uncertain"]} ⚪{s["suggested_no"]}）',
            '',
        ]
        for item in rel['items']:
            icon = {'suggested_yes': '🟢', 'uncertain': '🟡', 'suggested_no': '⚪'}.get(item['auto'], '·')
            src = '石墨' if item['source'] == 'shimo' else 'Conf'
            lines.append(f'- [ ] {icon} `{src}` {item["name"]}')
        lines.append('')

    lines += [
        '---',
        '',
        '## 汇总（自动初筛，待你确认）',
        '',
        f'| 类型 | 数量 |',
        f'|------|------|',
        f'| 🟢 建议用户可感知 | {total_yes} |',
        f'| 🟡 待你确认 | {total_unc} |',
        f'| ⚪ 建议内部/不可感知 | {total_no} |',
        '',
        '## 下一步',
        '',
        '1. 勾选确认后，把 `data/release_perception_review.json` 里对应项的 `user_perceivable` 改为 `true`/`false`',
        '2. 再运行关联脚本（待建）召回用户工单/反馈',
        '3. 生成触达清单与向上汇报稿',
        '',
    ]
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--months', type=int, default=6)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--md', type=Path, default=DEFAULT_MD)
    args = parser.parse_args()

    review = build_review(args.months)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
    args.md.write_text(render_markdown(review), encoding='utf-8')

    total_items = sum(len(r['items']) for r in review['releases'])
    print(f'版本: {review["release_count"]}  发版项: {total_items}')
    print(f'JSON: {args.out}')
    print(f'Markdown: {args.md}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
