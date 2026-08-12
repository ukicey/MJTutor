# MJTutor

<p align="center">
  <a href="README.md">简体中文</a> |
  <strong>English</strong> |
  <a href="README.ja.md">日本語</a>
</p>

MJTutor is a local riichi-mahjong review plugin for Codex. Mortal evaluates the
actions in a game log, the plugin stores structured evidence through MCP, and a
Codex Skill turns game facts, Mortal evaluations, rule-based reasoning, and
coaching hypotheses into an interactive lesson you can question and correct.

> Current status: personal MVP. Four-player Mahjong Soul hanchan reviews, a
> local Koromo game catalog, Mortal Web report imports, decision lookup, local
> memory, and a correctable player profile are available. Mortal Web still
> requires the user to complete Turnstile personally.

[View the changelog](CHANGELOG.md)

## Features

- Accept Mahjong Soul four-player hanchan URLs directly in a Codex conversation.
- Use Mortal Web for remote inference without downloading or running Mortal weights locally.
- Store candidate actions, Q values, probabilities, shanten, and the Mortal model version.
- Replay `mjai_log` to reconstruct scores, dora indicators, rivers, melds, riichi states, and visible-tile counts before each decision.
- Store reviews, explicit feedback, and a long-term profile that can be confirmed, corrected, rejected, or forgotten in local SQLite.
- Incrementally sync public four-player hanchan ranked-game metadata from Koromo, then filter, paginate, and select games in an interactive catalog.
- Use a single-owner local model. One installation may bind multiple Mahjong Soul accounts, but there is no login or multi-user system.

MJTutor does not automatically label every disagreement with Mortal as a
mistake, nor does it claim that Mortal can explain its own internal reasoning.

## Install the plugin

Requirements:

