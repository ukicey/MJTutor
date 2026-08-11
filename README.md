# MJTutor

MJTutor 是一个本地运行的日麻复盘教练。Mortal 负责评估牌谱中的动作，Codex 通过 MCP 读取结构化证据，再由项目 Skill 把结果组织成可以追问、能够积累长期画像的教学对话。

> 当前状态：个人 MVP。四麻半庄的导入、Mortal Web 报告、决策查询、本地记忆和画像流程已经可用；远程推理仍需人工通过 Turnstile，牌谱屋自动同步尚未实现。

## 功能

- 支持雀魂四人半庄牌谱链接和 `tenhou.net/6` 兼容导出 JSON。
- 支持 Mortal Web 远程推理，不需要在本机运行模型。
- 支持本地 `mjai-reviewer + Mortal`，适合已经准备好模型和权重的用户。
- 保存 Mortal 候选动作、Q 值、概率、向听数和模型版本。
- 重放 `mjai_log`，补充决策前的分数、宝牌、牌河、副露、立直状态和可见牌统计。
- 使用本地 SQLite 保存复盘、客观观察、明确反馈和可纠正的长期画像。
- 单机单主人；一份安装可以绑定多个雀魂账号，但没有登录和多用户系统。

MJTutor 不会把 Mortal 的动作偏好直接称为错误，也不会声称 Mortal 能解释自己的内部原因。教练输出需要区分牌谱事实、Mortal 输出、规则推导和教练推测。

## 运行方式

当前推荐在 **Codex 桌面端或 Codex CLI 的本地项目任务**中使用。仓库内包含：

- `.codex/config.toml`：启动本地 `mjtutor` MCP。
- `.agents/skills/coach-mahjong-soul/`：复盘与长期记忆工作流。

普通 ChatGPT 对话不会自动读取你电脑上的仓库，也不能直接启动本地 MCP。这个项目目前不是远程 ChatGPT App 或托管服务。

## 快速开始

### 1. 安装环境

需要：

- Python 3.11 或更高版本。
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)。
- Codex 桌面端或 Codex CLI。

克隆并安装依赖：

```bash
git clone https://github.com/ukicey/MJTutor.git
cd MJTutor
uv sync
uv run pytest
```

测试通过后，检查运行状态：

```bash
uv run mjtutor setup
```

### 2. 在 Codex 中打开项目

在 Codex 中把克隆得到的 `MJTutor` 目录作为本地项目打开，然后新建一个任务。首次使用项目配置时，Codex 可能要求你信任仓库或允许启动 MCP。

确认工具可用后，可以直接发送：

```text
用 $coach-mahjong-soul 复盘这份雀魂四麻半庄牌谱：
https://game.maj-soul.com/1/?paipu=...
```

也可以先问：

```text
检查 MJTutor 是否已经配置好，不要开始牌局教学。
```

### 3. 使用 Mortal Web

这是默认推荐路线，不需要下载 Mortal 权重，也几乎不占本地推理算力。

1. 把雀魂 `paipu` 链接发给 Codex。
2. MJTutor 调用 `prepare_mortal_web_review`，生成预填的 Mortal Web 页面。
3. 在浏览器中人工完成 Cloudflare Turnstile 并提交。
4. 把生成的 `/report/*.json` 或 `/report/*.html` 地址发回 Codex。
5. MJTutor 调用 `import_mortal_web_report`，保存结构化报告。
6. 让教练先选最多三个最值得讨论的决策，再按需展开。

MJTutor 不会绕过、破解或外包 Turnstile。Mortal Web 也没有可依赖的公开提交 API，因此这一步不能无人值守。

## 绑定本地账号

绑定账号是可选项。没有绑定账号也可以导入牌谱、建立观察和使用长期画像。

```bash
uv run mjtutor account-bind '雀魂昵称' 12345678
uv run mjtutor profile
```

这里的数字是雀魂稳定的 `account_id`。昵称可能重复或变化，只用于显示和记录历史。

牌谱链接中的 `_a...` 是经过编码的账号参数，表示该链接指定的账号或查看视角；它不一定就是被复盘玩家。MJTutor 只有在它与已经确认的本地账号一致时，才会把它作为账号来源，不会凭昵称或链接自动认领身份。

牌谱屋（Koromo）目前主要覆盖金、玉、王座段位场，数据可能延迟或不完整。未被牌谱屋收录不代表雀魂账号没有 `account_id`。

## 本地 Mortal

已经准备好 Mortal 的用户可以使用完全本地的分析路线。需要另外安装：

