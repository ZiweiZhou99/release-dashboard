# JUST 工单 Cookie 30 秒更新卡

说明：当前脚本默认优先使用 `ic` 动态 Cookie，这份文档主要用于 `ic` 暂时不可用时的兜底方案。

适用文件：`/Users/zhouziwei/FeedBackChecking/.config/tokens/work-order.cookie`

## 1) 浏览器里复制 Cookie（10 秒）

1. 打开并登录：`https://work-order.zhenguanyu.com`
2. 按 `F12` 打开开发者工具，切到 `Network`
3. 刷新页面，点任意接口请求
4. 在 `Request Headers` 里复制整行 `Cookie` 值

## 2) 终端写入（5 秒）

先把刚复制的 Cookie 放进剪贴板，然后执行：

```bash
cd /Users/zhouziwei/FeedBackChecking
pbpaste | tr -d '\n' > .config/tokens/work-order.cookie
chmod 600 .config/tokens/work-order.cookie
```

## 3) 立即验证（5 秒）

```bash
python3 scripts/check_auth.py
```

看到 `JUST` 校验通过即可。

## 4) 失败时快速排查（10 秒）

1. 确认复制的是 **请求头 Cookie 整行**，不是网页里某个单字段
2. 重新登录后再复制一次（旧会话可能已过期）
3. 确认本机网络环境可访问公司系统

## 5) 一键补跑同步（可选）

```bash
bash scripts/sync_all_local.sh
```
