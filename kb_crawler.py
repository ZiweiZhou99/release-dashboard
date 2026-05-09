#!/usr/bin/env python3
"""
Confluence PRD Crawler for 学练机产品知识库
Crawls all pages under root page 122413970, skipping specified directories.
"""

import json
import time
import re
import os
import sys
from html.parser import HTMLParser
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import urllib.error
import base64

# Configuration
CONFLUENCE_BASE = "https://confluence.zhenguanyu.com"
ROOT_PAGE_ID = "122413970"
TOKEN_FILE = os.path.expanduser("~/.openclaw/workspace/.config/tokens/confluence.token")
OUTPUT_FILE = "/tmp/kb_pages.json"

# Skip these page IDs (subtrees to exclude)
SKIP_PAGE_IDS = {
    "434425641",  # 过期文档
    "141113249",  # 后台相关
    "325913540",  # 供应商对接
    "504743654",  # 内容更新
    "516460063",  # 墨水屏官网
}

class MLStripper(HTMLParser):
    """HTML tag stripper"""
    def __init__(self):
        super().__init__()
        self.reset()
        self.fed = []
        self.in_skip = 0
        
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.in_skip += 1
            
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.in_skip = max(0, self.in_skip - 1)
    
    def handle_data(self, d):
        if self.in_skip == 0:
            self.fed.append(d)
    
    def get_data(self):
        return ' '.join(self.fed)


def strip_html(html_content):
    """Strip HTML tags and return plain text"""
    if not html_content:
        return ""
    s = MLStripper()
    s.feed(html_content)
    text = s.get_data()
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove common wiki markup artifacts
    text = re.sub(r'\{[^}]+\}', '', text)
    return text


def read_token():
    """Read Confluence API token"""
    with open(TOKEN_FILE, 'r') as f:
        return f.read().strip()


def confluence_get(path, token, params=None):
    """Make a GET request to Confluence API"""
    url = f"{CONFLUENCE_BASE}/rest/api{path}"
    if params:
        url += "?" + urlencode(params)
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code} for {url}: {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return None


def get_page_content(page_id, token):
    """Get a single page with content"""
    result = confluence_get(
        f"/content/{page_id}",
        token,
        params={"expand": "body.storage,version,ancestors,space"}
    )
    return result


def get_children(page_id, token, start=0, limit=50):
    """Get children of a page"""
    result = confluence_get(
        f"/content/{page_id}/child/page",
        token,
        params={"start": start, "limit": limit, "expand": "version"}
    )
    return result


def build_title_path(ancestors, title):
    """Build breadcrumb path from ancestors"""
    parts = []
    for ancestor in ancestors:
        parts.append(ancestor.get('title', ''))
    parts.append(title)
    # Skip the first element (usually "Confluence" or space root)
    if len(parts) > 1:
        parts = parts[1:]  # Skip space root
    return " > ".join(parts)


def crawl_page(page_id, token, pages_dict, skip_ids, depth=0, since=None):
    """Recursively crawl a page and its children"""
    if page_id in skip_ids:
        print(f"  {'  '*depth}[SKIP] {page_id}")
        return
    
    if page_id in pages_dict:
        return  # Already processed
    
    # Get page content
    page = get_page_content(page_id, token)
    if not page:
        print(f"  {'  '*depth}[ERROR] Failed to get page {page_id}")
        return
    
    title = page.get('title', '')
    
    # Get ancestors for title path
    ancestors = page.get('ancestors', [])
    title_path = build_title_path(ancestors, title)
    parent_title = ancestors[-1].get('title', '') if ancestors else ''
    
    # Get content
    body = page.get('body', {}).get('storage', {}).get('value', '')
    content = strip_html(body)
    word_count = len(content)
    
    # Get last modified
    last_modified = page.get('version', {}).get('when', '')[:10] if page.get('version') else ''
    
    # 增量模式：跳过未修改的页面（但仍然递归其子页面）
    if since and last_modified and last_modified <= since:
        # 不加入 pages_dict，但继续遍历子页面
        pass
    else:
        page_data = {
            "id": page_id,
            "title": title,
            "url": f"{CONFLUENCE_BASE}/pages/viewpage.action?pageId={page_id}",
            "parent_title": parent_title,
            "title_path": title_path,
            "content": content,
            "word_count": word_count,
            "last_modified": last_modified
        }
        
        pages_dict[page_id] = page_data
        
        if word_count >= 50:
            print(f"  {'  '*depth}[PAGE] {title[:50]} ({word_count} chars)")
        else:
            print(f"  {'  '*depth}[EMPTY] {title[:50]}")
    
    time.sleep(0.1)  # Rate limiting
    
    # Get all children with pagination
    start = 0
    limit = 50
    while True:
        children_result = get_children(page_id, token, start=start, limit=limit)
        if not children_result:
            break
        
        children = children_result.get('results', [])
        if not children:
            break
        
        for child in children:
            child_id = child['id']
            if child_id not in skip_ids:
                crawl_page(child_id, token, pages_dict, skip_ids, depth + 1, since=since)
            else:
                print(f"  {'  '*(depth+1)}[SKIP] {child.get('title', child_id)}")
        
        # Check if there are more children
        total = children_result.get('size', 0)
        start += limit
        if start >= total or len(children) < limit:
            break
        
        time.sleep(0.05)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--since', help='只抓取该日期之后修改的页面 (YYYY-MM-DD)，用于增量更新')
    parser.add_argument('--merge', help='与已有 chunks.json 合并的目录路径', default=None)
    args = parser.parse_args()

    print("=== Confluence PRD Crawler ===")
    print(f"Root page: {ROOT_PAGE_ID}")
    print(f"Skip IDs: {SKIP_PAGE_IDS}")
    if args.since:
        print(f"增量模式: 只抓取 {args.since} 之后修改的页面")

    token = read_token()
    print(f"Token loaded: {token[:20]}...")

    pages_dict = {}

    print("\nStarting crawl...")
    crawl_page(ROOT_PAGE_ID, token, pages_dict, SKIP_PAGE_IDS, since=args.since)

    all_pages = list(pages_dict.values())
    substantial_pages = [p for p in all_pages if p['word_count'] >= 50]

    print(f"\n=== Crawl Complete ===")
    print(f"Total pages crawled: {len(all_pages)}")
    print(f"Substantial pages (>=50 chars): {len(substantial_pages)}")

    # 增量模式：与旧数据合并
    if args.since and args.merge:
        old_file = os.path.join(args.merge, '../kb_pages_old.json') if not args.merge.endswith('.json') else args.merge
        # 直接用 OUTPUT_FILE 里的旧数据合并
        if os.path.exists(OUTPUT_FILE):
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                old_pages = json.load(f)
            new_ids = {p['id'] for p in all_pages}
            merged = [p for p in old_pages if p['id'] not in new_ids] + all_pages
            print(f"合并旧数据: {len(old_pages)} 条 + 增量 {len(all_pages)} 条 = {len(merged)} 条")
            all_pages = merged

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_pages, f, ensure_ascii=False, indent=2)

    print(f"Saved to {OUTPUT_FILE}")
    return all_pages


if __name__ == "__main__":
    main()
