# Codex Skill Manager

简体中文 | [English](README.md)

一个安全优先的本地 Codex Skills 管理工具。它同时提供浏览器管理面板和确定性的命令行工具，用于盘点 Skills、查看 GitHub Stars、观察显式使用频率、检查更新、可恢复卸载与还原。

![Codex Skill Manager 管理面板](design-reference-option-2.png)

## 主要能力

- 只展示能够更新或安全卸载的本地 Skills。
- 从可操作列表中隐藏 Codex 系统 Skills 和插件托管 Skills，避免误删。
- 展示推测分类、GitHub Stars、显式 `$skill-name` 使用次数、来源与更新策略。
- GitHub 触发限流后停止继续刷新 Stars，并保留已有缓存。
- 更新、卸载和还原前都先展示预览。
- 卸载时移动到可恢复的回收目录，不永久删除文件。

## 安装

在 Codex 对话中输入：

```text
请使用 $skill-installer 安装这个 Skill：
https://github.com/simple0926/codex-skill-manager
```

也可以手动克隆：

```bash
git clone https://github.com/simple0926/codex-skill-manager.git ~/.codex/skills/codex-skill-manager
```

安装后重启 Codex，使其重新发现该 Skill。

## 打开本地管理面板

```bash
python3 panel/server.py --open
```

服务默认只绑定 `127.0.0.1`。请保持本机回环访问，因为面板具备更新和卸载本地 Skills 的能力。

## 使用命令行

```bash
python3 scripts/skill_manager.py inventory
python3 scripts/skill_manager.py inventory --refresh-stars
python3 scripts/skill_manager.py update <skill-name>
python3 scripts/skill_manager.py uninstall <skill-name>
python3 scripts/skill_manager.py restore <trash-id>
```

更新、卸载和还原命令默认只预览；必须同时提供 `--apply` 与 `--yes` 才会执行。请始终先检查预览中的真实路径。

## GitHub API 限额

GitHub 匿名 API 的额度较低。可以在启动面板的环境中设置 `GITHUB_TOKEN` 或 `GH_TOKEN`，使用登录账号的额度。不要把 Token 写入本仓库或任何浏览器端代码。

## 使用频率的统计边界

`usage_30d`、`usage_90d` 和 `usage_all` 统计本地 Codex 对话历史中明确出现的 `$skill-name`。它无法统计隐式调用，只能作为复核信号，不能直接证明某个 Skill 没有被使用。

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
node --check panel/static/app.js
```

运行时仅使用 Python 标准库。

## 安全模型

- 除非明确提供 `--allow-non-loopback`，否则面板只允许本机回环访问。
- 每次修改都要求服务器生成新的预览，并输入页面显示的确认短语。
- 系统与插件托管 Skills 受到保护。
- 遇到脏仓库、名称歧义或来源不明时直接阻止更新。
- 卸载可恢复。

## 发布说明

参见[中文版发布说明](RELEASE_NOTES.zh-CN.md)。首个公开版本为 `v1.0.0`。

