# Manual flow: one feature end to end, by hand

Until the dispatcher (stage 4) exists, you play the dispatcher: you start each agent run, push
its commit, read CI and the reviewer, and decide the next step. This is the same loop stage 4
will automate, so running it by hand is also the acceptance test for stage 4's design.

Each step ends with **Check**: what you should see before moving on.

## 0. Once per machine

```bash
uv tool install specify-cli==1.4.1
uv tool install --editable ~/git/met/software-factory-1      # the `factory` command
cd ~/git/met/software-factory-1 && make images                # local runner images (arm64 on a Mac)
```

The token must be in the shell that runs `factory agent`. `~/.zshenv` is read by every zsh,
`~/.zshrc` only by interactive ones:

```bash
claude setup-token                                            # copy the sk-ant-oat... token
echo "export CLAUDE_CODE_OAUTH_TOKEN='sk-ant-oat...'" >> ~/.zshenv && chmod 600 ~/.zshenv
```

Never set `ANTHROPIC_API_KEY`: the runner refuses to start with it.

**Check:** `factory --help` works, `docker images | grep runner-python` shows the current
version (`grep ^version pyproject.toml`), and `echo ${CLAUDE_CODE_OAUTH_TOKEN:+set}` prints `set`.

## 1. Create the product

Skip to step 3 to reuse `software-factory-product-1` with a new feature.

```bash
mkdir ~/git/met/my-product && cd ~/git/met/my-product && git init -b main
factory init --factory-repo sligokid/software-factory-1
claude                                                        # then: /factory-setup
```

`/factory-setup` asks for the runner, `setup` and `verify`, and the stack. Then edit
`.factory/factory.yaml` by hand where needed:

- `setup` must succeed **before any product code exists**: the agent runs it at the start of
  phase 1 too. `pip install -r requirements.txt` fails if phase 1 is what creates the file.
- `egress`: package registries the agent needs (`pypi.org`, `files.pythonhosted.org`,
  `registry.npmjs.org`). Nothing else is reachable from the sandbox.
- `limits.commit_lines` (default 300), `protected`, and no `preview` for now.

Then, still in Claude Code: `/speckit-constitution` for the product's principles. The reviewer
judges every change against them.

Add a `.gitignore` and enough code for `verify` to pass on `main` (one placeholder test will
do: Python's unittest fails when it finds no tests).

**Check:** `factory validate` prints `ok` with no warnings, and `factory ci verify factory`
passes. (`secrets`, `sast`, `deps` need the runner image; CI runs them.)

## 2. Put it on GitHub

```bash
git add -A && git commit -m "factory init"
gh repo create sligokid/my-product --public --source . --remote origin --push
gh secret set CLAUDE_CODE_OAUTH_TOKEN -R sligokid/my-product   # paste when prompted
```

**Check:** the `factory` run on `main` is green: `gh run list -L 1`, `gh run watch`.

## 3. Write the feature (you, interactively)

```bash
claude
/factory-start docs/my-feature.md        # or a Linear issue ID; creates feature/<ID>
/speckit-clarify
/speckit-plan
/speckit-tasks
/factory-handoff
```

Keep each `## Phase N` small (one commit under `commit_lines`) and testable on its own.
`/factory-handoff` checks that, pushes the spec, opens a **draft** PR and adds the
`factory:ready` label. The label does nothing yet; you are the dispatcher.

**Check:** a draft PR exists, `tasks.md` has only unchecked `- [ ] T###` tasks, and CI on the
spec commit is green.

## 4. The phase loop

Repeat for each phase, on the feature branch:

```bash
git switch feature/<ID> && git pull
factory agent implement                  # next open phase -> one commit "<ID>: Phase N: ..."
git log --stat -1                        # read what it did
git push
gh run watch                             # checks, then the reviewer on the pushed commit
```

The run prints `ok: feature/<ID> -> <sha> (run: ~/.factory/runs/<run id>)`. Everything about
it is in that folder: `run.json` (result, turns, cost), `transcript.jsonl`, `runner.log`,
`egress.log`.

**Check:** one new commit touching only that phase's files plus `tasks.md` (its tasks now
`[X]`), CI green, and the reviewer's PR comment has no **blocking** finding.

### If CI or the review fails

`fix` replaces the last phase commit (same message) instead of adding one, so push with lease:

```bash
gh run view --log-failed > /tmp/ci.txt                        # CI failure, or
gh pr view --comments > /tmp/ci.txt                            # trim to the blocking finding
factory agent fix --feedback-file /tmp/ci.txt
git push --force-with-lease
```

Give it at most two or three tries (the dispatcher will have the same limit). If it still
fails, the phase is probably too big or the spec is unclear: fix the spec yourself or run
`/factory-replan <ID>`.

### If a run errors out

| Message | Cause |
|---|---|
| `setup failed` | `setup` cannot run yet, or needs a host missing from `egress` (see `egress.log`, `deny` lines) |
| `the agent made no changes` | the phase was already done or the agent got stuck: read `transcript.jsonl` |
| `no open phase to implement` | every phase is `[X]`: go to step 5 |
| `no specs/*/source.yaml with id <ID>` | branch name and `source.yaml` `id` disagree |
| exit at the timeout or turn limit | phase too big: split it (`--timeout`, `--max-turns` to experiment) |
| `<branch> is checked out and changed; result kept at refs/factory/runs/...` | uncommitted changes, or the branch moved during the run: clean up, then `git reset --keep refs/factory/runs/<run id>` |
| Docker `input/output error`, `ENOSPC` | disk full: `docker system df`, `docker builder prune` |

`factory replay ~/.factory/runs/<run id>` re-runs a run from the same commit and inputs; its
result goes to `refs/factory/runs/<run id>` and the branch does not move. Useful for comparing.

## 5. Converge

When every phase is `[X]`:

```bash
factory agent converge
```

It checks the whole feature against the spec without changing code. Either it reports
`converged`, or it appends a new phase to `tasks.md` as one commit: push that and go back to
step 4 for the new phase.

**Check:** the run result says `converged`.

## 6. Ready for review

```bash
gh pr ready
gh run watch                             # the reviewer on the whole PR
```

**Check:** a reviewer comment on the PR for the whole range, with no blocking finding.

If a human reviewer requests changes, put their comments in a file and:

```bash
factory agent rework --feedback-file /tmp/review.txt
git push
```

## 7. Merge

Review the PR yourself and merge it.

**Check:** the `factory` run on `main` is green, and the `pull_request: closed` run is green
(the preview job is skipped while previews are off).

## What to note while testing

Write these down; they are the inputs to stage 4:

- each decision you made between runs, and what you looked at to make it;
- every time you had to read the transcript to understand a result;
- runs per phase, fixes per phase, turns, cost and wall time (`run.json`);
- anything in the PR body or comments you wished the factory had updated for you.
