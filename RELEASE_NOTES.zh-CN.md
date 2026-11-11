# Codex Skill Manager v1.0.0

本地 Codex Skills 管理面板与命令行工具的首个公开版本。

## 版本亮点

- 盘点用户可管理的 Codex Skills，展示分类、来源、更新策略、GitHub Stars 与显式使用频率。
- 操作面板不展示受保护的系统 Skills 与插件托管 Skills，避免误删。
- 对 Git 来源执行仅快进更新，并保护脏仓库、歧义目标和来源不明的 Skill。
- 支持可恢复卸载和还原。
- 每次修改都要求短时有效的操作预览和明确确认短语。
- 支持 Stars 缓存、仓库级请求去重、Token 认证及 GitHub 限流后的安全停止。
- 本地服务默认只绑定回环地址。

## 验证情况

- 16 项自动化测试，覆盖命令行、面板 API、访问令牌、操作确认、系统保护、Stars 限流、更新、卸载和还原。
- 已执行面板 JavaScript 语法检查。
- 已通过 Codex `skill-creator` 结构校验。

## 已知限制

- 显式使用频率无法统计隐式 Skill 调用。
- Stars 和更新状态依赖可解析的仓库来源。
- 插件托管 Skills 需要通过插件管理器更新；Codex 系统 Skills 需要随 Codex 更新。

## 升级方式

通过 Git 安装时，使用仅快进拉取更新仓库。升级后重启 Codex。

