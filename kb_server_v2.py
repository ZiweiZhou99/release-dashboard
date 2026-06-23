#!/usr/bin/env python3
"""
学练机产品知识库问答服务 v2
调用 OpenClaw 内置 Claude，无需外部 API Key
"""

import json
import math
import re
import pickle
import os
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import defaultdict

KB_DIR = os.path.expanduser("~/release-platform/kb")
PORT = 8888
OPENCLAW_URL = "http://127.0.0.1:18789/v1/chat/completions"
OPENCLAW_TOKEN = "a5002cf6e6a59404137b6aacd2cfdcbd45750d0e47e6bf65"
TOP_K = 5

# ─── 加载知识库 ─────────────────────────────────────────────
print("Loading chunks...")
with open(os.path.join(KB_DIR, "chunks.json")) as f:
    chunks = json.load(f)
with open(os.path.join(KB_DIR, "meta.json")) as f:
    meta = json.load(f)
print(f"Loaded {len(chunks)} chunks")

# ─── 简单中文分词（不依赖 jieba）──────────────────────────────
def tokenize(text):
    if not text:
        return []
    tokens = set()
    clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', ' ', text)
    # 2-gram / 3-gram 中文
    for i in range(len(clean) - 1):
        c = clean[i]
        if '\u4e00' <= c <= '\u9fa5':
            tokens.add(clean[i:i+2])
            if i + 2 < len(clean):
                tokens.add(clean[i:i+3])
    # 英文/数字
    for w in clean.split():
        if len(w) > 1:
            tokens.add(w.lower())
    return list(tokens)

# ─── 构建内存 BM25 索引 ────────────────────────────────────
print("Building in-memory BM25 index...")
k1, b_param = 1.5, 0.75
N = len(chunks)
total_len = sum(len((c.get("content") or "")) for c in chunks)
avgdl = total_len / N if N else 1

inverted = defaultdict(list)
doc_lengths = []

for i, chunk in enumerate(chunks):
    text = (chunk.get("title_path") or "") + " " + \
           (chunk.get("title") or "") + " " + \
           (chunk.get("content") or "")
    tokens = tokenize(text)
    doc_lengths.append(len(tokens))
    tf = defaultdict(int)
    for t in tokens:
        tf[t] += 1
    for term, freq in tf.items():
        inverted[term].append((i, freq))

print(f"Index built: {len(inverted)} unique terms")

def bm25_search(query, top_k=20):
    q_tokens = tokenize(query)
    scores = [0.0] * N
    for term in q_tokens:
        postings = inverted.get(term, [])
        if not postings:
            continue
        df = len(postings)
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
        for idx, tf in postings:
            dl = doc_lengths[idx]
            norm = k1 * (1 - b_param + b_param * dl / avgdl)
            scores[idx] += idf * (tf * (k1 + 1)) / (tf + norm)
    # 标题路径加权
    for i, score in enumerate(scores):
        if score > 0:
            title_path = (chunks[i].get("title_path") or "") + (chunks[i].get("title") or "")
            for term in q_tokens:
                if term in title_path:
                    scores[i] *= 1.5
                    break
    indexed = sorted(enumerate(scores), key=lambda x: -x[1])
    return [{"chunk": chunks[i], "score": s} for i, s in indexed[:top_k] if s > 0]

# ─── Prompt 构建 ────────────────────────────────────────────
def build_prompt(question, retrieved):
    refs = "\n\n".join(
        f"【参考{i+1}】{r['chunk'].get('title_path') or r['chunk'].get('title','')}\n"
        f"{(r['chunk'].get('content') or '')[:600]}"
        for i, r in enumerate(retrieved)
    )
    return f"""你是学练机产品助手，帮助客服和营销人员快速了解产品功能边界。

## 参考资料（来自PRD文档）
{refs}

## 用户问题
{question}

## 回答要求
1. 只基于上方参考资料回答，不要编造
2. 如果资料中没有明确答案，说"PRD中暂无明确说明，建议查阅完整文档"
3. 涉及机型时明确区分 S6/S2/E1/S1/A1
4. 回答简洁直接，100-200字，客服可直接使用
5. 末尾附参考来源（文档标题）

请直接给出回答："""

# ─── 调用 OpenClaw Claude（流式）────────────────────────────
def stream_openclaw(prompt):
    payload = json.dumps({
        "model": "openclaw:main",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "stream": True,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
    }
    req = urllib.request.Request(OPENCLAW_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            for line in resp:
                line = line.rstrip(b"\n")
                if line.startswith(b"data: "):
                    data_str = line[6:].decode("utf-8")
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = (data.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    except json.JSONDecodeError:
                        pass
    except urllib.error.HTTPError as e:
        yield f"\n[Error: {e.code} - {e.read().decode()[:200]}]"
    except Exception as e:
        yield f"\n[Error: {str(e)}]"

# ─── HTTP Handler ──────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默日志

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        import os, mimetypes
        if self.path == "/api/status":
            body = json.dumps({
                "status": "ok",
                "total_chunks": len(chunks),
                "total_pages": meta.get("total_pages", len(chunks)),
                "last_updated": meta.get("last_updated", meta.get("created_at", "")),
                "model": "openclaw:main (Claude)",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body)
        else:
            # 静态文件服务
            path = self.path.split("?")[0]
            if path == "/": path = "/index.html"
            file_path = os.path.join("/home/ubuntu/release-platform", path.lstrip("/"))
            if os.path.isfile(file_path):
                mime, _ = mimetypes.guess_type(file_path)
                with open(file_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()

    def do_POST(self):
        if self.path != "/api/ask":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            question = data.get("question", "").strip()
        except Exception:
            self.send_response(400)
            self.end_headers()
            return
        if not question:
            self.send_response(400)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_cors()
        self.end_headers()

        def write_event(obj):
            line = f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()

        try:
            retrieved = bm25_search(question, top_k=TOP_K)
            if not retrieved:
                write_event({"type": "chunk", "content": "PRD中暂无相关内容，建议查阅完整文档。"})
            else:
                prompt = build_prompt(question, retrieved)
                for text in stream_openclaw(prompt):
                    write_event({"type": "chunk", "content": text})
                sources = []
                seen = set()
                for r in retrieved:
                    url = r["chunk"].get("url", "")
                    if url not in seen:
                        seen.add(url)
                        sources.append({
                            "title": r["chunk"].get("title", ""),
                            "url": url,
                            "title_path": r["chunk"].get("title_path") or r["chunk"].get("title", ""),
                        })
                write_event({"type": "sources", "sources": sources})
        except Exception as e:
            write_event({"type": "chunk", "content": f"[Error: {e}]"})

        write_event({"type": "done"})

# ─── 启动 ────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Starting KB server (OpenClaw Claude) on port {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
