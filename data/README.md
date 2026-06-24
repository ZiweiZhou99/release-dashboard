# 数据目录

用户声音、发版记录等运行时数据统一存放于此，供前端 `fetch` 加载，也方便 AI / 脚本直接读取（充当轻量数据库）。

## 文件说明

| 文件 | 格式 | 来源 |
|------|------|------|
| `releases.json` | 发版记录对象数组 | `update_data.py` 拉取 Confluence/石墨 |
| `tickets.json` | 工单对象数组 | `scripts/fetch_tickets.py` 拉 JUST / CSV 上传 |
| `feedback.json` | 反馈二维数组 `[userId, desc, category, device, source, time]` | Cupid 导出 / 上传 |
| `store.json` | 门店反馈二维数组 | 门店表单导出 / 上传 |
| `feature_keywords.json` | 功能名 → 搜索关键词映射 | 手工维护 |
| `voice_closure_ledger.json` | 发版项台账（可感知、用户价值） | `export_feishu_voice_closure.py --json-out` |
| `voice_closure_links.json` | 发版项 ↔ 原声推荐关联 | 同上 |
| `voice_closure_state.json` | 人工确认/触达状态 | 看板 Tab 保存 |
| `nps_data.json` | NPS 图表数据（根目录） | CSV 上传后自动生成 |

## 更新方式

```bash
# 从 HTML 内嵌数据导出（迁移用）
python3 scripts/export_embedded_data.py

# 拉取 JUST 工单（最近 1 天，需 work-order.cookie）
python3 scripts/fetch_tickets.py --days 1
bash scripts/update_tickets_local.sh

# 上传新数据（页面内「上传数据」或 API）
curl -X POST -H "X-Upload-Token: zzw2026" -F "file=@tickets.csv" \
  https://www.zhouziwei.online/upload-api/upload/tickets
# 生成用户声音闭环看板数据（需飞书台账 CSV）
python3 scripts/export_feishu_voice_closure.py --json-only --json-out \
  --ledger ~/Downloads/学练机发版用户声音闭环_发版项台账_表格.csv
```

## 读取 API

`GET /upload-api/data/{releases|tickets|feedback|store|voice_closure_*}.json` — 公开只读。

- 首屏仅加载 `releases.json`；「用户声音」Tab 懒加载其余大文件（**不截断 `desc` 字段**）。
- 支持 **gzip** 压缩与 **ETag** 缓存；mtime 见 `GET /upload-api/api/data-status`。

`POST /upload-api/voice-closure/state` — 保存关联确认状态（需 `X-Upload-Token`）。

发版数据更新后写入 `data/releases.json`（`update_data.py`），不再内嵌 HTML。
