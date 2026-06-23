#!/usr/bin/env python3
"""
学练机发版平台 - 数据上传 API Server
Port 8890

Endpoints:
  POST /upload/feedback   - 上传用户反馈 CSV/XLSX
  POST /upload/tickets    - 上传用户工单 CSV/XLSX
  POST /upload/store      - 上传门店反馈 CSV/XLSX
  POST /upload/nps        - 上传 NPS CSV（month1 或 month3）
  POST /upload/nps/rebuild- 重新生成 nps_data.json

Token: zzw2026 (header: X-Upload-Token 或 query: token)
"""
import http.server
import json
import os
import csv
import io
import threading
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

WORKSPACE = os.path.expanduser('~/release-platform')
DATA_DIR = os.path.join(WORKSPACE, 'data')
NPS_JSON = os.path.join(WORKSPACE, 'nps_data.json')
UPLOAD_TOKEN = 'zzw2026'

os.makedirs(DATA_DIR, exist_ok=True)

def read_token(handler):
    token = handler.headers.get('X-Upload-Token', '')
    if not token:
        qs = parse_qs(urlparse(handler.path).query)
        token = qs.get('token', [''])[0]
    return token

def send_json(handler, code, data):
    body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Upload-Token')
    handler.end_headers()
    handler.wfile.write(body)

def parse_multipart(handler):
    """Parse multipart/form-data, returns dict {field_name: (filename, bytes)}"""
    import cgi
    content_type = handler.headers.get('Content-Type', '')
    content_length = int(handler.headers.get('Content-Length', 0))
    body = handler.rfile.read(content_length)
    
    # Use cgi.FieldStorage
    environ = {
        'REQUEST_METHOD': 'POST',
        'CONTENT_TYPE': content_type,
        'CONTENT_LENGTH': str(content_length),
    }
    fs = cgi.FieldStorage(
        fp=io.BytesIO(body),
        environ=environ,
        keep_blank_values=True
    )
    result = {}
    for key in fs.keys():
        item = fs[key]
        if hasattr(item, 'filename') and item.filename:
            result[key] = (item.filename, item.file.read())
        else:
            result[key] = (None, item.value)
    return result

def parse_csv_or_xlsx(filename, data):
    """Parse CSV or XLSX bytes, return list of lists"""
    filename_lower = (filename or '').lower()
    if filename_lower.endswith('.xlsx') or filename_lower.endswith('.xls'):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.active
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append([str(c) if c is not None else '' for c in row])
            return rows
        except ImportError:
            raise Exception('服务器未安装 openpyxl，请上传 CSV 格式')
    else:
        # CSV
        text = data.decode('utf-8-sig')
        reader = csv.reader(io.StringIO(text))
        return list(reader)

