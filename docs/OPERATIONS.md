# 运维说明

当前版本：`0.1.19`

## 统一管理入口

Ubuntu和Debian：

```bash
curl -fsSL https://raw.githubusercontent.com/suzijin876-lgtm/slowlink-assistant-bot/main/install.sh | sudo bash
```

当前公开仓库无需GitHub Token。安装程序不会覆盖已有`.env`和`data/`。

无参数运行时显示：

```text
SlowLink Assistant Bot 管理
1.安装
2.更新到最新版本
3.卸载
0.退出
```

卸载二级菜单：

```text
卸载方式
1.卸载程序，保留配置和数据库
2.彻底删除程序、配置和数据库
0.返回上一级
```

彻底删除仍需输入`PURGE`确认。更新选项要求Bot已经安装，并自动保留`.env`和`data/`。

首次安装按顺序询问机器人Token、主人用户ID、报表群ID和源频道ID。Token输入会显示在终端上；报表群和源频道应填写负数ID或Telegram用户名。

高级管理命令：

```bash
sudo /opt/slowlink_assistant_bot/manage.sh status
sudo /opt/slowlink_assistant_bot/manage.sh logs
sudo /opt/slowlink_assistant_bot/manage.sh restart
sudo /opt/slowlink_assistant_bot/manage.sh update
sudo /opt/slowlink_assistant_bot/manage.sh backup
sudo /opt/slowlink_assistant_bot/manage.sh uninstall
```

`manage.sh purge`会永久删除配置和数据库，必须手动输入`PURGE`确认。

## 服务器路径

项目部署路径：

```bash
/opt/slowlink_assistant_bot
```

主要文件：

```text
/opt/slowlink_assistant_bot/.env
/opt/slowlink_assistant_bot/docker-compose.yml
/opt/slowlink_assistant_bot/data/assistant.sqlite3
/opt/slowlink_assistant_bot/data/watchdog_status.txt
/opt/slowlink_assistant_bot/watchdog.log
/etc/systemd/system/slowlink-assistant-watchdog.service
```

## 容器

查看容器状态：

```bash
docker ps --filter name=slowlink_assistant_bot --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
```

查看容器健康：

```bash
docker inspect --format "{{.State.Health.Status}}" slowlink_assistant_bot
```

查看 Bot 版本：

```bash
cd /opt/slowlink_assistant_bot
docker compose exec -T assistant_bot python -c "import assistant_bot; print(assistant_bot.__version__)"
```

重启 Bot 容器：

```bash
cd /opt/slowlink_assistant_bot
docker compose up -d assistant_bot
```

## 日志

实时查看 Bot 日志：

```bash
docker logs -f --tail 100 slowlink_assistant_bot
```

查看最近 30 分钟日志：

```bash
docker logs --since 30m --tail 200 slowlink_assistant_bot
```

正常报表日志示例：

```text
日报发送完成：日期=2026-07-10 转发=27条 异常=0次
```

报表时间重叠时的日志示例：

```text
组合报表发送完成：包含=日报、周报
组合报表发送完成：包含=日报、周报、月报
```

频道纠错日志示例：

```text
👎进入待删除：消息=1088 👎=2 💩=0 倒计时=60秒
👎自动删除已取消：消息=1088 👎=1 💩=0
自动删除完成：消息=1088 👎=2 💩=0
💩直接删除完成：消息=1089 👎=0 💩=2
帖子已保留：消息=1089 原因=主人确认
批量删除保护已触发：10分钟内已删除4条 消息=1090 触发=💩
```

频道置顶时的正常跳过日志：

```text
跳过频道置顶通知：来源=Source 消息=1234
```

只看异常关键词：

```bash
docker logs --since 2h slowlink_assistant_bot 2>&1 | grep -Ei "error|traceback|exception|failed|失败|异常"
```

查看 watchdog 日志：

```bash
tail -f /opt/slowlink_assistant_bot/watchdog.log
```

查看 watchdog 状态文件：

```bash
cat /opt/slowlink_assistant_bot/data/watchdog_status.txt
```

## Watchdog

查看 watchdog 服务状态：

```bash
systemctl status slowlink-assistant-watchdog --no-pager
```

查看是否运行：

```bash
systemctl is-active slowlink-assistant-watchdog.service
```

重启 watchdog：

```bash
systemctl restart slowlink-assistant-watchdog.service
```

watchdog 默认策略：

```text
检查间隔：20 秒
CPU 阈值：85%
连续次数：4 次
冷却时间：600 秒
监控容器：slowlink_assistant_bot
```

触发自动重启后：

- 写入 `/opt/slowlink_assistant_bot/watchdog.log`
- 更新 `/opt/slowlink_assistant_bot/data/watchdog_status.txt`
- 调用 Bot API 给 `OWNER_USER_ID` 发送私聊提醒

## 配置变更

修改 Bot token：

```bash
cd /opt/slowlink_assistant_bot
nano .env
docker compose up -d assistant_bot
systemctl restart slowlink-assistant-watchdog.service
```

修改源频道、报表群或 owner：

```bash
cd /opt/slowlink_assistant_bot
nano .env
docker compose up -d assistant_bot
```

## 频道纠错权限

频道设置中建议只启用标准👎和💩反应。Telegram Bot API不能修改频道可用反应，Bot启动时只会检查并记录中文警告。Bot需要保持频道管理员身份，并拥有：

```text
删除消息
```

如果删除消息权限被取消，Bot会记录“帖子删除失败”并停止自动重试。

## 本地验证

```powershell
python -m compileall -q assistant_bot tests
python -m unittest discover -s tests -v
```

## 部署注意

- 不要覆盖服务器 `.env`。
- 不要删除服务器 `data/`。
- 只重建 `slowlink_assistant_bot`，不要动主 SlowLink。
- 更新 watchdog 脚本后，需要执行 `systemctl daemon-reload` 并重启 `slowlink-assistant-watchdog.service`。
- 上传包可以部署完成后删除，避免残留。

## 发布新版本

1. 更新`VERSION`、`assistant_bot/__init__.py`和`CHANGELOG.md`。
2. 运行全部测试和Bash语法检查。
3. 提交并推送`main`。
4. 创建并推送`vX.Y.Z`标签。
5. GitHub Actions自动生成app包、full包、更新日志和`SHA256SUMS.txt`并发布Release。

## 主 SlowLink 验证

Bot 项目和主 SlowLink 分开运行。部署 Bot 后，可以顺手确认主 SlowLink 健康：

```bash
cd /opt/slowlink
curl -sf http://127.0.0.1:8080/health
```
