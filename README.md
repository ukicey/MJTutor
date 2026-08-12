# MJTutor

<p align="center">
  <strong>简体中文</strong> |
  <a href="README.en.md">English</a> |
  <a href="README.ja.md">日本語</a>
</p>

MJTutor 是一个面向 Codex 的本地日麻复盘插件。Mortal 负责评估牌谱动作，插件通过 MCP 保存结构化证据，Codex Skill 再把牌谱事实、Mortal 判断、规则推导和教练推测组织成可以追问的教学对话。

> 当前状态：个人 MVP。雀魂四麻半庄、牌谱屋本地目录、Mortal Web 报告导入、决策查询、本地记忆和可纠正画像已经可用。Mortal Web 仍需用户亲自完成 Turnstile。

[查看更新日志](CHANGELOG.md)

## 功能

- 直接在 Codex 对话中接收雀魂四人半庄牌谱链接。
- 使用 Mortal Web 远程推理，不在本机下载或运行 Mortal 权重。
- 保存候选动作、Q 值、概率、向听数和 Mortal 模型版本。
- 重放 `mjai_log`，补充决策前的分数、宝牌、牌河、副露、立直状态和可见牌统计。
- 使用本地 SQLite 保存复盘、明确反馈和可以确认、纠正、否认或遗忘的长期画像。
- 从牌谱屋增量同步公开的四麻半庄段位场元数据，在交互目录中筛选、翻页和选择牌局。
- 单机单主人；一份安装可以绑定多个雀魂账号，但没有登录或多用户系统。

MJTutor 不会把 Mortal 的偏好自动称为错误，也不会声称 Mortal 能解释自己的内部原因。

## 安装插件

需要：

- macOS 或 Linux。
- [Codex 桌面端](https://developers.openai.com/codex/app) 或 Codex CLI。
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)；第一次启动 MCP 时会用它准备 Python 3.11+ 和轻量依赖。

### 从 Codex 桌面端添加

在 **Plugins -> Add from GitHub** 中添加：

```text
ukicey/MJTutor
```

然后安装列表中的 **MJTutor**。安装完成后新建一个任务，让 Codex 加载插件的 Skill 和 MCP。日常使用不需要克隆仓库，也不需要把 MJTutor 作为项目打开。

### 使用 CLI 添加

```bash
codex plugin marketplace add ukicey/MJTutor --ref main
codex plugin add mjtutor@mjtutor
```

安装后新建一个 Codex 任务。可以先发送：

```text
检查 MJTutor 配置和已有画像，不要开始教学。
```

## 复盘一局

把雀魂牌谱链接直接发给 Codex，例如：

```text
用 MJTutor 复盘这份雀魂四麻半庄牌谱，先挑最值得讲的三个决策：
https://game.maj-soul.com/1/?paipu=...
```

默认的 Mortal Web 流程是：

1. 插件生成已经填好牌谱地址、`4.1b` 模型和中文界面的 Mortal Web 页面。
2. 用户在可见浏览器中亲自完成 Cloudflare Turnstile 并提交。
3. 插件导入生成的 `/report/*.json` 报告。
4. 教练先选择最多三个最有教学价值的决策，再按用户追问展开。

MJTutor 不会绕过、破解或外包 Turnstile。Mortal Web 没有本项目可以依赖的公开提交 API，因此这一步不能无人值守。

## 牌局目录

绑定牌谱屋账号后，可以直接对 Codex 说：

```text
打开我的 MJTutor 牌局目录。
```

目录由 MCP App 渲染，不需要把大量牌局记录放进聊天上下文。它支持账号、顺位、日期和是否已复盘筛选，也可以选择一局并进入现有 Mortal Web 流程。在暂不渲染 MCP App 的客户端，`list_koromo_games`、`sync_koromo_games` 和 `prepare_selected_game_review` 仍可单独使用。

“自动同步”采用轻量的机会式策略：打开目录时，若距离上次尝试已超过 30 分钟，就增量查询牌谱屋；也可以在目录中手动刷新。MJTutor 不安装常驻进程，不会在 Codex 未运行时后台活动，也不会把同步到的牌局自动送去 Mortal。

首次同步默认查询最近一年；后续同步会回看最近一周，避免遗漏牌谱屋延迟出现的记录。牌局按 UUID 去重并保存到 `~/.local/share/mjtutor/coach.sqlite3`。

牌谱屋目前可能要求其网页计算挑战或站方访问密钥。MJTutor 不绕过该验证；遇到时会继续显示本地缓存并报告 `verification_required`。如果站方提供访问密钥，可在启动 MCP 的环境中设置 `MJTUTOR_KOROMO_TOKEN`。直接在牌谱屋网页正常浏览仍不受 MJTutor 控制。

## 长期记忆与画像