def rebuild_nps_json():
    """从 data/nps_month1.csv 和 data/nps_month3.csv 重新生成 nps_data.json"""
    import csv as csv_mod
    
    month1_file = os.path.join(DATA_DIR, 'nps_month1.csv')
    month3_file = os.path.join(DATA_DIR, 'nps_month3.csv')
    
    # 如果旧的 nps_data.json 存在，以它为基础
    base = {}
    if os.path.exists(NPS_JSON):
        with open(NPS_JSON, 'r', encoding='utf-8') as f:
            base = json.load(f)
    
    def load_nps_csv(filepath):
        """
        CSV 格式:
        行1: 标题行 (platform, model, channel, grade, date1, date2, ...)
        行2+: 数据 (platform_val, model_val, channel_val, grade_val, score1, score2, ...)
        返回: {key: [scores...], ...}, dates: [...]
        """
        if not os.path.exists(filepath):
            return {}, []
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            rows = list(csv_mod.reader(f))
        if len(rows) < 2:
            return {}, []
        header = rows[0]
        dates = header[4:]  # 从第5列开始是日期
        data_map = {}
        for row in rows[1:]:
            if len(row) < 4:
                continue
            p, m, c, g = row[0], row[1], row[2], row[3]
            key = f'{p}|{m}|{c}|{g}'
            scores = []
            for v in row[4:]:
                try:
                    scores.append(float(v) if v.strip() else None)
                except ValueError:
                    scores.append(None)
            data_map[key] = scores
        return data_map, dates
    
    m1_data, m1_dates = load_nps_csv(month1_file)
    m3_data, m3_dates = load_nps_csv(month3_file)
    
    # dates 以 month1 为准，如果没有则用 month3
    dates = m1_dates if m1_dates else m3_dates
    
    # 合并所有 keys 以构建下拉选项
    all_keys = set(m1_data.keys()) | set(m3_data.keys())
    platforms = set()
    models = set()
    channels = set()
    grades = set()
    for key in all_keys:
        parts = key.split('|')
        if len(parts) == 4:
            platforms.add(parts[0])
            models.add(parts[1])
            channels.add(parts[2])
            grades.add(parts[3])
    
    # 如果没新数据，保留旧的
    if not all_keys and base:
        return base
    
    # 保留旧 base 的选项（合并）
    if base.get('platforms'):
        platforms |= set(base['platforms'])
    if base.get('models'):
        models |= set(base['models'])
    if base.get('channels'):
        channels |= set(base['channels'])
    if base.get('grades'):
        grades |= set(base['grades'])
    
    # 确保"全部"在首位
    def sort_with_all(s):
        lst = sorted(s)
        if '全部' in lst:
            lst.remove('全部')
            lst.insert(0, '全部')
        return lst
    
    nps_out = {
        'dates': dates if dates else (base.get('dates', [])),
        'platforms': sort_with_all(platforms) if platforms else base.get('platforms', ['全部']),
        'models': sort_with_all(models) if models else base.get('models', ['全部']),
        'channels': sort_with_all(channels) if channels else base.get('channels', ['线上']),
        'grades': sort_with_all(grades) if grades else base.get('grades', ['小学']),
        'month1': m1_data if m1_data else base.get('month1', {}),
        'month3': m3_data if m3_data else base.get('month3', {}),
    }
    
    with open(NPS_JSON, 'w', encoding='utf-8') as f:
        json.dump(nps_out, f, ensure_ascii=False, indent=2)
    
    return nps_out


class UploadHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f'[{ts}] {format % args}')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Upload-Token')
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/health':
            send_json(self, 200, {'status': 'ok', 'time': datetime.now().isoformat()})
        elif path == '/api/data-status':
            files = {
                'releases': os.path.exists(os.path.join(DATA_DIR, 'releases.json')),
                'tickets': os.path.exists(os.path.join(DATA_DIR, 'tickets.json')),
                'feedback': os.path.exists(os.path.join(DATA_DIR, 'feedback.json')),
                'store': os.path.exists(os.path.join(DATA_DIR, 'store.json')),
                'nps_month1': os.path.exists(os.path.join(DATA_DIR, 'nps_month1.csv')),
                'nps_month3': os.path.exists(os.path.join(DATA_DIR, 'nps_month3.csv')),
                'nps_json': os.path.exists(NPS_JSON),
            }
            mtimes = {}
            for k, exists in files.items():
                if exists:
                    if k.startswith('nps_month'):
                        fp = os.path.join(DATA_DIR, f'{k}.csv')
                    elif k == 'nps_json':
                        fp = NPS_JSON
                    else:
                        fp = os.path.join(DATA_DIR, f'{k}.json')
                    mtimes[k] = datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%Y-%m-%d %H:%M:%S') if os.path.exists(fp) else None
            send_json(self, 200, {'files': files, 'mtimes': mtimes})
        elif path.startswith('/data/') and path.endswith('.json'):
            # Serve data files
            fname = os.path.basename(path)
            fpath = os.path.join(DATA_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath, 'rb') as f:
                    body = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
            else:
                send_json(self, 404, {'error': 'not found'})
        else:
            send_json(self, 404, {'error': 'not found'})

    def do_POST(self):
        path = urlparse(self.path).path
        
        # Token auth
        token = read_token(self)
        if token != UPLOAD_TOKEN:
            send_json(self, 401, {'error': '无效的 token，请提供正确的 X-Upload-Token'})
            return
        
        if path in ('/upload/tickets', '/upload/feedback', '/upload/store'):
            self._handle_user_data_upload(path)
        elif path == '/upload/nps':
            self._handle_nps_upload()
        elif path == '/upload/nps/rebuild':
            self._handle_nps_rebuild()
        else:
            send_json(self, 404, {'error': 'unknown endpoint'})

    def _handle_user_data_upload(self, path):
        """处理用户工单/反馈/门店反馈上传"""
        type_map = {
            '/upload/tickets': 'tickets',
            '/upload/feedback': 'feedback',
            '/upload/store': 'store',
        }
        data_type = type_map[path]
        
        try:
            fields = parse_multipart(self)
        except Exception as e:
            send_json(self, 400, {'error': f'解析请求失败: {str(e)}'})
            return
        
        if 'file' not in fields:
            send_json(self, 400, {'error': '缺少 file 字段'})
            return
        
        filename, file_bytes = fields['file']
        
        try:
            rows = parse_csv_or_xlsx(filename, file_bytes)
        except Exception as e:
            send_json(self, 400, {'error': f'解析文件失败: {str(e)}'})
            return
        
        if len(rows) < 2:
            send_json(self, 400, {'error': '文件内容为空或只有标题行'})
            return
        
        # Save as JSON (array of arrays, header + rows)
        out_path = os.path.join(DATA_DIR, f'{data_type}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False)
        
        send_json(self, 200, {
            'ok': True,
            'type': data_type,
            'rows': len(rows) - 1,
            'file': filename,
            'saved': out_path,
            'time': datetime.now().isoformat(),
        })

    def _handle_nps_upload(self):
        """处理 NPS CSV 上传"""
        try:
            fields = parse_multipart(self)
        except Exception as e:
            send_json(self, 400, {'error': f'解析请求失败: {str(e)}'})
            return
        
        results = []
        errors = []
        
        for nps_type in ('month1', 'month3'):
            if nps_type in fields:
                filename, file_bytes = fields[nps_type]
                try:
                    rows = parse_csv_or_xlsx(filename, file_bytes)
                    # Save as CSV
                    out_path = os.path.join(DATA_DIR, f'nps_{nps_type}.csv')
                    # Re-encode as CSV
                    buf = io.StringIO()
                    writer = csv.writer(buf)
                    for row in rows:
                        writer.writerow(row)
                    with open(out_path, 'w', encoding='utf-8') as f:
                        f.write(buf.getvalue())
                    results.append({'type': nps_type, 'rows': len(rows)-1, 'file': filename})
                except Exception as e:
                    errors.append({'type': nps_type, 'error': str(e)})
        
        if not results and not errors:
            send_json(self, 400, {'error': '请提供 month1 或 month3 字段'})
            return
        
        # Auto rebuild nps_data.json
        try:
            rebuild_nps_json()
            rebuilt = True
        except Exception as e:
            rebuilt = False
            errors.append({'type': 'rebuild', 'error': str(e)})
        
        send_json(self, 200, {
            'ok': len(errors) == 0,
            'uploaded': results,
            'errors': errors,
            'nps_rebuilt': rebuilt,
            'time': datetime.now().isoformat(),
        })

    def _handle_nps_rebuild(self):
        """手动触发重新生成 nps_data.json"""
        try:
            result = rebuild_nps_json()
            send_json(self, 200, {
                'ok': True,
                'dates_count': len(result.get('dates', [])),
                'keys_month1': len(result.get('month1', {})),
                'keys_month3': len(result.get('month3', {})),
                'time': datetime.now().isoformat(),
            })
        except Exception as e:
            send_json(self, 500, {'error': str(e)})


if __name__ == '__main__':
    PORT = 8890
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), UploadHandler)
    print(f'[upload_server] 启动在 127.0.0.1:{PORT}')
    print(f'[upload_server] 数据目录: {DATA_DIR}')
    print(f'[upload_server] NPS JSON: {NPS_JSON}')
    server.serve_forever()
