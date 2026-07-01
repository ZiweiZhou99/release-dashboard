#!/usr/bin/env bash
# 在本地（需能访问 JUST 工单系统）拉取工单，并同步到线上服务器。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${RELEASE_SERVER:-ubuntu@43.156.48.214}"
KEY="${RELEASE_SSH_KEY:-$HOME/.ssh/ai_deploy_key}"
REMOTE_DIR="/home/ubuntu/release-platform"
DAYS="${TICKET_DAYS:-1}"

echo "==> 本地拉取 JUST 工单（最近 ${DAYS} 天）..."
cd "$ROOT"
python3 scripts/fetch_tickets.py --days "$DAYS"

echo "==> 同步 tickets.json 到服务器..."
scp -i "$KEY" -o StrictHostKeyChecking=no \
  -o ConnectTimeout=20 -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
  "$ROOT/data/tickets.json" \
  "$SERVER:$REMOTE_DIR/data/tickets.json"

echo "✅ 完成。刷新 https://www.zhouziwei.online/release-dashboard.html 用户工单 Tab"
