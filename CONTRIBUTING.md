# Contributing to jev-ultrafast (ARC fork)

For people and agents. Read this whole file before your first change here.
Shared ARC rules (tasks, branches, PRs, secrets, release): [ARC contribution handbook](https://github.com/arc-web/agent-config/blob/main/handbook/HANDBOOK.md).

This repository is a **public** fork of [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast).
Anyone can read it. The upstream project's own guide is [README.md](README.md) and [AGENTS.md](AGENTS.md);
this file only adds how ARC works in the fork.

## At a glance

| | |
|---|---|
| What this repo is | ARC's fork of the Jev Ultrafast browser agent: one goal in, the model picks an operation and an observed element each step |
| Owner and approver | Johan approves routine changes. Mike decides rule changes he approved, budget, and new agents |
| Runs live at | ARC's agent server, where the ARC runner (`scripts/arc_browser_run.py`) drives a local Chrome for ARC's agents |
| A merge reaches live by | Never automatically. A person installs a chosen merged commit on the agent server, with Johan's approval |
| Test command | `uv run ruff check . && uv run pytest && node --check jev_ultrafast/static/app.js && node --check jev_ultrafast/snapshot.js` |
| Task tracking | ARC's internal task tracker. Do not link it from this public repo |

## Quick start for agents

1. Read the ARC task and its comments. No task, no change (ask a person to create one).
2. Claim the work so nobody else takes it (HANDBOOK, "Claim before you change").
3. Branch from the latest `main` of `arc-web/jev-ultrafast`: `<type>/<short-slug>`, for example `fix/scroll-step`.
4. Make the smallest change that meets the task's acceptance. Follow the loop rules in [AGENTS.md](AGENTS.md).
5. Run the test command. Paste the result into the PR.
6. Open the PR against **`arc-web/jev-ultrafast`**, not upstream: `gh pr create --repo arc-web/jev-ultrafast`.
   Fill in the template. Refer to the task by its key only; no internal links.
7. After approval and merge: the approved commit is installed on the agent server and one real goal is run
   through the ARC runner. Report the result on the task.
8. Comment on the task with the PR, the live check, and what is left.

## Quick start for people

Tell an agent what the browser agent gets wrong or should do, with the web page and the goal you gave it.
The agent reproduces it offline where it can, changes the smallest part of the loop, and opens a PR here.
You get a PR link with test results, and after install, the outcome of one real run of that goal.

## What belongs here

| Change | Home |
|---|---|
| The browser loop, model calls, DOM snapshot, executor, inspector | this repo |
| ARC's chooser route (`jev_ultrafast/chooser_openrouter.py`, `jev_route()` in `model.py`) and the ARC runner (`scripts/arc_browser_run.py`) | this repo |
| When and how ARC's agents call the browser, their instructions and skills | ARC's private agent repos, not here |
| Server setup, credentials, schedules | ARC's private deployment docs, not here |
| A fix that helps everyone | this repo first, then offer it upstream as a separate PR to `browser-use/jev-ultrafast` |

## Layout

```text
jev_ultrafast/
  agent.py              the whole loop: observe, choose, execute, log
  model.py              operation and target questions, text helper, jev_route() (ARC: which endpoint answers)
  chooser_openrouter.py ARC: the same questions answered by one OpenAI-compatible call
  browser.py            browser connection, geometry, execution
  snapshot.js           atomic DOM snapshot and indexed controls
  questions.py          model instructions
  demo.py               local inspector (`uv run jev`)
  static/               inspector page, script, styles and a test fixture
examples/               flights.py and run.py (live, paid model calls)
scripts/
  arc_browser_run.py    ARC: run one goal against a local Chrome and write a trace
  check_guards.py       real controls in a local browser, no model calls
  smoke.py, measure_*, record_*, render_*   measurement and demo tools (most make paid calls)
tests/test_agent.py     offline tests, no network, no paid calls
docs/                   performance evidence, design notes, demo media
```

## Set up and test

Needs [uv](https://docs.astral.sh/uv/), Python 3.12 or newer, and Node.js for the syntax checks.

```bash
gh repo clone arc-web/jev-ultrafast
cd jev-ultrafast
uv sync
uv run ruff check .
uv run pytest
node --check jev_ultrafast/static/app.js
node --check jev_ultrafast/snapshot.js
uv build
```

Tests are offline and must stay that way. `uv run python scripts/check_guards.py` checks real controls in a
local browser without model calls. Examples, `smoke.py`, measurement and recording scripts make paid calls:
run them only when the task needs it.

Known state on 2026-09-28: `uv run pytest` passes (32 tests). `uv run ruff check .` reports 10 findings in
ARC-added code (import order, one unused import, long lines in `browser.py`, `chooser_openrouter.py` and
`scripts/arc_browser_run.py`). Do not add new ones.

There is no CI workflow in this repo yet. Run the checks yourself and paste the output in the PR.

## Making a change

- Keep the loop small and general. No site-specific plans, field values, selectors or code from the model.
- Keep ARC-only behavior switchable by environment variable, so the upstream default path still works.
  Example: `CHOOSER_MODEL` starting with `typesafe/` routes decisions through OpenRouter; without it, the
  TypeSafe endpoint and `TYPESAFE_API_KEY` are used as upstream intends.
- Keep ARC notes in `CONTRIBUTING.md` and `AGENTS.md` only. Do not edit `README.md` or `docs/` for ARC
  reasons: that is upstream's text and a merge conflict later.
- Commit messages: `<type>: <what changed>`, for example `fix: never call a failed form step done`.

## Release and rollback

| Layer | Here |
|---|---|
| Dev | A branch in your own clone or worktree |
| Test | The test command above, offline, with no paid calls |
| Staging | None yet. A dry run is one real goal through the ARC runner before the commit is used by agents |
| Production | A merged commit of `main`, installed on ARC's agent server and checked with one real goal |

**Deploy.** A person installs the approved merged commit on ARC's agent server following ARC's private
runbook. Copy files from the git commit, not from a Windows working copy (line endings change).

**Prove it landed.** Run one real goal through the ARC runner and read the trace. A `DONE` choice is not proof:
check the page outcome on its own. Record the installed commit on the task.

**Undo it.** Revert the PR, then install the previous good commit the same way.

**Staying in step with upstream.** Pull upstream changes on their own branch:

```bash
git remote add upstream https://github.com/browser-use/jev-ultrafast.git   # once
git fetch upstream
git switch -c chore/upstream-sync origin/main
git merge upstream/main
uv run pytest
```

Open that as its own PR here. Never mix an upstream sync with an ARC change.

## Rules that are easy to break

- **This repo is public.** No internal hostnames, server paths, task links, channel names, client names or
  people's roles beyond names. Put those in ARC's private repos.
- **PRs go to `arc-web/jev-ultrafast`.** `gh pr create` in a fork can default to upstream; always pass `--repo arc-web/jev-ultrafast`.
- **Never retry a browser mutation.** Log execution before observing the result (see [AGENTS.md](AGENTS.md)).
- **Never call a failed form step done.** A `DONE` choice needs an independent outcome check.
- **Tests never call paid APIs.** Anything that needs a key belongs in `examples/` or `scripts/`, not `tests/`.
- **Keep keys out of the repo.** `.env` stays ignored; `.env.example` holds names only.
- **Merged is not live.** Nothing deploys by itself; the agent server keeps its installed commit until someone installs a new one.

## Secrets

Names only, never values. Local runs read `TYPESAFE_API_KEY` and `TEXT_MODEL_API_KEY` from an ignored `.env`
(see `.env.example`). The ARC runner reads its OpenRouter key from ARC's secret store at run time and never
prints or writes it. On ARC's side the default chooser is TypeSafe's Jev (`typesafe/jev-1.13`) through
OpenRouter; set it with `--chooser-model` or `JEV_CHOOSER_MODEL`.

## Getting help

- ARC people and agents: ask Johan on the ARC task.
- Upstream behavior and design: [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast) and
  [TypeSafe docs](https://docs.typesafe.ai/introduction).
