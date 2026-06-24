#!/usr/bin/env bash
# 在本地（公司网络）拉取 Confluence 发版数据，并同步到线上服务器。
# 原因：腾讯云服务器 IP 无法通过 Confluence SSO，需在本地执行。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${RELEASE_SERVER:-ubuntu@43.156.48.214}"
KEY="${RELEASE_SSH_KEY:-$HOME/.ssh/ai_deploy_key}"
REMOTE_DIR="/home/ubuntu/release-platform"

echo "==> 本地拉取 Confluence + 石墨..."
cd "$ROOT"
python3 update_data.py

echo "==> 同步 releases.json 到服务器..."
scp -i "$KEY" -o StrictHostKeyChecking=no \
  "$ROOT/data/releases.json" \
  "$SERVER:$REMOTE_DIR/data/releases.json"

echo "✅ 完成。刷新 https://www.zhouziwei.online/release-dashboard.html 查看"
