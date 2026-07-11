# SlowLink Assistant Bot

当前版本：`0.1.17`

这是一个独立的 Telegram Bot API 项目，和主 SlowLink 分开运行。它不接主 SlowLink，不做去重、不跑规则、不生成链接，只负责把指定源频道的新消息原样复制到你的私聊，并在固定群里发送日报、周报、月报。

## 项目定位

- 新消息：源频道 -> Bot -> 你的私聊。
- 群消息：固定报表群只接收报表和当前概览。
- 权限：私聊命令只允许 `OWNER_USER_ID` 使用，群里命令也只允许你使用。
- 稳定性：Docker 自动重启、健康检查、独立 CPU watchdog、SQLite 备份和清理。
- 频道纠错：`👎`达到2个后等待60秒，`💩`达到2个后直接处理，并保留批量删除保护。
- 日志：Docker 日志和 watchdog 日志均为中文，北京时间。
- 分发：支持Ubuntu/Debian一键安装、命令行管理和GitHub Releases自动发布。

## 统一管理入口

仓库已公开，可在Ubuntu或Debian服务器直接执行：

```bash
curl -fsSL https://raw.githubusercontent.com/suzijin876-lgtm/slowlink-assistant-bot/main/install.sh | sudo bash
```

运行后会出现统一菜单：

```text
SlowLink Assistant Bot 管理
1.安装
2.更新到最新版本
3.卸载
0.退出
```

进入卸载后可以选择保留配置和数据库，或彻底删除。彻底删除仍需输入`PURGE`确认。

安装程序会自动安装Docker、下载最新稳定Release、校验SHA-256，并按四步中文提示填写Bot配置。更新会保留`.env`和`data/`。

安装时依次填写：

1. 机器人Token：从`@BotFather`获取，输入内容会直接显示。
2. 主人用户ID：你自己的Telegram数字ID。
3. 报表群ID：接收日报、周报和月报的群，通常以`-100`开头。
4. 源频道ID：Bot监听的频道，通常以`-100`开头；多个频道用英文逗号分隔。

报表群和源频道也可以填写Telegram用户名，但不能填写`1`这类正数。

### 自动化参数

指定版本安装：

```bash
curl -fsSL https://raw.githubusercontent.com/suzijin876-lgtm/slowlink-assistant-bot/main/install.sh | sudo bash -s -- --version 0.1.17
```

直接更新已安装版本：

```bash
curl -fsSL https://raw.githubusercontent.com/suzijin876-lgtm/slowlink-assistant-bot/main/install.sh | sudo bash -s -- --update
```

当前公开仓库无需配置GitHub Token。

## 文档

- [功能说明](docs/FEATURES.md)
- [运维说明](docs/OPERATIONS.md)
- [版本归档](docs/VERSION_ARCHIVE.md)
- [更新日志](CHANGELOG.md)

版本安装包统一发布到[GitHub Releases](https://github.com/suzijin876-lgtm/slowlink-assistant-bot/releases)，不再放进仓库根目录。

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

安装后也可使用：

```bash
sudo /opt/slowlink_assistant_bot/manage.sh status
sudo /opt/slowlink_assistant_bot/manage.sh logs
sudo /opt/slowlink_assistant_bot/manage.sh update
sudo /opt/slowlink_assistant_bot/manage.sh backup
```
