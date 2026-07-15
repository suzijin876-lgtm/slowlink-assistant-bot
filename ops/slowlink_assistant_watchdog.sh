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
HEARTBEAT_FILE="${HEARTBEAT_FILE:-/opt/slowlink_assistant_bot/data/bot_heartbeat}"
HEARTBEAT_MAX_AGE="${HEARTBEAT_MAX_AGE:-120}"
STALE_COUNT_LIMIT="${STALE_COUNT_LIMIT:-2}"
WATCHDOG_MAX_CHECKS="${WATCHDOG_MAX_CHECKS:-0}"

high_count=0
stale_count=0
last_restart=0
check_count=0

log() {
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  line="[$ts] $*"
  echo "$line"
  printf '%s\n' "$line" >> "$LOG_FILE" 2>/dev/null || true
}

write_status() {
  status_cpu="${1:-未知}"
  status_note="${2:-运行中}"
  status_heartbeat_age="${3:-未知}"
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
    printf 'heartbeat_age=%s\n' "$status_heartbeat_age"
    printf 'heartbeat_max_age=%s\n' "$HEARTBEAT_MAX_AGE"
    printf 'stale_count=%s\n' "$stale_count"
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
  restart_reason="${1:-未知}"
  restart_cpu="${2:-未知}"
  load_env
  if [ "${BOT_TOKEN:-}" = "" ] || [ "${OWNER_USER_ID:-}" = "" ]; then
    log "通知跳过：BOT_TOKEN或OWNER_USER_ID未配置"
    return
  fi
  if [ "$restart_reason" = "持续CPU过高" ]; then
    text="⚠️CPU过高，Bot已自动重启
容器：$APP_CONTAINER
CPU：${restart_cpu}%
时间：$(date '+%Y-%m-%d %H:%M:%S')"
  else
    text="⚠️Bot心跳超时，已自动重启
容器：$APP_CONTAINER
原因：$restart_reason
时间：$(date '+%Y-%m-%d %H:%M:%S')"
  fi
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

heartbeat_age() {
  [ -f "$HEARTBEAT_FILE" ] || {
    printf 'missing'
    return
  }
  heartbeat_mtime="$(stat -c %Y "$HEARTBEAT_FILE" 2>/dev/null || true)"
  case "$heartbeat_mtime" in
    ''|*[!0-9]*)
      printf 'missing'
      return
      ;;
  esac
  heartbeat_now="$(date +%s)"
  heartbeat_delta=$((heartbeat_now - heartbeat_mtime))
  if [ "$heartbeat_delta" -lt 0 ]; then
    heartbeat_delta=0
  fi
  printf '%s' "$heartbeat_delta"
}

snapshot() {
  log "记录现场：负载=$(cut -d ' ' -f1-3 /proc/loadavg 2>/dev/null || true)"
  docker stats --no-stream "$APP_CONTAINER" >> "$LOG_FILE" 2>/dev/null || true
  ps -eo pid,ppid,comm,%cpu,%mem,etime,args --sort=-%cpu | head -20 >> "$LOG_FILE" 2>/dev/null || true
  docker logs --tail 80 "$APP_CONTAINER" >> "$LOG_FILE" 2>&1 || true
}

log "监控已启动：容器=$APP_CONTAINER CPU阈值=${CPU_THRESHOLD}% 连续=${HIGH_COUNT_LIMIT}次 心跳上限=${HEARTBEAT_MAX_AGE}秒 冷却=${COOLDOWN_SECONDS}秒"
write_status "未知" "监控已启动" "未知"

while true; do
  check_count=$((check_count + 1))
  cpu="$(container_cpu || true)"
  case "$cpu" in
    ''|*[!0-9]*)
      high_count=0
      cpu="未知"
      ;;
    *)
      if [ "$cpu" -ge "$CPU_THRESHOLD" ]; then
        high_count=$((high_count + 1))
        log "CPU过高：${cpu}%（${high_count}/${HIGH_COUNT_LIMIT}）"
      else
        if [ "$high_count" -gt 0 ]; then
          log "CPU恢复：${cpu}%（计数清零）"
        fi
        high_count=0
      fi
      ;;
  esac

  heartbeat_current_age="$(heartbeat_age)"
  case "$heartbeat_current_age" in
    ''|*[!0-9]*)
      stale_count=$((stale_count + 1))
      log "Bot心跳异常：文件不存在（${stale_count}/${STALE_COUNT_LIMIT}）"
      ;;
    *)
      if [ "$heartbeat_current_age" -gt "$HEARTBEAT_MAX_AGE" ]; then
        stale_count=$((stale_count + 1))
        log "Bot心跳超时：${heartbeat_current_age}秒（${stale_count}/${STALE_COUNT_LIMIT}）"
      else
        if [ "$stale_count" -gt 0 ]; then
          log "Bot心跳恢复：${heartbeat_current_age}秒（计数清零）"
        fi
        stale_count=0
      fi
      ;;
  esac

  status_note="运行中"
  if [ "$cpu" = "未知" ]; then
    status_note="读取CPU失败"
  fi
  if [ "$stale_count" -gt 0 ]; then
    status_note="Bot心跳异常"
  fi
  write_status "$cpu" "$status_note" "$heartbeat_current_age"

  now="$(date +%s)"
  restart_reason=""
  if [ "$high_count" -ge "$HIGH_COUNT_LIMIT" ]; then
    restart_reason="持续CPU过高"
  elif [ "$stale_count" -ge "$STALE_COUNT_LIMIT" ]; then
    restart_reason="Bot心跳超时"
  fi
  if [ -n "$restart_reason" ]; then
    since=$((now - last_restart))
    if [ "$last_restart" -eq 0 ] || [ "$since" -ge "$COOLDOWN_SECONDS" ]; then
      snapshot
      log "准备重启容器：$APP_CONTAINER，原因=$restart_reason"
      if docker restart "$APP_CONTAINER" >> "$LOG_FILE" 2>&1; then
        log "容器重启完成：$APP_CONTAINER"
        last_restart="$now"
        write_status "$cpu" "刚刚自动重启" "$heartbeat_current_age"
        notify_owner_restart "$restart_reason" "$cpu"
      else
        log "容器重启失败：$APP_CONTAINER"
        write_status "$cpu" "自动重启失败" "$heartbeat_current_age"
      fi
    else
      log "冷却中，跳过重启：${since}秒/${COOLDOWN_SECONDS}秒"
      write_status "$cpu" "冷却中，跳过重启" "$heartbeat_current_age"
    fi
    high_count=0
    stale_count=0
  fi

  if [ "$WATCHDOG_MAX_CHECKS" -gt 0 ] && [ "$check_count" -ge "$WATCHDOG_MAX_CHECKS" ]; then
    break
  fi

  sleep "$CHECK_INTERVAL"
done
