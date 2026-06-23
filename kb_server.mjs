/**
 * 学练机产品知识库问答服务
 * Node.js 版本，调用 OpenClaw 内置 Claude，无需外部 API Key
 */

import http from 'http';
import fs from 'fs';
import path from 'path';
import { createRequire } from 'module';

const KB_DIR = '/home/ubuntu/release-platform/kb';
const PORT = 8891;
const OPENCLAW_URL = 'http://127.0.0.1:18789/v1/chat/completions';
const OPENCLAW_TOKEN = 'a5002cf6e6a59404137b6aacd2cfdcbd45750d0e47e6bf65';
const TOP_K = 5;

// ─── 加载知识库 ────────────────────────────────────────
console.log('Loading chunks...');
const chunks = JSON.parse(fs.readFileSync(path.join(KB_DIR, 'chunks.json'), 'utf-8'));
const meta = JSON.parse(fs.readFileSync(path.join(KB_DIR, 'meta.json'), 'utf-8'));
console.log(`Loaded ${chunks.length} chunks`);

// ─── 简单 BM25 实现（JS 版，不依赖 Python pickle）────────
function tokenize(text) {
  // 简单中文分词：按字符 n-gram + 标点分割
  if (!text) return [];
  const tokens = new Set();
  const clean = text.replace(/[^\u4e00-\u9fa5a-zA-Z0-9]/g, ' ');
  // 2-gram 和 3-gram 中文
  for (let i = 0; i < clean.length - 1; i++) {
    const c = clean[i];
    if (/[\u4e00-\u9fa5]/.test(c)) {
      if (i + 1 < clean.length) tokens.add(clean.slice(i, i + 2));
      if (i + 2 < clean.length) tokens.add(clean.slice(i, i + 3));
    }
  }
  // 英文/数字词
  clean.split(/\s+/).forEach(w => { if (w.length > 1) tokens.add(w.toLowerCase()); });
  return [...tokens];
}

// 构建倒排索引（内存 BM25）
console.log('Building in-memory index...');
const k1 = 1.5, b = 0.75;
const N = chunks.length;
const avgdl = chunks.reduce((s, c) => s + (c.content || '').length, 0) / N;

// 倒排索引: term -> [{idx, tf}]
const invertedIndex = new Map();
const docLengths = [];

for (let i = 0; i < chunks.length; i++) {
  const chunk = chunks[i];
  const text = (chunk.title_path || '') + ' ' + (chunk.title || '') + ' ' + (chunk.content || '');
  const tokens = tokenize(text);
  docLengths.push(tokens.length);
  
  const tf = new Map();
  for (const t of tokens) {
    tf.set(t, (tf.get(t) || 0) + 1);
  }
  for (const [term, freq] of tf) {
    if (!invertedIndex.has(term)) invertedIndex.set(term, []);
    invertedIndex.get(term).push({ idx: i, tf: freq });
  }
}

console.log(`Index built: ${invertedIndex.size} unique terms`);

function bm25Search(query, topK = 20) {
  const qTokens = tokenize(query);
  const scores = new Float64Array(N);
  
  for (const term of qTokens) {
    const postings = invertedIndex.get(term);
    if (!postings) continue;
    const df = postings.length;
    const idf = Math.log((N - df + 0.5) / (df + 0.5) + 1);
    for (const { idx, tf } of postings) {
      const dl = docLengths[idx];
      const norm = k1 * (1 - b + b * dl / avgdl);
      scores[idx] += idf * (tf * (k1 + 1)) / (tf + norm);
    }
  }
  
  // 标题路径匹配加权
  for (let i = 0; i < N; i++) {
    if (scores[i] > 0) {
      const titlePath = (chunks[i].title_path || '') + (chunks[i].title || '');
      for (const term of qTokens) {
        if (titlePath.includes(term)) {
          scores[i] *= 1.5;
          break;
        }
      }
    }
  }
  
  // 取 topK
  const indexed = Array.from(scores.entries())
    .filter(([, s]) => s > 0)
    .sort(([, a], [, b]) => b - a)
    .slice(0, topK);
  
  return indexed.map(([idx, score]) => ({ chunk: chunks[idx], score }));
}

