#!/bin/sh
set -eu

APP_CONTAINER="${APP_CONTAINER:-slowlink_assistant_bot}"
CHECK_INTERVAL="${CHECK_INTERVAL:-20}"
CPU_THRESHOLD="${CPU_THRESHOLD:-85}"
HIGH_COUNT_LIMIT="${HIGH_COUNT_LIMIT:-4}"
COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-600}"
LOG_FILE="${LOG_FILE:-/opt/slowlink_assistant_bot/watchdog.log}"
ENV_FILE="${ENV_FILE:-/opt/slowlink_assistant_bot/.env}"
STATUS_FILE="${STATUS_FILE:-/opt/slowlink_assistant_bot/data/watchdog_status.txt}"

high_count=0
last_restart=0

log() {
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  line="[$ts] $*"
  echo "$line"
  printf '%s\n' "$line" >> "$LOG_FILE" 2>/dev/null || true
}

write_status() {
  status_cpu="${1:-未知}"
  status_note="${2:-运行中}"
  status_dir="$(dirname "$STATUS_FILE")"
  status_tmp="${STATUS_FILE}.tmp"
  mkdir -p "$status_dir" 2>/dev/null || true
  {
    printf 'updated_at_ts=%s\n' "$(date +%s)"
    printf 'updated_at=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
    printf 'container=%s\n' "$APP_CONTAINER"
    printf 'cpu=%s\n' "$status_cpu"
    printf 'high_count=%s\n' "$high_count"
    printf 'threshold=%s\n' "$CPU_THRESHOLD"
    printf 'last_restart_ts=%s\n' "$last_restart"
    printf 'note=%s\n' "$status_note"
  } > "$status_tmp" 2>/dev/null && mv "$status_tmp" "$STATUS_FILE" 2>/dev/null || true
}

load_env() {
  if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
  fi
}

notify_owner_restart() {
  restart_cpu="${1:-未知}"
  load_env
  if [ "${BOT_TOKEN:-}" = "" ] || [ "${OWNER_USER_ID:-}" = "" ]; then
    log "通知跳过：BOT_TOKEN或OWNER_USER_ID未配置"
    return
  fi
  text="⚠️CPU过高，Bot已自动重启
容器：$APP_CONTAINER
CPU：${restart_cpu}%
时间：$(date '+%Y-%m-%d %H:%M:%S')"
  if curl -fsS --max-time 10 -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${OWNER_USER_ID}" \
    --data-urlencode "text=${text}" >/dev/null 2>&1; then
    log "已发送重启提醒"
  else
    log "重启提醒发送失败"
  fi
}

container_cpu() {
  docker stats --no-stream --format '{{.CPUPerc}}' "$APP_CONTAINER" 2>/dev/null | tr -d '%' | awk '{printf "%.0f", $1}'
}

snapshot() {
  log "记录现场：负载=$(cut -d ' ' -f1-3 /proc/loadavg 2>/dev/null || true)"
  docker stats --no-stream "$APP_CONTAINER" >> "$LOG_FILE" 2>/dev/null || true
  ps -eo pid,ppid,comm,%cpu,%mem,etime,args --sort=-%cpu | head -20 >> "$LOG_FILE" 2>/dev/null || true
  docker logs --tail 80 "$APP_CONTAINER" >> "$LOG_FILE" 2>&1 || true
}

log "监控已启动：容器=$APP_CONTAINER 阈值=${CPU_THRESHOLD}% 连续=${HIGH_COUNT_LIMIT}次 间隔=${CHECK_INTERVAL}秒 冷却=${COOLDOWN_SECONDS}秒"
write_status "未知" "监控已启动"

while true; do
  cpu="$(container_cpu || true)"
  case "$cpu" in
    ''|*[!0-9]*)
      high_count=0
      write_status "未知" "读取CPU失败"
      sleep "$CHECK_INTERVAL"
      continue
      ;;
  esac

  if [ "$cpu" -ge "$CPU_THRESHOLD" ]; then
    high_count=$((high_count + 1))
    log "CPU过高：${cpu}%（${high_count}/${HIGH_COUNT_LIMIT}）"
  else
    if [ "$high_count" -gt 0 ]; then
      log "CPU恢复：${cpu}%（计数清零）"
    fi
    high_count=0
  fi
  write_status "$cpu" "运行中"

  now="$(date +%s)"
  if [ "$high_count" -ge "$HIGH_COUNT_LIMIT" ]; then
    since=$((now - last_restart))
    if [ "$last_restart" -eq 0 ] || [ "$since" -ge "$COOLDOWN_SECONDS" ]; then
      snapshot
      log "准备重启容器：$APP_CONTAINER，原因=持续CPU过高"
      if docker restart "$APP_CONTAINER" >> "$LOG_FILE" 2>&1; then
        log "容器重启完成：$APP_CONTAINER"
        last_restart="$now"
        write_status "$cpu" "刚刚自动重启"
        notify_owner_restart "$cpu"
      else
        log "容器重启失败：$APP_CONTAINER"
        write_status "$cpu" "自动重启失败"
      fi
    else
      log "冷却中，跳过重启：${since}秒/${COOLDOWN_SECONDS}秒"
      write_status "$cpu" "冷却中，跳过重启"
    fi
    high_count=0
  fi

  sleep "$CHECK_INTERVAL"
done
