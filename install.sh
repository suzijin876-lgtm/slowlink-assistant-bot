#!/bin/sh
set -eu

REPO="suzijin876-lgtm/slowlink-assistant-bot"
INSTALL_DIR="/opt/slowlink_assistant_bot"
CONTAINER="slowlink_assistant_bot"
WATCHDOG_SERVICE="slowlink-assistant-watchdog.service"
REQUESTED_VERSION=""
UPDATE_ONLY=0
SHOW_MENU=0
TMP_DIR=""

[ "$#" -eq 0 ] && SHOW_MENU=1

log() {
  printf '[安装] %s\n' "$*"
}

die() {
  printf '[安装失败] %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
    rm -rf -- "$TMP_DIR"
  fi
}

is_chat_ref() {
  value=$(printf '%s' "$1" | tr -d '[:space:]')
  case "$value" in
    -*)
      digits=${value#-}
      case "$digits" in ''|*[!0-9]*) return 1 ;; esac
      [ "$digits" -gt 0 ]
      ;;
    '')
      return 1
      ;;
    *[!0-9]*)
      username=${value#@}
      [ "${#username}" -ge 5 ] || return 1
      case "$username" in *[!A-Za-z0-9_]*) return 1 ;; esac
      ;;
    *)
      return 1
      ;;
  esac
}

validate_source_refs() {
  printf '%s\n' "$1" | tr ',' '\n' | while IFS= read -r ref; do
    is_chat_ref "$ref" || exit 1
  done
}

usage() {
  cat <<'EOF'
用法：sudo sh install.sh [--version 0.1.20] [--update]

  --version VERSION  安装指定版本，默认安装GitHub最新稳定版
  --update           保留现有.env和data并更新程序
  --help             显示帮助
EOF
}

uninstall_menu() {
  if [ ! -f "$INSTALL_DIR/uninstall.sh" ]; then
    printf '[提示]尚未检测到已安装的Bot，无法卸载。\n' > /dev/tty
    return
  fi
  while true; do
    cat > /dev/tty <<'EOF'
卸载方式
1.卸载程序，保留配置和数据库
2.彻底删除程序、配置和数据库
0.返回上一级
请选择：
EOF
    choice=""
    IFS= read -r choice < /dev/tty || choice=""
    case "$choice" in
      1)
        if sh "$INSTALL_DIR/uninstall.sh"; then
          exit 0
        fi
        ;;
      2)
        if sh "$INSTALL_DIR/uninstall.sh" --purge; then
          exit 0
        fi
        ;;
      0)
        return
        ;;
      *)
        printf '[输入错误]请输入0、1或2。\n' > /dev/tty
        ;;
    esac
  done
}

main_menu() {
  while true; do
    cat > /dev/tty <<'EOF'
SlowLink Assistant Bot 管理
1.安装
2.更新到最新版本
3.卸载
0.退出
请选择：
EOF
    choice=""
    IFS= read -r choice < /dev/tty || choice=""
    case "$choice" in
      1)
        return
        ;;
      2)
        if [ ! -f "$INSTALL_DIR/.env" ]; then
          printf '[提示]尚未检测到安装，请先选择1安装。\n' > /dev/tty
          continue
        fi
        UPDATE_ONLY=1
        return
        ;;
      3)
        uninstall_menu
        ;;
      0)
        printf '已退出。\n' > /dev/tty
        exit 0
        ;;
      *)
        printf '[输入错误]请输入0、1、2或3。\n' > /dev/tty
        ;;
    esac
  done
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      [ "$#" -ge 2 ] || die "--version缺少版本号"
      REQUESTED_VERSION=${2#v}
      shift 2
      ;;
    --update)
      UPDATE_ONLY=1
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

[ "$(id -u)" -eq 0 ] || die "请使用root运行：curl ... | sudo bash"
if [ "$SHOW_MENU" -eq 1 ]; then
  main_menu
fi
if [ "$UPDATE_ONLY" -eq 1 ] && [ ! -f "$INSTALL_DIR/.env" ]; then
  die "尚未检测到安装，请先运行安装菜单并选择1安装"
fi
[ -r /etc/os-release ] || die "无法识别Linux发行版"
. /etc/os-release
case "${ID:-}" in
  ubuntu|debian) ;;
  *) die "当前仅支持Ubuntu和Debian" ;;
esac

TMP_DIR=$(mktemp -d /tmp/slowlink-assistant-install.XXXXXX)
trap cleanup 0
trap 'exit 130' INT
trap 'exit 143' TERM

