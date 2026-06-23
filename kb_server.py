#!/usr/bin/env python3
"""
Knowledge Base Q&A Server for 学练机产品知识库
Flask app on port 8890 with BM25 retrieval + Gemini generation
"""

import json
import pickle
import os
import sys
import time
import re
from datetime import datetime
from flask import Flask, request, Response, jsonify
import jieba
from rank_bm25 import BM25Okapi

# Configuration
KB_DIR = os.path.join(os.path.dirname(__file__), "kb")
CHUNKS_FILE = os.path.join(KB_DIR, "chunks.json")
INDEX_FILE = os.path.join(KB_DIR, "bm25_index.pkl")
META_FILE = os.path.join(KB_DIR, "meta.json")

GEMINI_API_KEY = "AIzaSyAbKR4kIFJjGyinqfAMYe2ezqmNdf6Vb0w"
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:streamGenerateContent?key={GEMINI_API_KEY}&alt=sse"

TOP_K_RETRIEVE = 20
TOP_K_FINAL = 5

app = Flask(__name__)

# Global state
chunks = []
bm25 = None
chunk_ids = []
meta = {}


def load_index():
    """Load BM25 index and chunks"""
    global chunks, bm25, chunk_ids, meta
    
    print("Loading chunks...")
    with open(CHUNKS_FILE, 'r', encoding='utf-8') as f:
        chunks = json.load(f)
    print(f"Loaded {len(chunks)} chunks")
    
    print("Loading BM25 index...")
    with open(INDEX_FILE, 'rb') as f:
        index_data = pickle.load(f)
    bm25 = index_data['bm25']
    chunk_ids = index_data['chunk_ids']
    print("BM25 index loaded")
    
    if os.path.exists(META_FILE):
        with open(META_FILE, 'r', encoding='utf-8') as f:
            meta = json.load(f)
    
    print("Index ready!")


def retrieve_chunks(question, top_k=TOP_K_FINAL):
    """Retrieve relevant chunks using BM25 + title path boost"""
    # Tokenize query
    query_tokens = list(jieba.cut(question))
    query_tokens = [t for t in query_tokens if len(t.strip()) > 1]
    
    if not query_tokens:
        return []
    
    # BM25 retrieval - get top 20
    scores = bm25.get_scores(query_tokens)
    
    # Apply title path boost
    for i, chunk in enumerate(chunks):
        title_path = chunk.get('title_path', '')
        title = chunk.get('title', '')
        # Check if any query token appears in title_path or title
        for token in query_tokens:
            if token in title_path or token in title:
                scores[i] *= 1.5
                break
    
    # Get top K indices
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    
    # Filter out zero-score results
    results = []
    for idx in top_indices:
        if scores[idx] > 0:
            results.append({
                'chunk': chunks[idx],
                'score': float(scores[idx])
            })
    
    return results[:top_k]


def build_prompt(question, retrieved_chunks, history=None):
    """Build prompt for Gemini"""
    # Format retrieved chunks
    refs = []
    for i, item in enumerate(retrieved_chunks, 1):
        chunk = item['chunk']
        refs.append(f"""### 参考{i}：{chunk['title_path']}
{chunk['content'][:800]}
来源：{chunk['url']}""")
    
    refs_text = "\n\n".join(refs)
    
    # Build conversation history
    history_text = ""
    if history:
        for turn in history[-3:]:  # Last 3 turns
            role = turn.get('role', 'user')
            content = turn.get('content', '')
            if role == 'user':
                history_text += f"\n用户：{content}"
            else:
                history_text += f"\n助手：{content}"
    
    prompt = f"""你是学练机产品助手，帮助客服和营销人员快速了解产品功能边界。

## 参考资料（来自PRD文档）

{refs_text}

{f"## 对话历史{history_text}" if history_text else ""}

## 用户问题
{question}

## 回答要求
1. 只基于上方参考资料回答，不要编造
2. 如果资料中没有明确答案，说"PRD中暂无明确说明，建议查阅完整文档"
3. 涉及机型时明确区分 S6/S2/E1/S1/A1
4. 回答简洁直接，100-200字，客服可直接使用
5. 末尾附参考来源（文档标题，不需要URL）

请直接给出回答："""
    
    return prompt


def stream_gemini(prompt):
    """Stream response from Gemini API"""
    import urllib.request
    import urllib.error
    
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 1024,
        }
    }).encode('utf-8')
    
    headers = {
        "Content-Type": "application/json",
    }
    
    req = urllib.request.Request(
        GEMINI_API_URL,
        data=payload,
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            buffer = b""
            for line in resp:
                line = line.rstrip(b'\n')
                if line.startswith(b'data: '):
                    data_str = line[6:].decode('utf-8')
                    if data_str == '[DONE]':
                        break
                    try:
                        data = json.loads(data_str)
                        candidates = data.get('candidates', [])
                        if candidates:
                            content = candidates[0].get('content', {})
                            parts = content.get('parts', [])
                            for part in parts:
                                text = part.get('text', '')
                                if text:
                                    yield text
                    except json.JSONDecodeError:
                        pass
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        yield f"\n[Error: {e.code} - {error_body[:200]}]"
    except Exception as e:
        yield f"\n[Error: {str(e)}]"


@app.route('/api/ask', methods=['POST'])
def ask():
    """Main Q&A endpoint with streaming response"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    
    question = data.get('question', '').strip()
    history = data.get('history', [])
    
    if not question:
        return jsonify({"error": "Question is required"}), 400
    
    def generate():
        try:
            # Retrieve relevant chunks
            retrieved = retrieve_chunks(question, top_k=TOP_K_FINAL)
            
            if not retrieved:
                yield f"data: {json.dumps({'type': 'chunk', 'content': 'PRD中暂无相关内容，建议查阅完整文档。'})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return
            
            # Build prompt
            prompt = build_prompt(question, retrieved, history)
            
            # Stream Gemini response
            for text_chunk in stream_gemini(prompt):
                yield f"data: {json.dumps({'type': 'chunk', 'content': text_chunk})}\n\n"
            
            # Send sources
            sources = []
            seen_urls = set()
            for item in retrieved:
                chunk = item['chunk']
                url = chunk['url']
                if url not in seen_urls:
                    sources.append({
                        "title": chunk['title'],
                        "url": url,
                        "title_path": chunk.get('title_path', chunk['title'])
                    })
                    seen_urls.add(url)
            
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
    
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
        }
    )


@app.route('/api/ask', methods=['OPTIONS'])
def ask_options():
    return Response('', headers={
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    })


@app.route('/api/status', methods=['GET'])
def status():
    """Return index status"""
    return jsonify({
        "status": "ok",
        "total_chunks": len(chunks),
        "total_pages": meta.get("total_pages", 0),
        "last_updated": meta.get("last_updated", "未知"),
        "created_at": meta.get("created_at", ""),
    })


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


if __name__ == '__main__':
    if not os.path.exists(CHUNKS_FILE) or not os.path.exists(INDEX_FILE):
        print(f"ERROR: Index files not found in {KB_DIR}")
        print("Please run kb_indexer.py first to build the index.")
        sys.exit(1)
    
    load_index()
    print("Starting KB server on port 8890...")
    app.run(host='0.0.0.0', port=8890, debug=False, threaded=True)
