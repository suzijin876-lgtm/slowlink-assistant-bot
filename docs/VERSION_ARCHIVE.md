# 发布与归档

当前版本：`0.1.25`

## GitHub Releases

从V0.1.15起，版本包不再提交到Git仓库根目录，统一保存在：

[SlowLink Assistant Bot Releases](https://github.com/suzijin876-lgtm/slowlink-assistant-bot/releases)

每个Release在线包含：

```text
slowlink_assistant_bot_app_vX_Y_Z.zip
slowlink_assistant_bot_vX_Y_Z_full.zip
SHA256SUMS.txt
```

本地版本归档额外保留`slowlink_assistant_bot_vX_Y_Z_update_log.txt`，用于生成Release中文正文。

## 历史记录

- 所有版本功能说明统一保存在根目录`CHANGELOG.md`。
- V0.1.0至V0.1.14的旧压缩包保存在开发机仓库外的`slowlink_assistant_bot_releases`目录。
- 初始Git提交仍保留旧版本目录的完整历史，需要时可通过Git恢复。

## 发布规则

- `main`只保存当前源码和文档。
- 版本号同时更新`VERSION`和`assistant_bot/__init__.py`。
- 推送`vX.Y.Z`标签后，GitHub Actions运行测试并自动创建Release。
- 自动发布先生成四个本地归档文件，线上只上传两个ZIP和`SHA256SUMS.txt`。
- `.env`、数据库、日志和服务器凭据永远不进入Git或Release。
