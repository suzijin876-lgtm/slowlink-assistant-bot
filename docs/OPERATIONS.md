# 运维说明

当前版本：`0.1.35`

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
4.修改配置
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

首次安装按顺序询问机器人Token、主人用户ID、报表群ID、可选简报频道ID和源频道ID。Token输入会显示在终端上；聊天目标应填写负数ID或Telegram用户名，简报频道可直接回车跳过。

## Bot按钮面板

主人私聊发送`/start`打开主面板，可查看当前报告、运行状态、最近记录和系统自检，也可管理简报开关与固定封面。旧命令继续兼容，但Telegram命令列表只显示`/start`。

简报设置可分别控制报表群和简报频道的日报、周报、月报。设置保存在SQLite中，不需要重启容器。固定报表群只显示主人可用的“当前报告”按钮。

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
日报发送完成：日期=2026-07-10 转发=27条 异常=0次 目标=报表群
```

报表时间重叠时的日志示例：

```text
组合报表发送完成：包含=日报、周报 目标=报表群
组合报表发送完成：包含=日报、周报、月报 目标=简报频道
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

主人私聊快捷处理：回复Bot复制的消息发送`删`或`删除`会立即删除源帖；如果已经在频道中手动删除，回复`已删除`即可记入纠错统计。私聊副本不会被删除。

定时报表封面由主人私聊按钮面板管理：点击“封面管理”和“更换封面”，随后直接发送图片即可设置或替换。封面失败时Bot会记录中文警告、私聊主人，并自动改发纯文字报表。

历史周期不完整时，报表会显示实际数据范围，并将同期变化写为“暂无可比数据”。完整覆盖但确实没有转发时，零仍会参与正常的增加、减少或持平计算。正式报表发送后会在SQLite的`report_snapshots`表保存当时正文和统计依据。

Bot错过设定的精确分钟后，会在当天补发日报；周报只在星期一补发，月报只在每月一号补发。已发送周期继续由SQLite去重，新安装且没有历史数据时不会补空报表。

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
心跳上限：120 秒
心跳连续次数：2 次
冷却时间：600 秒
监控容器：slowlink_assistant_bot
```

触发自动重启后：

- 写入 `/opt/slowlink_assistant_bot/watchdog.log`
- 更新 `/opt/slowlink_assistant_bot/data/watchdog_status.txt`
- 调用 Bot API 给 `OWNER_USER_ID` 发送私聊提醒

## 配置变更

运行统一管理入口：

```bash
curl -fsSL https://raw.githubusercontent.com/suzijin876-lgtm/slowlink-assistant-bot/main/install.sh | sudo bash
```

选择`4.修改配置`后，可依次修改：

- Bot Token
- 主人用户ID
- 报表群ID
- 简报频道ID（可选，输入`0`停用）
- 源频道ID
- SlowLink面板地址（可选，输入`0`隐藏按钮）

每项直接回车保留原值。脚本只替换这六项并保留其他`.env`设置，然后强制重建Assistant Bot容器以读取新配置。新配置启动失败时自动恢复旧配置；SQLite、备份、主SlowLink、Redis和watchdog不会被修改或重启。

简报频道中的Bot需要保持管理员身份，并拥有：

```text
发布消息
编辑消息（用于置顶）
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
