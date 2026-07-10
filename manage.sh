#!/bin/sh
set -eu

REPO="suzijin876-lgtm/slowlink-assistant-bot"
INSTALL_DIR="/opt/slowlink_assistant_bot"
CONTAINER="slowlink_assistant_bot"
WATCHDOG_SERVICE="slowlink-assistant-watchdog.service"

die() {
  printf '[管理失败] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
用法：sudo /opt/slowlink_assistant_bot/manage.sh COMMAND

  status     查看版本、容器和watchdog状态
  logs       实时查看Bot日志
  restart    重启Assistant Bot
  update     更新到最新GitHub Release
  backup     手动备份SQLite数据库
  uninstall  停止并卸载服务，保留配置和数据
  purge      永久删除程序、配置和数据
EOF
}

[ "$(id -u)" -eq 0 ] || die "请使用sudo或root运行"
[ "$#" -ge 1 ] || { usage; exit 1; }

case "$1" in
  status)
    version="未知"
    if docker inspect "$CONTAINER" >/dev/null 2>&1; then
      version=$(docker exec "$CONTAINER" python -c 'import assistant_bot; print(assistant_bot.__version__)' 2>/dev/null || printf '未知')
      docker inspect "$CONTAINER" --format '容器：{{.State.Status}} / {{if .State.Health}}{{.State.Health.Status}}{{else}}无健康检查{{end}}，重启={{.RestartCount}}，OOM={{.State.OOMKilled}}'
      docker stats --no-stream --format '资源：CPU {{.CPUPerc}}，内存 {{.MemUsage}}' "$CONTAINER"
    else
      printf '容器：未安装或未运行\n'
    fi
    printf '版本：%s\n' "$version"
    printf '守护：%s\n' "$(systemctl is-active "$WATCHDOG_SERVICE" 2>/dev/null || printf 'inactive')"
    ;;
  logs)
    exec docker logs -f --tail 100 "$CONTAINER"
    ;;
  restart)
    cd "$INSTALL_DIR"
    docker compose restart assistant_bot
    systemctl restart "$WATCHDOG_SERVICE"
    printf 'Assistant Bot已重启\n'
    ;;
  update)
    tmp=$(mktemp /tmp/slowlink-assistant-update.XXXXXX)
    trap 'rm -f "$tmp"' 0
    trap 'exit 130' INT
    trap 'exit 143' TERM
    if [ -n "${GITHUB_TOKEN:-}" ]; then
      curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" "https://raw.githubusercontent.com/$REPO/main/install.sh" -o "$tmp" || die "下载安装脚本失败"
    else
      curl -fsSL "https://raw.githubusercontent.com/$REPO/main/install.sh" -o "$tmp" || die "下载安装脚本失败"
    fi
    sh "$tmp" --update
    ;;
  backup)
    docker exec "$CONTAINER" python -c "from datetime import datetime; from pathlib import Path; from assistant_bot.config import BotConfig; from assistant_bot.store import EventStore; c=BotConfig.load(); s=EventStore(c.data_path); p=s.backup_database(datetime.now().astimezone(), keep_days=30); s.close(); print(p or '无需备份')"
    ;;
  uninstall)
    exec "$INSTALL_DIR/uninstall.sh"
    ;;
  purge)
    exec "$INSTALL_DIR/uninstall.sh" --purge
    ;;
  --help|-h|help)
    usage
    ;;
  *)
    die "未知命令：$1"
    ;;
esac
