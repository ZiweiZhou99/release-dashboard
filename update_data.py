#!/usr/bin/env python3
"""
学练机发版平台 - 数据更新脚本
1. 拉取 Confluence 发版数据
2. 拉取石墨产品功能数据
3. 合并 → 更新 release-dashboard.html
"""
import os, re, json, sys
from datetime import datetime
from html.parser import HTMLParser
from collections import defaultdict
import urllib.request, urllib.parse

WORKSPACE = '/home/ubuntu/release-platform'
HTML_PATH = os.path.join(WORKSPACE, 'release-dashboard.html')
DATA_DIR = os.path.join(WORKSPACE, 'data')
RELEASES_JSON = os.path.join(DATA_DIR, 'releases.json')
CONF_TOKEN_PATH = os.path.join(WORKSPACE, '.config/tokens/confluence.token')
CONF_COOKIE_PATH = os.path.join(WORKSPACE, '.config/tokens/confluence.cookie')
SHIMO_TOKEN_PATH = os.path.join(WORKSPACE, '.config/tokens/shimo.token')
SHIMO_USERID_PATH = os.path.join(WORKSPACE, '.config/tokens/shimo.userid')

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)

# ─── Confluence ───────────────────────────────────────────────
def load_conf_token():
    # 优先用 cookie，fallback 到 bearer token
    if os.path.exists(CONF_COOKIE_PATH):
        with open(CONF_COOKIE_PATH) as f:
            return ('cookie', f.read().strip())
    with open(CONF_TOKEN_PATH) as f:
        content = f.read().strip()
    if content.startswith('token='):
        return ('bearer', content.split('=', 1)[1].strip())
    return ('bearer', content)

