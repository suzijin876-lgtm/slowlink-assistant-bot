#!/bin/sh
set -eu

INSTALL_DIR="/opt/slowlink_assistant_bot"
CONTAINER="slowlink_assistant_bot"
WATCHDOG_SERVICE="slowlink-assistant-watchdog.service"
PURGE=0

die() {
  printf '[卸载失败] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
用法：sudo sh uninstall.sh [--purge]

  默认卸载容器和watchdog，但保留配置、数据库和程序文件。
  --purge  永久删除程序、配置和数据库，必须输入PURGE确认。
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --purge)
      PURGE=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "未知参数：$1"
      ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "请使用sudo或root运行"

if [ "$PURGE" -eq 1 ]; then
  printf '此操作会永久删除Bot配置和数据库。输入PURGE确认：' > /dev/tty
  IFS= read -r answer < /dev/tty || answer=""
  [ "$answer" = "PURGE" ] || die "已取消永久删除"
  [ "$INSTALL_DIR" = "/opt/slowlink_assistant_bot" ] || die "安装目录异常，拒绝删除"
fi

systemctl disable --now "$WATCHDOG_SERVICE" >/dev/null 2>&1 || true
rm -f -- "/etc/systemd/system/$WATCHDOG_SERVICE"
systemctl daemon-reload >/dev/null 2>&1 || true

if [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
  cd "$INSTALL_DIR"
  docker compose stop assistant_bot >/dev/null 2>&1 || true
  docker compose rm -f assistant_bot >/dev/null 2>&1 || true
elif command -v docker >/dev/null 2>&1; then
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
fi

if [ "$PURGE" -eq 0 ]; then
  printf '卸载完成，配置和数据库已保留在%s\n' "$INSTALL_DIR"
  printf '重新安装时会自动复用现有数据。\n'
  exit 0
fi

rm -rf -- "$INSTALL_DIR"
printf '程序、配置和数据库已永久删除。\n'