log "安装基础工具"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl jq unzip >/dev/null

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  log "安装Docker Engine和Docker Compose"
  curl -fsSL https://get.docker.com -o "$TMP_DIR/get-docker.sh"
  sh "$TMP_DIR/get-docker.sh"
fi

systemctl enable --now docker >/dev/null 2>&1 || die "Docker服务启动失败"

github_get() {
  url=$1
  output=${2:-}
  accept=${3:-application/vnd.github+json}
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    if [ -n "$output" ]; then
      curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: $accept" "$url" -o "$output"
    else
      curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: $accept" "$url"
    fi
  elif [ -n "$output" ]; then
    curl -fsSL -H "Accept: $accept" "$url" -o "$output"
  else
    curl -fsSL -H "Accept: $accept" "$url"
  fi
}

if [ -n "$REQUESTED_VERSION" ]; then
  RELEASE_API="https://api.github.com/repos/$REPO/releases/tags/v$REQUESTED_VERSION"
else
  RELEASE_API="https://api.github.com/repos/$REPO/releases/latest"
fi

log "读取GitHub Release信息"
github_get "$RELEASE_API" "$TMP_DIR/release.json" || die "读取Release失败，请检查网络或GitHub访问权限"
TAG_NAME=$(jq -r '.tag_name // empty' "$TMP_DIR/release.json")
FULL_NAME=$(jq -r '.assets[] | select(.name | test("_full\\.zip$")) | .name' "$TMP_DIR/release.json" | head -n 1)
FULL_URL=$(jq -r '.assets[] | select(.name | test("_full\\.zip$")) | .url' "$TMP_DIR/release.json" | head -n 1)
CHECKSUM_URL=$(jq -r '.assets[] | select(.name == "SHA256SUMS.txt") | .url' "$TMP_DIR/release.json" | head -n 1)
[ -n "$TAG_NAME" ] || die "Release缺少版本标签"
[ -n "$FULL_NAME" ] || die "Release缺少full安装包文件名"
[ -n "$FULL_URL" ] || die "Release缺少full安装包"
[ -n "$CHECKSUM_URL" ] || die "Release缺少SHA256SUMS.txt"
[ "$FULL_NAME" = "$(basename "$FULL_NAME")" ] || die "Release安装包文件名不安全"

FULL_FILE="$TMP_DIR/$FULL_NAME"
CHECKSUM_FILE="$TMP_DIR/SHA256SUMS.txt"
log "下载$TAG_NAME"
github_get "$FULL_URL" "$FULL_FILE" "application/octet-stream" || die "下载安装包失败"
github_get "$CHECKSUM_URL" "$CHECKSUM_FILE" "application/octet-stream" || die "下载校验文件失败"

FULL_NAME=$(basename "$FULL_FILE")
grep "  $FULL_NAME\$" "$CHECKSUM_FILE" > "$TMP_DIR/SHA256SUMS.selected" || die "校验文件中找不到$FULL_NAME"
(cd "$TMP_DIR" && sha256sum -c SHA256SUMS.selected) || die "安装包SHA-256校验失败"

if unzip -Z1 "$FULL_FILE" | grep -Eq '(^/|(^|/)\.\.(/|$)|(^|/)\.env$|(^|/)data/|(^|/)\.git/)'; then
  die "安装包包含不应覆盖的配置、数据或Git目录"
fi

STAGE="$TMP_DIR/stage"
mkdir -p "$STAGE"
unzip -q "$FULL_FILE" -d "$STAGE"
[ -f "$STAGE/VERSION" ] || die "安装包缺少VERSION"
[ -f "$STAGE/docker-compose.yml" ] || die "安装包缺少docker-compose.yml"
[ -f "$STAGE/manage.sh" ] || die "安装包缺少manage.sh"
[ -f "$STAGE/uninstall.sh" ] || die "安装包缺少uninstall.sh"

KEEP_ENV=0
if [ -f "$INSTALL_DIR/.env" ]; then
  if [ "$UPDATE_ONLY" -eq 1 ]; then
    KEEP_ENV=1
  else
    printf '检测到现有配置，是否保留？[Y/n] ' > /dev/tty
    IFS= read -r answer < /dev/tty || answer=""
    case "$answer" in n|N) KEEP_ENV=0 ;; *) KEEP_ENV=1 ;; esac
  fi
fi

prompt_value() {
  prompt=$1
  value=""
  while [ -z "$value" ]; do
    printf '%s' "$prompt" > /dev/tty
    IFS= read -r value < /dev/tty || value=""
  done
  printf '%s' "$value"
}

