# 更新日志

本文件记录 MJTutor 各版本中对用户可见的重要变化。版本号遵循
[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

暂无。

## [0.3.0] - 2026-08-12

### 新增

- 增加已绑定账号的四麻半庄牌局增量同步和本地缓存。
- 增加 MCP App 牌局目录，支持按账号、日期、顺位和复盘状态筛选、翻页及选择牌局。
- 增加机会式自动同步：打开目录时按间隔刷新，同时保留手动刷新入口。
- 增加从目录中选择牌局并进入 Mortal Web 复盘的流程。
- 增加牌谱屋同步状态和访问验证状态提示；远端不可用时继续显示本地缓存。
- 增加问题报告、功能建议和教学反馈的 GitHub Issue 表单。

### 变更

- 将 SQLite schema 升级至 v3，使牌谱屋牌局、账号和已导入复盘建立关联。
- 牌局目录数据通过组件私有元数据传递，避免把大量记录写入模型上下文。

## [0.2.0] - 2026-08-12

### 新增

- 将 MJTutor 打包为可从 Codex marketplace 安装的正式插件。
- 增加插件清单、内置 MCP 配置、启动器和 GitHub marketplace 元数据。
- 增加 MIT 许可证和面向公开安装的使用说明。

### 变更

- 日常使用方式由“打开项目运行”改为“安装插件后在任意新任务中使用”。
- 将长期记忆和复盘数据库移至插件目录之外，默认位置为
  `~/.local/share/mjtutor/coach.sqlite3`，以便更新或重装插件时保留数据。
- 简化为单机单主人模型；一份安装仍可绑定多个雀魂账号。

### 迁移说明

- 从旧项目模式升级的用户，需要在退出旧任务后备份仓库内的
  `data/coach.sqlite3`，并将数据库迁移到 `~/.local/share/mjtutor/coach.sqlite3`。

## [0.1.0] - 2026-08-11

### 新增

- 实现首个可用的雀魂四人半庄复盘流程。
- 支持准备 Mortal Web 分析页面并导入其结构化报告，保留人工完成 Turnstile 的边界。
- 支持通过 `mjai-reviewer` 调用本地 Mortal，以及导入已有的本地复盘报告。
- 保存候选动作、Q 值、概率、向听数、模型版本和实际动作等结构化证据。
- 重放 `mjai_log`，重建决策前的分数、宝牌、牌河、副露、立直状态和可见牌统计。
- 增加决策摘要、单个决策查询和教学笔记工具。
- 增加本地 SQLite 长期记忆：客观观察、暂定画像、确认画像，以及支持和反驳证据。
- 增加雀魂账号绑定与昵称历史，并避免凭同名搜索结果或牌谱链接自动认领身份。
- 增加面向 Codex 的日麻教练 Skill，要求区分牌谱事实、Mortal 输出、规则推导和教练推测。

### 安全

- 从公开测试夹具中移除真实雀魂牌谱码。

[Unreleased]: https://github.com/ukicey/MJTutor/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/ukicey/MJTutor/compare/9dd7d5b...v0.3.0
[0.2.0]: https://github.com/ukicey/MJTutor/compare/f4946eb...9dd7d5b
[0.1.0]: https://github.com/ukicey/MJTutor/tree/f4946eb
