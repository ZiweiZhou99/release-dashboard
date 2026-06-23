# 发版管理平台部署说明

## 架构

| 组件 | 端口 | 路径 | 说明 |
|------|------|------|------|
| Nginx 静态页 | 443 | `/release-dashboard.html` | 主页面 |
| `kb_server_v2.py` | 8888 | `/kb-api/` | 知识库问答 API |
| `update_server.py` | 8889 | `/release-api/` | 发版数据更新 API |
| `upload_server.py` | 8890 | `/upload-api/` | 工单/反馈/NPS 上传 |

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

# 3. 重建知识库索引（首次或 PRD 更新后）
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

```bash
# 从内嵌 HTML 导出最新数据到 data/
python3 scripts/export_embedded_data.py
```