ENV_FILE="$TMP_DIR/new.env"
if [ "$KEEP_ENV" -eq 0 ]; then
  BOT_TOKEN_VALUE=${BOT_TOKEN:-$(prompt_value '[1/4]机器人Token
从@BotFather获取；输入内容会显示，例如123456789:AAExampleToken。
请输入：')}
  OWNER_USER_ID_VALUE=${OWNER_USER_ID:-$(prompt_value '[2/4]主人用户ID
填写你自己的Telegram数字ID，例如123456789。
请输入：')}
  REPORT_CHAT_ID_VALUE=${REPORT_CHAT_ID:-$(prompt_value '[3/4]报表群ID
填写接收日报、周报和月报的群ID，通常以-100开头。
请输入：')}
  SOURCE_CHANNEL_IDS_VALUE=${SOURCE_CHANNEL_IDS:-$(prompt_value '[4/4]源频道ID
填写Bot需要监听的频道ID，通常以-100开头；多个用英文逗号分隔。
请输入：')}
  case "$BOT_TOKEN_VALUE" in *:*) ;; *) die "BOT_TOKEN格式不正确" ;; esac
  case "$OWNER_USER_ID_VALUE" in ''|*[!0-9]*) die "OWNER_USER_ID必须是正整数" ;; esac
  [ "$OWNER_USER_ID_VALUE" -gt 0 ] || die "OWNER_USER_ID必须大于0"
  is_chat_ref "$REPORT_CHAT_ID_VALUE" || die "报表群ID格式不正确：请填写负数群ID或群用户名"
  validate_source_refs "$SOURCE_CHANNEL_IDS_VALUE" || die "源频道ID格式不正确：请填写负数频道ID或频道用户名，多个用英文逗号分隔"
  umask 077
  cat > "$ENV_FILE" <<EOF
BOT_TOKEN=$BOT_TOKEN_VALUE
OWNER_USER_ID=$OWNER_USER_ID_VALUE
REPORT_CHAT_ID=$REPORT_CHAT_ID_VALUE
SOURCE_CHANNEL_IDS=$SOURCE_CHANNEL_IDS_VALUE
DATA_PATH=data/assistant.sqlite3
TIMEZONE=Asia/Shanghai
POLL_TIMEOUT=25
POLL_INTERVAL=1
REPORT_HOUR=0
REPORT_MINUTE=0
UNAUTHORIZED_GROUP_ACTION=leave
STARTUP_DROP_PENDING_UPDATES=0
EOF
  chmod 600 "$ENV_FILE"
fi

log "部署到$INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/data"
cp -a "$STAGE"/. "$INSTALL_DIR"/
find "$INSTALL_DIR/assistant_bot" -type f -exec touch {} +
touch "$INSTALL_DIR/Dockerfile" "$INSTALL_DIR/requirements.txt" "$INSTALL_DIR/docker-compose.yml"
if [ "$KEEP_ENV" -eq 0 ]; then
  install -m 600 "$ENV_FILE" "$INSTALL_DIR/.env"
else
  chmod 600 "$INSTALL_DIR/.env"
fi
chmod 755 "$INSTALL_DIR/install.sh" "$INSTALL_DIR/manage.sh" "$INSTALL_DIR/uninstall.sh" "$INSTALL_DIR/ops/slowlink_assistant_watchdog.sh"

install -m 644 "$INSTALL_DIR/deploy/slowlink-assistant-watchdog.service" "/etc/systemd/system/$WATCHDOG_SERVICE"
systemctl daemon-reload

cd "$INSTALL_DIR"
log "构建并启动Assistant Bot"
docker compose build --no-cache assistant_bot
docker compose up -d --no-deps assistant_bot

healthy=0
i=0
while [ "$i" -lt 45 ]; do
  state=$(docker inspect "$CONTAINER" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)
  if [ "$state" = "healthy" ]; then
    healthy=1
    break
  fi
  i=$((i + 1))
  sleep 2
done

if [ "$healthy" -ne 1 ]; then
  docker logs --tail 120 "$CONTAINER" 2>&1 || true
  die "容器未通过健康检查"
fi

systemctl enable --now "$WATCHDOG_SERVICE" >/dev/null 2>&1 || die "watchdog启动失败"
INSTALLED_VERSION=$(docker exec "$CONTAINER" python -c 'import assistant_bot; print(assistant_bot.__version__)')
log "安装完成：版本=$INSTALLED_VERSION"
printf '管理命令：sudo %s/manage.sh status\n' "$INSTALL_DIR"
