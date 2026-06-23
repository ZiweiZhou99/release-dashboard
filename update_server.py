#!/usr/bin/env python3
"""
学练机发版平台 - 更新 API Server
Port 8889
Endpoints:
  POST /api/update  -> 触发后台更新任务
  GET  /api/status  -> 返回当前任务状态
  GET  /api/log     -> 返回任务日志
"""
import http.server
import json
import os
import subprocess
import threading
import time
from datetime import datetime

WORKSPACE = os.path.expanduser('~/release-platform')
UPDATE_SCRIPT = os.path.join(WORKSPACE, 'update_data.py')
LOG_FILE = os.path.join(os.path.expanduser('~/release-platform/logs'), 'update.log')

state = {
    'status': 'idle',   # idle | running | done | error
    'started_at': None,
    'finished_at': None,
    'message': '待更新',
}
state_lock = threading.Lock()


def run_update():
    with state_lock:
        state['status'] = 'running'
        state['started_at'] = datetime.now().isoformat()
        state['finished_at'] = None
        state['message'] = '正在拉取数据...'

    with open(LOG_FILE, 'w') as log:
        proc = subprocess.Popen(
            ['python3', UPDATE_SCRIPT],
            stdout=log, stderr=subprocess.STDOUT
        )
        proc.wait()

    with open(LOG_FILE) as f:
        output = f.read()

    with state_lock:
        state['finished_at'] = datetime.now().isoformat()
        if proc.returncode == 0:
            state['status'] = 'done'
            state['message'] = '更新完成 ✅'
        else:
            state['status'] = 'error'
            state['message'] = '更新失败 ❌ 请查看日志'


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass  # suppress access logs

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/status':
            with state_lock:
                self.send_json(200, dict(state))
        elif self.path == '/api/log':
            try:
                with open(LOG_FILE) as f:
                    log = f.read()
            except FileNotFoundError:
                log = ''
            self.send_json(200, {'log': log})
        else:
            self.send_json(404, {'error': 'not found'})

    def do_POST(self):
        if self.path == '/api/update':
            with state_lock:
                if state['status'] == 'running':
                    self.send_json(409, {'error': '更新任务正在进行中，请稍候'})
                    return
            t = threading.Thread(target=run_update, daemon=True)
            t.start()
            self.send_json(200, {'ok': True, 'message': '更新任务已启动'})
        else:
            self.send_json(404, {'error': 'not found'})


if __name__ == '__main__':
    import socketserver
    server = socketserver.ThreadingTCPServer(('0.0.0.0', 8889), Handler)
    server.allow_reuse_address = True
    print('API server listening on :8889')
    server.serve_forever()