def fetch_confluence(auth):
    log("拉取 Confluence 数据...")
    url = 'https://confluence.zhenguanyu.com/rest/api/content/917724867?expand=body.storage'
    auth_type, auth_val = auth if isinstance(auth, tuple) else ('bearer', auth)
    if auth_type == 'cookie':
        headers = {'Cookie': auth_val, 'Accept': 'application/json'}
    else:
        headers = {'Authorization': f'Bearer {auth_val}', 'Accept': 'application/json'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    html = data['body']['storage']['value']
    log(f"Confluence HTML: {len(html)} chars")
    return html

def parse_confluence_html(html, token=''):
    H_RE = re.compile(r'<h[123][^>]*>(.*?)</h[123]>', re.DOTALL | re.IGNORECASE)
    TABLE_RE = re.compile(r'<table\b', re.IGNORECASE)

    h_list = [(m.start(), re.sub(r'<[^>]+>', '', m.group(1)).strip()) for m in H_RE.finditer(html)]
    t_positions = [m.start() for m in TABLE_RE.finditer(html)]

    version_headers = []
    for h_pos, h_text in h_list:
        ver_m = re.search(r'2\.\d{2,3}(?:\.\d+)*(?:[^\s】，,<【]{0,20})?', h_text)
        if not ver_m: continue
        raw_ver = ver_m.group(0).strip()
        ver = re.sub(r'[（(][^）)]*[）)]', '', raw_ver).strip()

        ver_type = ''
        tp = re.search(r'[（(]([^）)]{2,20})[）)]', raw_ver)
        if tp: ver_type = tp.group(1)
        if not ver_type:
            if '固件+软件' in h_text: ver_type = '固件+软件'
            elif '固件' in h_text and '软件' not in h_text: ver_type = '固件'
            elif '软件' in h_text: ver_type = '软件'

        model_m = re.search(r'【机型】([^【\n]+)', h_text)
        model = model_m.group(1).strip().strip('，、 ') if model_m else ''

        date_m = re.search(r'【日期】(\d{8})', h_text)
        if date_m:
            d = date_m.group(1)
            date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        else:
            date_m2 = re.search(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', h_text)
            date = f"{date_m2.group(1)}-{int(date_m2.group(2)):02d}-{int(date_m2.group(3)):02d}" if date_m2 else ''

        next_t = next((tp for tp in t_positions if tp > h_pos), None)
        if next_t is None: continue

        version_headers.append({
            'version': ver, 'model': model, 'date': date,
            'type': ver_type, 'pm': '',
            'table_pos': next_t,
        })

    log(f"Version headers: {len(version_headers)}")

    class TParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables = []
            self.userkeys = set()  # collect all userkeys for batch lookup
            self._d = 0; self._rows = []; self._row = []
            self._cell = ''; self._in_cell = False
            self._task_bodies = []; self._in_tb = False; self._tb = ''
        def handle_starttag(self, tag, attrs):
            attrs_d = dict(attrs)
            if tag == 'table':
                self._d += 1
                if self._d == 1: self._rows = []
            if self._d == 1:
                if tag in ('td', 'th'): self._in_cell = True; self._cell = ''; self._task_bodies = []
                elif tag == 'ac:task-body' and self._in_cell: self._in_tb = True; self._tb = ''
                elif tag == 'ri:user' and self._in_cell:
                    ukey = attrs_d.get('ri:userkey', '')
                    if ukey:
                        self.userkeys.add(ukey)
                        placeholder = f'__UK_{ukey}__'
                        if self._in_tb: self._tb += placeholder + ' '
                        else: self._cell += placeholder + ' '
        def handle_endtag(self, tag):
            if tag == 'table':
                if self._d == 1 and self._rows: self.tables.append(list(self._rows))
                self._d -= 1
            if self._d == 1:
                if tag in ('td', 'th'):
                    val = ' '.join(self._task_bodies) if self._task_bodies else self._cell.strip()
                    self._row.append(val); self._in_cell = False
                elif tag == 'tr':
                    if self._row: self._rows.append(list(self._row)); self._row = []
                elif tag == 'ac:task-body':
                    self._in_tb = False
                    if self._tb.strip(): self._task_bodies.append(self._tb.strip())
        def handle_data(self, data):
            if self._in_cell:
                if self._in_tb: self._tb += data
                else: self._cell += data

    tp = TParser(); tp.feed(html)
    tables = tp.tables
    log(f"Tables parsed: {len(tables)}, userkeys: {len(tp.userkeys)}")

    # Batch resolve userkeys -> real names
    def resolve_userkeys(token, userkeys):
        mapping = {}
        for uk in userkeys:
            try:
                url = f'https://confluence.zhenguanyu.com/rest/api/user?key={urllib.parse.quote(uk)}'
                req = urllib.request.Request(url, headers={
                    'Authorization': f'Bearer {token}',
                    'Accept': 'application/json'
                })
                with urllib.request.urlopen(req, timeout=8) as r:
                    d = json.loads(r.read())
                mapping[uk] = d.get('displayName', uk)
            except Exception:
                mapping[uk] = uk
        return mapping

    userkey_map = resolve_userkeys(token, tp.userkeys)
    log(f"Resolved {len(userkey_map)} userkeys")

    def replace_userkeys(text, uk_map):
        for uk, name in uk_map.items():
            text = text.replace(f'__UK_{uk}__', name)
        # Clean up any remaining placeholders
        text = re.sub(r'__UK_[a-f0-9]+__', '', text)
        return text.strip()

    def is_header(row):
        t = ' '.join(row).lower()
        return sum(1 for k in ['功能', 'rd', 'qa', '研发', '测试', 'jira', '备注', '状态'] if k in t) >= 3

    def detect_cols(row):
        m = {}
        for i, c in enumerate(row):
            c = c.strip().lower()
            if any(k in c for k in ['功能', 'feature']): m['name'] = i
            elif c in ('rd', '研发', '开发'): m['rd'] = i
            elif c in ('qa', '测试', '品控'): m['qa'] = i
            elif any(k in c for k in ['jira', 'ticket']): m['jira'] = i
            elif any(k in c for k in ['备注', '说明', 'note']): m['note'] = i
            elif any(k in c for k in ['状态', 'status', '进度']): m['status'] = i
        return m

    def parse_status(t):
        for k in ['✅', '⏳', '❌']:
            if k in t: return k
        return '—'

    releases = []; seen = set()
    for vh in version_headers:
        ver = vh['version']
        vt = vh['type']
        if '固件' in vt and '软件' not in vt: continue
        if ver in seen: continue

        t_idx = next((i for i, tp in enumerate(t_positions) if tp == vh['table_pos']), None)
        if t_idx is None or t_idx >= len(tables): continue
        table = tables[t_idx]
        if not table or len(table) < 2: continue

        hi = next((i for i, r in enumerate(table[:5]) if is_header(r)), None)
        if hi is None: continue
        col_map = detect_cols(table[hi])
        if 'name' not in col_map: continue

        seen.add(ver)
        feats = []
        for row in table[hi + 1:]:
            if len(row) <= col_map['name']: continue
            name = row[col_map['name']].strip()
            if not name or is_header(row): continue
            if not re.search(r'[\u4e00-\u9fa5a-zA-Z]', name): continue
            def get(k): return row[col_map[k]].strip() if k in col_map and col_map[k] < len(row) else ''
            feats.append({
                'name': replace_userkeys(name, userkey_map),
                'rd': replace_userkeys(get('rd'), userkey_map),
                'qa': replace_userkeys(get('qa'), userkey_map),
                'note': replace_userkeys(get('note'), userkey_map),
                'status': parse_status(get('status')),
                'jira': re.findall(r'[A-Z]+-\d+', get('jira')),
            })
        if not feats: continue
        releases.append({
            'version': ver, 'model': vh['model'], 'date': vh['date'],
            'type': vt, 'pm': '', 'features': feats, 'shimo': None
        })

    releases.sort(key=lambda r: [int(p) for p in re.findall(r'\d+', r['version'])], reverse=True)
    log(f"Parsed {len(releases)} releases")
    return releases

# ─── 石墨 ─────────────────────────────────────────────────────
def load_shimo_token():
    # 支持两种格式：独立文件 or JSON
    with open(SHIMO_TOKEN_PATH) as f:
        raw = f.read().strip()
    try:
        data = json.loads(raw)
        token = data['token']
        user_id = data['user_id']
    except (json.JSONDecodeError, KeyError):
        # 独立文件格式
        token = raw
        with open(SHIMO_USERID_PATH) as f:
            user_id = f.read().strip()
    return token, user_id

def fetch_shimo(token, user_id):
    log("拉取石墨数据...")
    guid = 'AZlp79EvK4zQHR69'
    url = f'https://shimo.zhenguanyu.com/lizard-api/files/{guid}/export?type=text'
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {token}',
        'X-Shimo-User-Id': str(user_id),
        'User-Agent': 'Mozilla/5.0',
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode('utf-8', errors='replace')
        log(f"石墨原始: {len(raw)} chars")
        return raw
    except Exception as e:
        log(f"石墨 export 失败: {e}, 尝试备用接口...")
        url2 = f'https://shimo.zhenguanyu.com/lizard-api/files/{guid}/content'
        req2 = urllib.request.Request(url2, headers={
            'Authorization': f'Bearer {token}',
            'X-Shimo-User-Id': str(user_id),
        })
        with urllib.request.urlopen(req2, timeout=30) as r:
            data = json.loads(r.read())
        # content 接口返回 OT 格式: [[type, text_or_obj, attrs], ...]
        # 提取所有文本片段拼接成纯文本
        def extract_text(item):
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                return ''
            t = item[1]
            if isinstance(t, str):
                return t
            if isinstance(t, dict):
                # mention/embed等对象，取text字段
                return t.get('text', t.get('mention', {}).get('text', ''))
            return ''
        if isinstance(data, list):
            content = ''.join(extract_text(item) for item in data)
        elif isinstance(data, dict):
            content = data.get('content', data.get('text', str(data)))
        else:
            content = str(data)
        log(f"石墨备用 OT→text: {len(content)} chars")
        return content

def parse_shimo(text):
    date_pattern = re.compile(r'^(\d{4}\.\d{1,2}\.\d{1,2})\s*$', re.MULTILINE)
    date_matches = list(date_pattern.finditer(text))

    HARD_SKIP = re.compile(
        r'^(新版本发布节奏|学练机（版本号|覆盖设备：|升级节奏：|升级的设备型号|录制:|日期:|录制文件:|'
        r'示意图|图示|效果对比|使用演示视频|介绍视频|使用路径视频|活动路径|活动时间|活动信息|'
        r'完成条件|奖励：|主题：|·更新名称|·更新了什么|·关注点|·更新范围|日期: \d|录制: |'
        r'>查询用户|营销相关：|宣传建议：|展示建议：|售后/客服|涉及直播|'
        r'报告顶部|报告中部|报告底部|比如练|比如练得|练得好|练得差|比如我们有|目前竞品没有|'
        r'使用率在|不过多抬高|与平板|与行业|规划性承诺|持续更新适合|长期优化墨水屏|'
        r'课程功能页面的总集数|课程资源为空|《学霸笔记》|《中学教材全解》|教辅上线《|'
        r'年后会|截止\d{4}年\d|主要的宣传点)'
    )
    DETAIL_LABELS = (
        '涉及机型', '支持机型', '设计机型', '功能入口', '详细介绍', '涉及范围',
        '更新内容', '更新范围', '优化部分', '升级内容', '下线范围', '下线时间',
        '上线内容', '关注点', '特殊说明', '特殊情况', '支持学段', '支持年级',
        '本期更新', '优化目标', '优化目的', '注意', '功能概述', '使用流程', '关注',
    )
    SUB_LINE_START = re.compile(
        r'^(反馈|引导|已删除|图书删除后|注：|可以先|然后提交|'
        r'原学情诊断：|该试卷分析：|强调|呈现|同时|对比|指向|对异常|'
        r'截止\s*\d|其中|另外|后续|更多|每个|按照|目前|比如|如果|若|'
        r'营销相关|宣传建议|不过多|与平板|规划性|持续更新|长期优化|'
        r'课程功能|课程资源|和学习机|目前学练机|后续有规划)'
    )
    SUB_BULLET_RE = re.compile(
        r'^(强化|增加[^：]{0,6}[：（]|新增[^：]{0,3}[：（]|支持双击|增加桌面|'
        r'增加AI助手|增加语音|强化语音|新增排名|增加[^：]{0,8}$)'
    )
    EXTRA_SUB = re.compile(
        r'^(新旧版都更新：|其他版本：|年级：\d|新旧都更新：|特别说明：|覆盖设备：|升级节奏：)'
    )
    NOISE_NAME = re.compile(
        r'^(展示建议|宣传建议|售后|客服|课程页面|资源说明|规划性|持续更新适合|长期优化|'
        r'课程功能页面|课程资源为空|和学习机|不过多抬高|用户认为|与平板|与行业|'
        r'目前学练机|后续有规划|介绍PPT|截止\s*\d|升级时间：|与原学情诊断|'
        r'智慧是指|AI视频$|用户如何反馈|没有符合孩子|有了书本|本期上线：海尼曼|线上视频：|'
        r'图书删除后|已删除的书支持|支持书本阅读|教辅/试卷：支持|其他：支持|教材：支持|'
        r'科目：|场景：)'
    )
    JUNK_SENTENCE = re.compile(
        r'(优先宣传|宣传自研|用户认为.*残影|课程功能页的集数|切换年级与版本|部分多版本的课程|'
        r'正在逐步生产|敬请期待|学习机课程支持多种互动|互动资源相对|后续有规划|合适的资源会同步|'
        r'规划性承诺|不过多抬高|与平板对比|与行业|营销相关|宣传建议|展示建议)'
    )

    def is_feature_title(line):
        if not line or len(line) < 4 or len(line) > 42: return False
        if not re.search(r'[\u4e00-\u9fa5]{2,}', line): return False
        if re.match(r'^[\d.]', line): return False
        if line.startswith(('-', '—', '*', '【', '（', '>', '·', '「', '」', '注：')): return False
        if HARD_SKIP.match(line): return False
        if SUB_LINE_START.match(line): return False
        if line.startswith('http'): return False
        if line.rstrip().endswith(('：', ':')): return False
        if re.search(r'[，。]', line[:20]): return False
        if line.endswith('？'): return False
        return True

    def clean_url(s):
        return re.sub(r'https?://\S+', '', s).strip().rstrip('：:。，、 ')

    def clean_detail_text(text):
        parts = re.split(r'[；;]', text)
        clean = []
        for p in parts:
            p = p.strip()
            if p and not JUNK_SENTENCE.search(p) and len(p) > 3:
                if not re.match(r'^(入口：首页$|优先|宣传|展示|售后|与平板|规划性|持续更新|长期优化|'
                                r'课程功能页面|课程资源|和学习机|目前学练机|不过多|与行业|比如练|练得)', p):
                    clean.append(p)
        return '；'.join(clean)

    def parse_block(content):
        lines = [l.strip() for l in content.split('\n')]
        features = []
        cur_name = None
        cur_fields = {}
        cur_free = []

        def flush():
            nonlocal cur_name, cur_fields, cur_free
            if not cur_name: return
            detail_parts = []
            label_order = ['功能概述', '涉及范围', '支持学段', '支持年级', '更新内容', '升级内容',
                           '优化部分', '优化目标', '详细介绍', '下线范围', '下线时间',
                           '关注点', '关注', '使用流程', '特殊说明', '注意']
            for lbl in label_order:
                if lbl in cur_fields:
                    val = clean_url(' '.join(v for v in cur_fields[lbl] if v))
                    if val and len(val) > 2:
                        detail_parts.append({'label': lbl, 'text': val})
            clean_free = []
            for l in cur_free:
                cl = clean_url(l)
                if (cl and len(cl) > 5 and not HARD_SKIP.match(l) and
                        not l.startswith(('【', '·', '>', '*', '（', '注：')) and
                        not re.match(r'^(营销相关|宣传建议|展示建议|售后|与平板|规划性|持续更新|'
                                     r'长期优化|课程功能页面|课程资源|和学习机|目前学练机|不过多|与行业|比如练|练得)', l)):
                    clean_free.append(cl)
            if clean_free:
                detail_parts.append({'label': None, 'text': ' '.join(clean_free[:4])})
            features.append({
                'name': cur_name,
                'devices': cur_fields.get('devices', [''])[0],
                'entry': cur_fields.get('entry', [''])[0],
                'detail_parts': detail_parts,
            })
            cur_name = None; cur_fields.clear(); cur_free.clear()

        for line in lines:
            if not line: continue
            if re.match(r'^\d{4}\.\d{1,2}\.\d{1,2}$', line): continue
            if HARD_SKIP.match(line): continue
            if line in ('yu', '注：'): continue

            matched_label = None
            for lbl in DETAIL_LABELS:
                pat = lbl.rstrip('：:')
                if re.match(rf'^{re.escape(pat)}[：:]\s*', line) or line in (pat + '：', pat + ':'):
                    matched_label = pat; break

            if matched_label and cur_name:
                val = re.sub(r'^[^：:]+[：:]\s*', '', line).strip()
                val = clean_url(val)
                if matched_label in ('涉及机型', '支持机型', '设计机型'):
                    cur_fields['devices'] = [val]
                elif matched_label == '功能入口':
                    val = re.sub(r'\[([^\]]+)\]', r'\1', val)
                    cur_fields['entry'] = [val]
                elif matched_label in ('功能概述', '使用流程', '关注'):
                    cur_fields.setdefault(matched_label, []).append(val)
                else:
                    cur_fields.setdefault(matched_label, []).append(val)
                continue

            if cur_name and SUB_LINE_START.match(line) and (
                    '功能概述' in cur_fields or '使用流程' in cur_fields or '关注' in cur_fields):
                cl = clean_url(line)
                for lbl in ['使用流程', '功能概述', '关注']:
                    if lbl in cur_fields:
                        cur_fields[lbl].append(cl); break
                continue

            if is_feature_title(line):
                flush()
                cur_name = line
            elif cur_name:
                cur_free.append(line)
        flush()
        return features

    def merge_sub_items(features):
        result = []
        for f in features:
            is_sub = (
                EXTRA_SUB.match(f['name']) or
                (SUB_BULLET_RE.match(f['name']) and not f['devices']) or
                (re.match(r'^入口：', f['name']) and not f['devices']) or
                re.match(r'^(科目：|场景：|教材：|教辅/试卷：|其他：|用户如何反馈：)', f['name'])
            )
            if is_sub and result:
                prev = result[-1]
                text = f['name']
                for dp in f['detail_parts']:
                    if dp['text'] and len(dp['text']) > 3: text += '；' + dp['text']
                if re.match(r'^入口：', f['name']) and not prev['entry']:
                    prev['entry'] = f['name'][3:].strip()
                else:
                    added = False
                    for dp in prev['detail_parts']:
                        if dp['label'] in ('升级内容', '更新内容', '优化部分', None):
                            dp['text'] += '；' + text[:100]; added = True; break
                    if not added:
                        prev['detail_parts'].append({'label': '升级内容', 'text': text[:100]})
            else:
                result.append(f)
        return result

    def clean_details(features):
        result = []
        for f in features:
            if NOISE_NAME.match(f['name']): continue
            cleaned_parts = []
            for dp in f['detail_parts']:
                if dp['label'] is None:
                    new_text = clean_detail_text(dp['text'])
                    if new_text and len(new_text) > 5:
                        cleaned_parts.append({'label': None, 'text': new_text})
                else:
                    cleaned_parts.append(dp)
            f['detail_parts'] = cleaned_parts
            result.append(f)
        return result

    blocks = []
    for i, dm in enumerate(date_matches):
        start = dm.start()
        end = date_matches[i + 1].start() if i + 1 < len(date_matches) else len(text)
        content = text[start:end].strip()
        date_raw = dm.group(1)
        parts_d = date_raw.split('.')
        date_norm = f"{parts_d[0]}-{int(parts_d[1]):02d}-{int(parts_d[2]):02d}"
        versions = list(dict.fromkeys(re.findall(r'版本号[：:]\s*v?(2\.\d+[\.\d]*)', content)))
        feats = parse_block(content)
        feats = merge_sub_items(feats)
        feats = clean_details(feats)
        feats = [f for f in feats if re.search(r'[\u4e00-\u9fa5]{2,}', f['name'])]
        blocks.append({'date': date_norm, 'raw_date': date_raw, 'versions': versions, 'features': feats})

    log(f"Shimo blocks: {len(blocks)}, features: {sum(len(b['features']) for b in blocks)}")
    return blocks

# ─── Merge ────────────────────────────────────────────────────
def merge(releases, shimo_blocks):
    shimo_by_version = {}
    shimo_by_date = {}
    for block in shimo_blocks:
        for v in block['versions']:
            v_clean = v.strip().rstrip('.')
            if v_clean not in shimo_by_version:
                shimo_by_version[v_clean] = block
        shimo_by_date[block['date']] = block

    def find_shimo(r):
        v = r['version'].strip()
        m = shimo_by_version.get(v) or shimo_by_date.get(r['date'])
        if not m:
            major_minor = '.'.join(v.split('.')[:2])
            for sv, sb in shimo_by_version.items():
                if sv.startswith(major_minor): m = sb; break
        return m

    shimo_to_releases = defaultdict(list)
    for i, r in enumerate(releases):
        m = find_shimo(r)
        if m: shimo_to_releases[m['date']].append(i)
    shimo_winner = {d: max(idxs) for d, idxs in shimo_to_releases.items()}

    for i, r in enumerate(releases):
        m = find_shimo(r)
        r['shimo'] = m if (m and shimo_winner.get(m['date']) == i) else None

    matched = sum(1 for r in releases if r['shimo'])
    log(f"Merged: {matched}/{len(releases)} releases have shimo data")
    return releases

# ─── Update data files ────────────────────────────────────────
def update_releases_data(releases):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(RELEASES_JSON, 'w', encoding='utf-8') as f:
        json.dump(releases, f, ensure_ascii=False, indent=2)
    size = os.path.getsize(RELEASES_JSON) / 1024
    log(f"releases.json updated: {size:.1f} KB ({len(releases)} versions)")

# ─── Main ─────────────────────────────────────────────────────
def main():
    log("=== 开始更新 ===")

    # Confluence
    try:
        conf_auth = load_conf_token()
        conf_html = fetch_confluence(conf_auth)
        releases = parse_confluence_html(conf_html, conf_auth[1] if isinstance(conf_auth, tuple) else conf_auth)
        if not releases:
            log("ERROR: Confluence 解析结果为空，中止")
            sys.exit(1)
    except Exception as e:
        log(f"ERROR Confluence: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    # 石墨
    shimo_blocks = []
    try:
        shimo_token, shimo_uid = load_shimo_token()
        shimo_text = fetch_shimo(shimo_token, shimo_uid)
        shimo_blocks = parse_shimo(shimo_text)
    except Exception as e:
        log(f"WARNING 石墨拉取失败 ({e})，尝试使用缓存...")
        try:
            with open('/tmp/shimo_v6.json') as f:
                shimo_blocks = json.load(f)
            log("使用缓存石墨数据")
        except Exception:
            log("无缓存，跳过石墨数据")

    releases = merge(releases, shimo_blocks)
    update_releases_data(releases)
    log(f"=== 更新完成 ✅  共 {len(releases)} 个版本 ===")

if __name__ == '__main__':
    main()
