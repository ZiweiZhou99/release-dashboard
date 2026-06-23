# 数据目录

用户声音、发版记录等运行时数据统一存放于此，供前端 `fetch` 加载，也方便 AI / 脚本直接读取（充当轻量数据库）。

## 文件说明

| 文件 | 格式 | 来源 |
|------|------|------|
| `releases.json` | 发版记录对象数组 | `update_data.py` 拉取 Confluence/石墨 |
| `tickets.json` | 工单对象数组 | Cupid 导出 / 上传 |
| `feedback.json` | 反馈二维数组 `[userId, desc, category, device, source, time]` | Cupid 导出 / 上传 |
| `store.json` | 门店反馈二维数组 | 门店表单导出 / 上传 |
| `feature_keywords.json` | 功能名 → 搜索关键词映射 | 手工维护 |
| `nps_data.json` | NPS 图表数据（根目录） | CSV 上传后自动生成 |

## 更新方式

```bash
# 从 HTML 内嵌数据导出（迁移用）
python3 scripts/export_embedded_data.py

# 上传新数据（页面内「上传数据」或 API）
curl -X POST -H "X-Upload-Token: zzw2026" -F "file=@tickets.csv" \
  https://www.zhouziwei.online/upload-api/upload/tickets
```

## 读取 API

`GET /upload-api/data/{releases|tickets|feedback|store}.json` — 公开只读，前端启动时加载。

发版数据更新后写入 `data/releases.json`（`update_data.py`），不再内嵌 HTML。