插件记忆独立于聊天记录和插件安装目录，默认保存在：

```text
~/.local/share/mjtutor/coach.sqlite3
```

如果设置了 `XDG_DATA_HOME`，位置为 `$XDG_DATA_HOME/mjtutor/coach.sqlite3`；也可以用 `MJTUTOR_DATA_DIR` 指定目录。

数据库分为三层证据：

1. **客观观察**：实际动作、Mortal 推荐、候选排名、Q 差、局面索引和模型版本。它们不是自动判定的弱点。
2. **暂定画像**：跨多场重复后提出的、带置信度和适用场景的假设，同时保存支持案例和反例。
3. **确认画像**：用户明确确认或纠正的风格、弱点、优势、目标、疑问、已理解内容和教学偏好。

数据库位于插件之外，因此刷新 GitHub marketplace、更新或重装插件都不会覆盖画像。

### 从旧项目模式迁移

旧版数据库位于仓库的 `data/coach.sqlite3`。退出正在使用 MJTutor 的旧任务后，先备份，再迁移：

```bash
mkdir -p "$HOME/.local/share/mjtutor"
cp data/coach.sqlite3 "$HOME/.local/share/mjtutor/coach.sqlite3"
```

如果目标位置已经存在数据库，不要直接覆盖；请先分别备份，再决定保留哪一份。

## 更新插件

各版本的功能变化与迁移提示见 [更新日志](CHANGELOG.md)。

GitHub 上发布新版本后，CLI 的确定流程是：

```bash
codex plugin marketplace upgrade mjtutor
codex plugin add mjtutor@mjtutor
```

然后新建一个任务以加载新版 Skill 和 MCP。桌面端若显示更新按钮，也可以在插件页完成同一流程。

更新不会修改 `~/.local/share/mjtutor/`。插件清单使用语义化版本，发布时会同步更新版本号；当前 Codex 不会把一个正在进行的旧任务热切换到新版插件。

## 账号绑定

绑定账号是可选项。没有绑定账号也可以导入牌谱、建立观察和使用长期画像。

MJTutor 把昵称用于显示，把经过用户确认的牌谱屋 `account_id` 作为稳定标识。昵称可能重复或变化；插件不会凭同名搜索结果或牌谱链接自动认领身份。

牌谱屋目前主要覆盖金、玉、王座段位场，数据可能延迟或不完整。未被牌谱屋收录不代表雀魂账号没有 `account_id`。

## 数据与隐私

本地数据库可能包含：

- 雀魂账号、当前昵称和昵称历史。
- Mortal 原始报告 JSON。
- 复盘及决策前公开桌面状态。
- 客观决策观察、教学记录和画像证据。

这些数据不会进入 GitHub 仓库或插件包。MJTutor 不会主动上传数据库或画像；只有用户明确选择 Mortal Web 分析时，相应的雀魂牌谱链接才会交给第三方站点。

## 当前限制

- 只支持雀魂四人半庄；牌谱格式不总能可靠区分段位场与友人场。
- Mortal Web 需要人工验证。
- 牌谱屋可能延迟、不完整或要求浏览器验证；未收录不代表牌局不存在。
- 牌局目录是宿主支持时显示的 MCP App，不是独立桌面程序。
- 不提供自动雀魂登录、常驻后台进程、实时对局辅助或远程托管服务。
- 插件启动器当前面向 macOS/Linux。
- Mortal 和 `mjai-reviewer` 是外部项目，本仓库不包含其源码或模型权重。

## 开发

运行源码只保留在 `plugins/mjtutor/`。仓库根目录的 Python 工程仅用于测试和构建插件，不会让 Codex 以“项目模式”自动加载 MJTutor。

```bash
git clone https://github.com/ukicey/MJTutor.git
cd MJTutor
uv sync
uv run ruff format --check plugins/mjtutor/src tests
uv run ruff check plugins/mjtutor/src tests
uv run pytest
uv run python -m compileall -q plugins/mjtutor/src tests
```

Python 代码使用 Ruff 格式化和静态检查，统一限制为 88 列。提交修改前，可用
`uv run ruff format plugins/mjtutor/src tests` 自动格式化。

插件结构：

```text
.agents/plugins/marketplace.json
plugins/mjtutor/.codex-plugin/plugin.json
plugins/mjtutor/.mcp.json
plugins/mjtutor/assets/game-catalog.html
plugins/mjtutor/bin/mjtutor-mcp
plugins/mjtutor/skills/coach-mahjong-soul/
plugins/mjtutor/src/mjtutor/
```

Mortal 使用 AGPL-3.0-or-later，`mjai-reviewer` 使用 Apache-2.0；MJTutor 只通过网页或进程接口使用它们。

## 许可证

[MIT](LICENSE)