1. [`Equim-chan/Mortal`](https://github.com/Equim-chan/Mortal) 及可用权重。
2. [`Equim-chan/mjai-reviewer`](https://github.com/Equim-chan/mjai-reviewer) 可执行文件。
3. Mortal 启动文件和 `config.toml`。

复制 `.env.example` 中的变量并按本机路径设置：

```bash
export MJTUTOR_REVIEWER_BIN=/absolute/path/to/mjai-reviewer
export MJTUTOR_MORTAL_EXE=/absolute/path/to/Mortal/mortal/mortal
export MJTUTOR_MORTAL_CONFIG=/absolute/path/to/Mortal/mortal/config.toml
```

先检查雀魂导出文件：

```bash
uv run mjtutor inspect /path/to/majsoul-log.json
```

`seat` 是东一局座位：东家为 `0`，其下家为 `1`，对家为 `2`，上家为 `3`。

```bash
uv run mjtutor review /path/to/majsoul-log.json --seat 0
uv run mjtutor list
uv run mjtutor summary REVIEW_ID
uv run mjtutor decision REVIEW_ID DECISION_ID
```

雀魂本地导出方法参见 `mjai-reviewer` 的[雀魂牌谱指南](https://github.com/Equim-chan/mjai-reviewer/blob/master/mjsoul.adoc)。

## 长期记忆

长期记忆以本地 SQLite 为准，不依赖某一次聊天记录，分为三层：

1. **客观观察**：实际动作、Mortal 推荐、候选排名、Q 差、局面索引和 `model_tag`。它们不是自动判定的缺点。
2. **暂定画像**：跨多场重复后提出的、带置信度和适用场景的假设，同时保存支持案例和反例。
3. **确认画像**：用户明确确认或纠正的风格、弱点、优势、目标、疑问、已理解内容和教学偏好。

画像条目支持确认、纠正、否认和遗忘。否认项默认不会进入后续教练上下文；遗忘会删除本地条目及其证据。

## 数据与隐私

默认数据库位于：

```text
data/coach.sqlite3
```

`data/`、`.env`、`models/`、虚拟环境和缓存均被 Git 忽略。MJTutor 不会主动上传牌谱、数据库或画像；只有用户明确选择的 Mortal Web 分析会把相应牌谱链接交给第三方站点。

数据库保存：

- 本地账号、当前昵称和昵称历史。
- Mortal 原始报告 JSON。
- 复盘及决策前公开桌面状态。
- 可分页检索的客观决策观察。
- 暂定与确认画像、支持证据和反例。
- 用户明确确认的错误、偏好、疑问和已理解事项。

## 常用命令

```bash
uv run mjtutor --help
uv run mjtutor setup
uv run mjtutor profile
uv run mjtutor list
uv run mjtutor web-prepare 'https://game.maj-soul.com/1/?paipu=...'
uv run mjtutor web-import 'https://mjai.ekyu.moe/report/example.json' 'https://game.maj-soul.com/1/?paipu=...'
```

## 故障排查

### Codex 中没有出现 MJTutor 工具

1. 在仓库目录运行 `uv sync`。
2. 确认 `uv run mjtutor setup` 可以执行。
3. 关闭旧任务，并从 MJTutor 项目中新建任务，让项目级 MCP 重新加载。
4. 如果 Codex 找不到 `uv`，把 `.codex/config.toml` 中的 `command` 改为本机 `uv` 的绝对路径。

### Mortal Web 无法自动提交

这是预期行为。页面要求人工完成 Turnstile，MJTutor 只负责生成提交地址和导入最终报告。

### 本地 Mortal 超时

可以提高 `MJTUTOR_TIMEOUT_SECONDS`。完整半庄在 CPU 上可能耗时较长，模型权重也不会随本仓库下载。

## 当前限制

- 只支持雀魂四人半庄；牌谱格式不总能可靠区分段位场与友人场。
- 牌谱屋自动检索和增量同步尚未实现。
- Mortal Web 需要人工验证。
- 不提供 GUI、自动雀魂登录、实时对局辅助或远程托管服务。
- Mortal 和 `mjai-reviewer` 是外部项目，本仓库不包含源码或模型权重。

## 开发

```bash
uv sync
uv run pytest
uv run python -m compileall -q src tests
```

Mortal 使用 AGPL-3.0-or-later，`mjai-reviewer` 使用 Apache-2.0。本仓库只通过进程调用它们。

## 许可证

本仓库暂未添加开源许可证。公开可见不等于授予复制、修改或再发布许可；正式发布前应选择合适的许可证。