// ─── Prompt 构建 ──────────────────────────────────────
function buildPrompt(question, retrieved) {
  const refs = retrieved.map((r, i) => {
    const c = r.chunk;
    return `【参考${i + 1}】${c.title_path || c.title}\n${(c.content || '').slice(0, 600)}`;
  }).join('\n\n');

  return `你是学练机产品助手，帮助客服和营销人员快速了解产品功能边界。

## 参考资料（来自PRD文档）
${refs}

## 用户问题
${question}

## 回答要求
1. 只基于上方参考资料回答，不要编造
2. 如果资料中没有明确答案，说"PRD中暂无明确说明，建议查阅完整文档"
3. 涉及机型时明确区分 S6/S2/E1/S1/A1
4. 回答简洁直接，100-200字，客服可直接使用
5. 末尾附参考来源（文档标题，无需链接）

请直接给出回答：`;
}

// ─── 调用 OpenClaw Claude（流式）────────────────────────
async function* streamClaude(prompt) {
  const body = JSON.stringify({
    model: 'openclaw:main',
    messages: [{ role: 'user', content: prompt }],
    max_tokens: 1024,
    stream: true,
  });

  const url = new URL(OPENCLAW_URL);
  const options = {
    hostname: url.hostname,
    port: url.port,
    path: url.pathname,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${OPENCLAW_TOKEN}`,
      'Content-Length': Buffer.byteLength(body),
    },
  };

  yield* await new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      resolve((async function* () {
        let buf = '';
        for await (const chunk of res) {
          buf += chunk.toString();
          const lines = buf.split('\n');
          buf = lines.pop();
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6).trim();
              if (data === '[DONE]') return;
              try {
                const json = JSON.parse(data);
                const delta = json.choices?.[0]?.delta?.content;
                if (delta) yield delta;
              } catch {}
            }
          }
        }
      })());
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// ─── HTTP Server ──────────────────────────────────────
const server = http.createServer(async (req, res) => {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  const url = new URL(req.url, `http://localhost:${PORT}`);

  // GET /api/status
  if (req.method === 'GET' && url.pathname === '/api/status') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      status: 'ok',
      total_chunks: chunks.length,
      total_pages: meta.total_pages || chunks.length,
      last_updated: meta.last_updated || meta.created_at,
      model: 'openclaw:main (Claude)',
    }));
    return;
  }

  // POST /api/ask
  if (req.method === 'POST' && url.pathname === '/api/ask') {
    let body = '';
    req.on('data', d => body += d);
    req.on('end', async () => {
      let question;
      try {
        question = JSON.parse(body).question?.trim();
      } catch {
        res.writeHead(400); res.end('Invalid JSON'); return;
      }
      if (!question) { res.writeHead(400); res.end('question required'); return; }

      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      });

      try {
        const retrieved = bm25Search(question, TOP_K);
        if (!retrieved.length) {
          res.write(`data: ${JSON.stringify({ type: 'chunk', content: 'PRD中暂无相关内容，建议查阅完整文档。' })}\n\n`);
        } else {
          const prompt = buildPrompt(question, retrieved);
          for await (const text of streamClaude(prompt)) {
            res.write(`data: ${JSON.stringify({ type: 'chunk', content: text })}\n\n`);
          }
          // 来源
          const sources = retrieved.map(r => ({
            title: r.chunk.title,
            url: r.chunk.url,
            title_path: r.chunk.title_path || r.chunk.title,
          }));
          res.write(`data: ${JSON.stringify({ type: 'sources', sources })}\n\n`);
        }
      } catch (e) {
        res.write(`data: ${JSON.stringify({ type: 'chunk', content: `[Error: ${e.message}]` })}\n\n`);
      }
      res.write(`data: ${JSON.stringify({ type: 'done' })}\n\n`);
      res.end();
    });
    return;
  }

  res.writeHead(404); res.end('Not found');
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`KB server (Claude) running on port ${PORT}`);
});
