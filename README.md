# 学练机发版看板 · Release Dashboard

面向产品/运营的发版与用户声音一体化看板：汇总 Confluence/石墨发版记录，聚合 JUST 工单、Cupid 反馈与门店原声，并支持「发版项 ↔ 用户原声」闭环确认与汇报导出。

线上地址：[release-dashboard.html](https://www.zhouziwei.online/release-dashboard.html)

## 功能概览

| Tab | 说明 |
|-----|------|
| **发版记录** | 按版本浏览发版项，支持筛选、详情与 Confluence/石墨一键更新 |
| **用户声音** | 工单 / 用户反馈 / 门店反馈三视图，全局搜索与 CSV 上传热更新 |
| **用户声音闭环** | 发版项台账 + 关键词自动关联原声，人工确认/排除/触达，导出 CSV 与 Markdown 汇报 |
| **NPS** | NPS 趋势与分布，支持月度 CSV 上传重建 |

## 项目结构

```
├── release-dashboard.html   # 主页面（与 index.html 同步）
├── index.html
├── upload_server.py           # 数据上传、JSON 只读 API、闭环状态保存
├── update_server.py           # 发版数据更新 API
├── update_data.py             # 从 Confluence/石墨拉取发版记录
├── kb_server_v2.py            # 知识库问答 API
├── data/                      # 运行时 JSON 数据（前端 fetch 加载）
├── scripts/                   # 数据拉取、导出、闭环生成等脚本
├── docs/                      # 飞书导入、闭环汇报模板等文档
├── deploy/                    # systemd 服务单元
└── DEPLOY.md                  # 服务器部署说明
```

## 本地使用

### 1. 准备数据

前端从 `/upload-api/data/*.json` 读取数据。本地调试可：

- 使用仓库内 `data/` 已有快照；或
- 运行 `python3 scripts/export_embedded_data.py` 从内嵌 HTML 导出（迁移用）

发版记录更新（需 Confluence/石墨凭证，见 `DEPLOY.md`）：

```bash
python3 update_data.py
```

工单拉取（需 `work-order.cookie`）：

```bash
python3 scripts/fetch_tickets.py --days 7
bash scripts/update_tickets_local.sh
```

### 2. 启动上传/数据服务

```bash
python3 upload_server.py
# 默认监听 8890，提供 /upload-api/data/*.json 与上传接口
```

静态页可用任意 HTTP 服务器打开 `release-dashboard.html`，并将 API 代理到 `upload_server`，或直接使用线上环境。

### 3. 生成用户声音闭环数据

```bash
python3 scripts/export_feishu_voice_closure.py --json-only --json-out \
  --ledger <飞书台账CSV路径>
```

产出：`data/voice_closure_ledger.json`、`voice_closure_links.json`、`voice_closure_state.json`，以及可导入飞书的 `exports/feishu/*.csv`。

## 首屏加载优化

- **懒加载**：打开页面仅加载 `releases.json`；进入「用户声音」Tab 再加载工单/反馈等大文件（工单保留完整 `desc` 字段）。
- **压缩与缓存**：`upload_server` 对 JSON 响应 gzip，并返回 `ETag` / `Cache-Control`；前端通过 `/upload-api/api/data-status` 的 mtime 作缓存版本号。

详见 [DEPLOY.md](./DEPLOY.md) 与 [data/README.md](./data/README.md)。

## 相关文档

- [DEPLOY.md](./DEPLOY.md) — 生产环境部署与凭证配置
- [docs/feishu_voice_closure_setup.md](./docs/feishu_voice_closure_setup.md) — 飞书多维表格搭建
- [docs/发版用户声音闭环_汇报模板.md](./docs/发版用户声音闭环_汇报模板.md) — 进度汇报模板

## 技术栈

- 前端：单页 HTML + 原生 JS（无构建步骤）
- 后端：Python 3 标准库 HTTP 服务 + 若干数据脚本
- 数据：JSON 文件 + 页面内上传/热更新

## 许可与说明

本项目为内部发版与用户声音运营工具。请勿将 `.config/` 下的 Token、Cookie 等凭证提交到仓库（已在 `.gitignore` 中排除）。