- macOS or Linux.
- [Codex desktop](https://developers.openai.com/codex/app) or Codex CLI.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/). On first launch, the MCP server uses it to prepare Python 3.11+ and lightweight dependencies.

### Add from Codex desktop

In **Plugins -> Add from GitHub**, enter:

```text
ukicey/MJTutor
```

Then install **MJTutor** from the list. Start a new task after installation so
Codex can load the plugin's Skill and MCP server. Normal use does not require
cloning the repository or opening MJTutor as a project.

### Add with the CLI

```bash
codex plugin marketplace add ukicey/MJTutor --ref main
codex plugin add mjtutor@mjtutor
```

Start a new Codex task after installation. A useful first prompt is:

```text
Check my MJTutor setup and existing profile without starting a coaching review.
```

## Review a game

Send a Mahjong Soul game-log URL directly to Codex, for example:

```text
Use MJTutor to review this four-player Mahjong Soul hanchan. Start with the three decisions that have the highest teaching value:
https://game.maj-soul.com/1/?paipu=...
```

The default Mortal Web flow is:

1. The plugin creates a Mortal Web page prefilled with the game-log URL, the `4.1b` model, and the selected interface language.
2. The user personally completes Cloudflare Turnstile in a visible browser and submits the form.
3. The plugin imports the generated `/report/*.json` report.
4. The coach first selects up to three decisions with the highest teaching value, then expands them as requested.

MJTutor never bypasses, solves, or outsources Turnstile. Mortal Web does not
provide a public submission API on which this project can rely, so this step
cannot run unattended.

## Game catalog

After binding a Koromo account, ask Codex:

```text
Open my MJTutor game catalog.
```

The catalog is rendered as an MCP App, so a large game list does not need to
enter the conversation context. It supports account, placement, date, and
review-status filters, and lets you select a game for the existing Mortal Web
flow. On clients that do not render the MCP App, `list_koromo_games`,
`sync_koromo_games`, and `prepare_selected_game_review` remain available as
standalone tools.

Automatic synchronization is lightweight and opportunistic. Opening the
catalog triggers an incremental query only when at least 30 minutes have
passed since the previous attempt; users can also refresh manually. MJTutor
does not install a resident process, does not run in the background while
Codex is closed, and never sends synchronized games to Mortal automatically.

The first synchronization queries the previous year by default. Later syncs
repeat the previous week to avoid missing records that appeared in Koromo with
a delay. Games are deduplicated by UUID and stored in
`~/.local/share/mjtutor/coach.sqlite3`.

Koromo may require its browser challenge or a site-owner access key. MJTutor
does not bypass that validation; it continues to show the local cache and
reports `verification_required`. If the site owner provides an access key, set
`MJTUTOR_KOROMO_TOKEN` in the MCP launch environment. Normal browsing on the
Koromo website remains outside MJTutor's control.

## Long-term memory and profile

Plugin memory is independent of chat history and the plugin installation
directory. By default, it is stored at:

```text
~/.local/share/mjtutor/coach.sqlite3
```

If `XDG_DATA_HOME` is set, the path is
`$XDG_DATA_HOME/mjtutor/coach.sqlite3`. You can also select a directory with
`MJTUTOR_DATA_DIR`.

The database separates evidence into three levels:

1. **Objective observations:** actual actions, Mortal recommendations, candidate rank, Q gap, decision context, and model version. These are not automatically treated as weaknesses.
2. **Tentative profile:** scoped hypotheses with confidence labels, proposed only after repeated behavior across games and stored with both supporting and contradicting examples.
3. **Confirmed profile:** styles, weaknesses, strengths, goals, questions, understood concepts, and teaching preferences explicitly confirmed or corrected by the user.

Because the database lives outside the plugin directory, refreshing the GitHub
marketplace, updating the plugin, or reinstalling it does not overwrite the
profile.

### Migrate from the former project mode

The old database is stored at `data/coach.sqlite3` inside the repository. After
closing any old task that is using MJTutor, back up and migrate it:

```bash
mkdir -p "$HOME/.local/share/mjtutor"
cp data/coach.sqlite3 "$HOME/.local/share/mjtutor/coach.sqlite3"
```

If a database already exists at the destination, do not overwrite it directly.
Back up both files first, then decide which copy to retain.

## Update the plugin

See the [changelog](CHANGELOG.md) for version changes and migration notes.

After a new version is published on GitHub, the deterministic CLI flow is:

```bash
codex plugin marketplace upgrade mjtutor
codex plugin add mjtutor@mjtutor
```

Then start a new task to load the updated Skill and MCP server. If the desktop
plugin page displays an update button, it performs the equivalent flow.

Updating does not modify `~/.local/share/mjtutor/`. The plugin manifest uses
semantic versions, and release versions are updated together. Codex does not
hot-swap an updated plugin into a task that is already running.

## Account binding

Account binding is optional. You can import game logs, build observations, and
use the long-term profile without binding an account.

MJTutor uses nicknames for display and uses a user-confirmed Koromo `account_id`
as the stable identifier. Nicknames may be duplicated or changed; the plugin
never claims an identity from a same-named search result or a game-log URL
without confirmation.

Koromo primarily covers Gold, Jade, and Throne ranked rooms. Its records may be
delayed or incomplete. Absence from Koromo does not mean that a Mahjong Soul
account lacks an `account_id`.

## Data and privacy

The local database may contain:

- Mahjong Soul accounts, current nicknames, and nickname history.
- Original Mortal report JSON.
- Reviews and the public table state before each decision.
- Objective decision observations, coaching notes, and profile evidence.

This data is not included in the GitHub repository or plugin package. MJTutor
does not upload its database or profile. A Mahjong Soul game-log URL is sent to
a third-party site only when the user explicitly chooses Mortal Web analysis.

## Current limitations

- Only four-player Mahjong Soul hanchan is supported. The game-log format cannot always distinguish ranked games from friendly games reliably.
- Mortal Web requires human verification.
- Koromo may be delayed, incomplete, or protected by browser verification; a missing record does not prove that a game did not occur.
- The game catalog is an MCP App shown by compatible hosts, not a standalone desktop application.
- MJTutor does not provide automated Mahjong Soul login, a resident background process, live-game assistance, or remotely hosted services.
- The plugin launcher currently targets macOS and Linux.
- Mortal and `mjai-reviewer` are external projects; this repository does not include their source code or model weights.

## Development

Runtime source is kept only under `plugins/mjtutor/`. The Python project at the
repository root exists for testing and building the plugin; it does not make
Codex load MJTutor automatically in project mode.

```bash
git clone https://github.com/ukicey/MJTutor.git
cd MJTutor
uv sync
uv run ruff format --check plugins/mjtutor/src tests
uv run ruff check plugins/mjtutor/src tests
uv run pytest
uv run python -m compileall -q plugins/mjtutor/src tests
```

Python code is formatted and linted with Ruff at an 88-column limit. Before
submitting changes, run `uv run ruff format plugins/mjtutor/src tests` to apply
the formatter.

Plugin layout:

```text
.agents/plugins/marketplace.json
plugins/mjtutor/.codex-plugin/plugin.json
plugins/mjtutor/.mcp.json
plugins/mjtutor/assets/game-catalog.html
plugins/mjtutor/bin/mjtutor-mcp
plugins/mjtutor/skills/coach-mahjong-soul/
plugins/mjtutor/src/mjtutor/
```

Mortal is licensed under AGPL-3.0-or-later and `mjai-reviewer` under
Apache-2.0. MJTutor interacts with them only through web or process interfaces.

## License

[MIT](LICENSE)
