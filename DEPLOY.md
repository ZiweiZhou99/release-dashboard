# 发版管理平台部署说明

## 架构

| 组件 | 端口 | 路径 | 说明 |
|------|------|------|------|
| Nginx 静态页 | 443 | `/release-dashboard.html` | 主页面 |
| `kb_server_v2.py` | 8888 | `/kb-api/` | 知识库问答 API |
| `update_server.py` | 8889 | `/release-api/` | 发版数据更新 API |
| `upload_server.py` | 8890 | `/upload-api/` | 工单/反馈/NPS 上传、闭环确认保存 |

服务器目录：`/home/ubuntu/release-platform/`

## 部署步骤

```bash
# 1. 拉取代码
cd /home/ubuntu/release-platform
git pull origin master

# 2. 安装 systemd 服务（首次）
sudo cp deploy/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now release-http release-api upload_server

# 3. 同步 data/*.json（首次或数据更新后）
# 前端从 /upload-api/data/*.json 加载，部署时务必带上 data 目录
# 用户声音闭环还需 voice_closure_ledger.json / voice_closure_links.json / voice_closure_state.json
python3 scripts/export_feishu_voice_closure.py --json-only --json-out --ledger <台账CSV路径>
python3 kb_crawler.py
python3 kb_indexer.py

# 4. 确认服务状态
systemctl status release-http release-api upload_server
```

## 文件说明

- `release-dashboard.html` — 线上主页面（与 `index.html` 内容一致）
- `kb-assistant.html` — 知识库助手独立页（内网限制）
- `update_data.py` — Confluence/石墨数据拉取脚本
- `upload_server.py` — 用户声音 & NPS 数据上传
- `nps_data.json` — NPS 图表数据（可通过上传接口更新）
- `data/*.json` — 用户声音 & 发版记录（从内嵌 HTML 导出，供前端 fetch / AI 读取）

### 首屏加载优化（第一期）

- **懒加载**：页面启动只拉 `releases.json`（约 66KB）；进入「用户声音」Tab 再拉 `tickets` / `feedback` / `store`（工单含完整 `desc`，约 4MB+）。
- **闭环 Tab**：进入时再拉 `voice_closure_*.json`（原有逻辑）。
- **缓存**：`GET /upload-api/api/data-status` 返回各文件 mtime，前端用 `?v=` + 浏览器缓存；服务端对 JSON 响应 **gzip**（`Accept-Encoding: gzip`）并带 `ETag` / `Cache-Control: max-age=300`。
- 更新 `upload_server.py` 后需 `sudo systemctl restart upload_server`。

```bash
# 从内嵌 HTML 导出最新数据到 data/
python3 scripts/export_embedded_data.py
```

## Confluence 凭证（发版数据更新必需）

凭证目录：`/home/ubuntu/release-platform/.config/tokens/`

| 文件 | 用途 |
|------|------|
| `confluence.token` | Bearer Token（推荐，一行纯 token 或 `token=xxx`） |
| `confluence.cookie` | 浏览器 Cookie（备用） |

### 更新 Bearer Token（推荐）

1. 登录 https://confluence.zhenguanyu.com
2. 个人设置 → Personal Access Token → 创建新 Token
3. 写入服务器：

```bash
ssh ubuntu@43.156.48.214
echo '你的新Token' > /home/ubuntu/release-platform/.config/tokens/confluence.token
chmod 600 /home/ubuntu/release-platform/.config/tokens/confluence.token
python3 /home/ubuntu/release-platform/scripts/check_auth.py
```

### 更新 Cookie（备用）

1. 浏览器登录 Confluence，打开开发者工具 → Network
2. 刷新任意页面，复制 Request Headers 中的完整 `Cookie` 值
3. 写入 `confluence.cookie`（格式：一整行 cookie 字符串）

### 验证

```bash
python3 /home/ubuntu/release-platform/scripts/check_auth.py
# 看到 Confluence OK 后，在页面点击「更新数据」
```

### ⚠️ 服务器无法直连 Confluence

腾讯云服务器 IP 会被 Confluence SSO 拦截（返回登录页），**线上「更新数据」按钮无法直接拉取 Confluence**。

请在本地（公司网络）执行：

```bash
# 1. 确保本地有有效 token
#    .config/tokens/confluence.token

# 2. 拉取并同步到服务器
bash scripts/update_releases_local.sh
```

或手动：

```bash
python3 update_data.py
scp data/releases.json ubuntu@43.156.48.214:/home/ubuntu/release-platform/data/
```

## JUST 工单凭证（用户工单 Tab）

凭证：`.config/tokens/work-order.cookie`（登录 https://work-order.zhenguanyu.com 后从浏览器复制 Cookie）

```bash
python3 scripts/check_auth.py          # 验证 JUST 登录
python3 scripts/fetch_tickets.py --days 1   # 拉最近 1 天，合并进 data/tickets.json
bash scripts/update_tickets_local.sh      # 拉取 + scp 到线上
```

`TICKET_DAYS=30 bash scripts/update_tickets_local.sh` 可拉更长时间范围。
