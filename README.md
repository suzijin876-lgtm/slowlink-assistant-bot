# SlowLink Assistant Bot

当前版本：`0.1.14`

这是一个独立的 Telegram Bot API 项目，和主 SlowLink 分开运行。它不接主 SlowLink，不做去重、不跑规则、不生成链接，只负责把指定源频道的新消息原样复制到你的私聊，并在固定群里发送日报、周报、月报。

## 项目定位

- 新消息：源频道 -> Bot -> 你的私聊。
- 群消息：固定报表群只接收报表和当前概览。
- 权限：私聊命令只允许 `OWNER_USER_ID` 使用，群里命令也只允许你使用。
- 稳定性：Docker 自动重启、健康检查、独立 CPU watchdog、SQLite 备份和清理。
- 频道纠错：`👎`达到2个后等待60秒，`💩`达到2个后直接处理，并保留批量删除保护。
- 日志：Docker 日志和 watchdog 日志均为中文，北京时间。

## 文档

- [功能说明](docs/FEATURES.md)
- [运维说明](docs/OPERATIONS.md)
- [版本归档](docs/VERSION_ARCHIVE.md)

版本包按主 SlowLink 风格归档在根目录 `V0.1.x/` 中，例如 `V0.1.14/`。

## 必要配置

复制 `.env.example` 为 `.env`，然后填写：

```env
BOT_TOKEN=123456789:replace_me
OWNER_USER_ID=123456789
REPORT_CHAT_ID=-1001234567890
SOURCE_CHANNEL_IDS=-1001111111111,@your_public_channel
```

后续更换 Bot token：只改 `.env` 的 `BOT_TOKEN`，然后重启容器。

## 常用命令

私聊 Bot：

```text
/help      查看命令
/status    查看运行状态
/report    查看当前概览
/recent    查看最近记录，可用 /recent 20
/check     自检
```

固定报表群里：

```text
/report    查看当前概览
```

## 本地测试

```powershell
python -m compileall -q assistant_bot tests
python -m unittest discover -s tests -v
```

## 服务器常用查看

```bash
docker logs -f --tail 100 slowlink_assistant_bot
```

```bash
systemctl status slowlink-assistant-watchdog --no-pager
```

```bash
tail -f /opt/slowlink_assistant_bot/watchdog.log
```
