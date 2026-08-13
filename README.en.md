<p align="center">
  <img src="plugins/mjtutor/assets/logo.svg" alt="MJTutor" width="120">
</p>

<h1 align="center">MJTutor</h1>

<p align="center">
  <a href="README.md">简体中文</a> |
  <strong>English</strong> |
  <a href="README.ja.md">日本語</a>
</p>

MJTutor is a local riichi-mahjong coaching plugin for Codex with support for
four-player Mahjong Soul hanchan. It combines Mortal's action evaluations,
public game information, and a correctable long-term profile to turn a
one-off review into a coaching conversation you can continue and question.

MJTutor distinguishes game facts, Mortal outputs, rule-based reasoning, and
coaching hypotheses. It does not automatically treat every disagreement with
Mortal as a mistake.

[View the changelog](CHANGELOG.md)

## Features

- Review four-player Mahjong Soul hanchan directly in a Codex conversation.
- Use Mortal Web for remote analysis without running Mortal models locally.
- Explain key decisions using candidates, Q values, shanten, scores, rivers,
  melds, and visible tiles.
- Turn explicit feedback and recurring patterns across games into a long-term
  profile that can be confirmed, corrected, or forgotten.
- Sync public games from Koromo and select games from an interactive catalog.

## Installation

Requirements:

- macOS or Linux.
- [Codex desktop](https://developers.openai.com/codex/app) or Codex CLI.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/).

### Codex desktop

In **Plugins -> Add from GitHub**, enter:

```text
ukicey/MJTutor
```

Install **MJTutor** from the list, then start a new task to load the plugin.

### Codex CLI

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

MJTutor opens a Mortal Web page with the game URL and analysis options already
filled in. Complete Cloudflare Turnstile and submit the page yourself. After
the report is ready, MJTutor imports it and starts the review. The plugin
cannot complete this human-verification step for you.

## Game catalog

After binding a Koromo account, ask Codex:

```text
Open my MJTutor game catalog.
```

The catalog can filter games by account, placement, date, and review status.
You can refresh it manually and select a game to review. Account binding is
optional and does not affect direct review from a Mahjong Soul URL.

MJTutor identifies an account with the Koromo `account_id` you confirm and
uses nicknames only for display. Koromo data may be delayed, incomplete, or
protected by additional verification. If access is unavailable, MJTutor
continues to show records already stored locally.

## Long-term memory

Reviews, feedback, and the long-term profile are stored by default at:

```text
~/.local/share/mjtutor/coach.sqlite3
```

When `XDG_DATA_HOME` is set, the database is stored at
`$XDG_DATA_HOME/mjtutor/coach.sqlite3`. You can select another directory with
`MJTUTOR_DATA_DIR`.

Profile information is separated into three categories:

1. **Objective observations:** actual actions, Mortal recommendations, and
   evidence from the decision context.
2. **Tentative profile:** patterns suggested across multiple games that still
   need confirmation.
3. **Confirmed profile:** styles, goals, weaknesses, strengths, and teaching
   preferences you explicitly confirm or correct.

The database is separate from the plugin installation, so updates and
reinstallation do not overwrite it.

## Updating

See the [changelog](CHANGELOG.md) for version changes. To update with the CLI:

```bash
codex plugin marketplace upgrade mjtutor
codex plugin add mjtutor@mjtutor
```

Start a new task after updating so it loads the new plugin version. When the
desktop plugin page shows an update button, you can update there instead.

## Feedback

Use [GitHub Issues](https://github.com/ukicey/MJTutor/issues/new/choose) to
report a problem, suggest a feature, or comment on the coaching explanations
and profile quality. The repository provides a template for each type.

Issues are public. Do not upload `coach.sqlite3`, access keys, private game
logs, or other information you do not want to disclose. Sanitize logs and
screenshots before attaching them.

## Data and privacy

The local database may contain Mahjong Soul accounts and nicknames, Mortal
reports, game reviews, coaching notes, and profile evidence. This data is not
included in the GitHub repository or plugin package, and MJTutor does not
upload the database or profile automatically.

A Mahjong Soul game-log URL is sent to Mortal Web only when you choose that
analysis flow. Game synchronization likewise relies on Koromo as a third-party
public data service.

## License

[MIT](LICENSE)
