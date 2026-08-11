# MJTutor

一个只在本机运行的个人日麻复盘项目：`mjai-reviewer + Mortal` 提供结构化牌谱分析，ChatGPT/Codex 通过 MCP 查询证据，再由项目 Skill 组织成可追问、可积累的教学对话。

## 当前范围

- 雀魂四人段位场牌谱
- 只支持半庄，即南风局
- 输入为雀魂牌谱链接或导出的 `tenhou.net/6` 兼容 JSON
- 牌谱屋（Koromo）是正式的账号标识与段位场牌局目录来源
- Mortal 负责动作评价；ChatGPT 不在本项目中调用额外 API
- 牌谱、复盘和个人反馈只保存在本机 SQLite
- 暂无 GUI、远程服务和商业化部署

代码不会修改 Mortal，也不会假定 Mortal 能解释自己的内部原因。它只保存 Mortal 实际提供的候选动作、Q 值、概率、向听数和局面状态。教练解释必须区分牌谱事实、Mortal 输出、规则推导与教练推测。

## 组成

```text
牌谱屋账号与雀魂牌谱链接 / 雀魂导出 JSON
    -> mjai-reviewer --json
    -> Mortal
    -> 本地 SQLite
    -> MJTutor MCP
    -> ChatGPT/Codex + coach-mahjong-soul Skill
```

我们直接利用 `mjai-reviewer --json` 的结构化结果。它已经包含每个决策的实际动作、Mortal 推荐动作、候选动作、Q 值、概率、向听数和手牌状态，因此第一版不需要修改 Mortal 本体。MJTutor 还会重放报告中的 `mjai_log`，为单个决策补充分数、宝牌、牌河、副露、立直状态以及从目标玩家视角计算的可见与未见枚数。

决策上下文严格停在实际动作发生前：只统计目标玩家手牌和当时已经公开的牌，不读取对手暗牌或后续事件。`unseen_tile_counts` 表示“玩家未看见的牌”，不代表这些牌确定仍在牌山。

## 本地主人与牌谱屋账号

每份 MJTutor 安装只服务一个本地主人，不提供用户表、登录、切换用户或按用户隔离画像。这个主人可以绑定一个或多个雀魂账号；每个账号使用“当前昵称 + 牌谱屋 `account_id`”展示。昵称可以重复或变化，因此只用于搜索和显示；首次绑定必须由用户确认牌谱屋搜索结果，系统会保存昵称历史，不会凭同名自动认领账号。

雀魂牌谱链接中的 `_a...` 查看者参数可以还原为牌谱屋 `account_id`。当该账号已经确认绑定时，新导入的 Mortal 报告会自动记录账号来源；旧报告也会在绑定账号时回填来源。无论账号是否已绑定，用户主动导入的目标座位都属于本地主人，决策观察和长期画像可以立即使用。无法可靠识别的本地导出只会缺少账号来源，不需要再绑定到某个“玩家”。

```bash
uv run mjtutor account-bind '昵称' 1234567
uv run mjtutor profile
```

牌谱屋是第三方且不是实时数据源。目前项目已完成身份绑定和牌谱链接识别；按账号增量同步金、玉、王座段位场牌局的 Provider 是下一层工作。同步不会登录或侵入雀魂客户端，也不会把整份牌局目录交给 LLM。

## 长期记忆

长期记忆以本地 SQLite 为准，不依赖 ChatGPT 会话历史，分成三层：

1. **客观观察**：每个已绑定复盘的决策、实际与 Mortal 动作、排名、Q 差、局面索引及 `model_tag`。它们不是自动判定的缺点。
2. **暂定画像**：跨多场重复后由教练提出的、带置信度和适用场景的假设，同时保存支持案例与反例。
3. **确认画像**：用户明确确认或纠正的风格、弱点、优势、目标、疑问、已理解内容和教学偏好。

画像条目支持确认、纠正、否认和遗忘。否认项默认不会进入后续教练上下文；遗忘会从本地数据库删除条目及其证据。`get_local_profile` 默认只返回紧凑聚合，ChatGPT 需要证明某个判断时才通过 `review_id + decision_id` 获取完整局面，以控制 token 使用。

## 开发环境

项目使用 `uv`，Python 版本要求为 3.11 或更高：

```bash
cd /Users/tongqi/pythonprojects/MJTutor
UV_CACHE_DIR=/private/tmp/mjtutor-uv-cache uv sync
UV_CACHE_DIR=/private/tmp/mjtutor-uv-cache uv run pytest
```

检查当前外部引擎配置：

```bash
uv run mjtutor setup
```

## 接入 Mortal

项目刻意把 Mortal 当成外部程序。需要另外准备：

1. [`Equim-chan/Mortal`](https://github.com/Equim-chan/Mortal) 及可用权重。
2. [`Equim-chan/mjai-reviewer`](https://github.com/Equim-chan/mjai-reviewer) 可执行文件。
3. Mortal 的启动文件和 `config.toml`。

根据 `.env.example` 设置三个环境变量：

```bash
export MJTUTOR_REVIEWER_BIN=/absolute/path/to/mjai-reviewer
export MJTUTOR_MORTAL_EXE=/absolute/path/to/Mortal/mortal/mortal
export MJTUTOR_MORTAL_CONFIG=/absolute/path/to/Mortal/mortal/config.toml
```

Mortal 源码使用 AGPL-3.0-or-later，`mjai-reviewer` 使用 Apache-2.0。本仓库目前只通过进程调用它们，不复制源码或模型权重。

## 导出与分析牌谱

`mjai-reviewer` 的[雀魂本地牌谱指南](https://github.com/Equim-chan/mjai-reviewer/blob/master/mjsoul.adoc)说明了如何在雀魂牌谱页面导出兼容 JSON。导出文件后先验证：

```bash
uv run mjtutor inspect /path/to/majsoul-log.json
```

`seat` 是东一局座位：东家为 `0`，其下家为 `1`，对家为 `2`，上家为 `3`。

```bash
uv run mjtutor review /path/to/majsoul-log.json --seat 0
uv run mjtutor list
uv run mjtutor summary REVIEW_ID
```

牌谱格式本身不总能可靠区分段位场和友人场。当前版本验证四麻与半庄；“段位场”先作为导入来源约束，后续拿到真实雀魂样本后再补充严格识别。

## 远程 Mortal Web

Mortal 在线站可以直接接收雀魂分享链接，并在远端完成推理。它没有公开提交 API，而且使用 Cloudflare Turnstile，因此 MJTutor 不会模拟、破解或外包验证码。当前提供安全的半自动流程：

1. 调用 MCP 工具 `prepare_mortal_web_review`，传入雀魂 `paipu` 链接。
2. MJTutor 返回已填入牌谱链接的 Mortal Web 地址。
3. 在页面确认模型和局筛选，人工完成一次 Turnstile 并提交。
4. 将生成的 `/report/*.html` 或 `/report/*.json` 地址交给 `import_mortal_web_report`。
5. 结构化结果进入和本地 Mortal 完全相同的查询、解释和个人档案流程。

直接在项目中输入牌谱链接：

```bash
uv run mjtutor web-prepare 'https://game.maj-soul.com/1/?paipu=...'
uv run mjtutor web-import 'https://mjai.ekyu.moe/report/....html' 'https://game.maj-soul.com/1/?paipu=...'
```

这条路线几乎不占本地推理算力，但不能无人值守。真正的全自动远程 Provider 需要一个明确允许程序调用的推理 API；目前没有找到可依赖的免费公共端点。

## MCP 与 Skill

项目级 MCP 配置位于 `.codex/config.toml`，新打开该项目的 Codex 任务后会启动 `mjtutor`。Skill 位于：

```text
.agents/skills/coach-mahjong-soul/
```

典型对话：

```text
用 $coach-mahjong-soul 复盘这份雀魂半庄牌谱，先找出三个最值得讨论的决策。
```

首次运行 MCP 前仍需完成 `uv sync`。当前 OpenAI Docs 网页和官方文档 MCP 端点在本机均返回 403；本项目配置依据本机 Codex 随附的 MCP 集成说明和 MCP Python SDK 2.0 接口编写。

## 数据位置

默认数据库为 `data/coach.sqlite3`，已排除在 Git 之外。它保存：

- 本地主人的牌谱屋账号 ID、当前昵称与昵称历史
- 复盘报告原始 JSON
- 从 `mjai_log` 按需重建的决策时点公开桌面状态
- 牌谱哈希与本地路径
- 目标玩家座位
- 可分页检索的客观决策观察
- 暂定与确认画像、支持证据和反例
- 教练明确记录的错误、风格偏好、疑问和已理解事项

不会上传牌谱，也不会把少量标注直接宣称为稳定打法特征。
