---
name: "factory-handoff"
description: "Hand a finished spec and task list to the factory: analyze, run handoff checks, commit, push, open the draft PR and move the Linear issue to Ready for agent."
user-invocable: true
disable-model-invocation: true
---

## Context

Run this on a `feature/<ISSUE>` branch after `/speckit-tasks`. After handoff the factory
implements every phase of `tasks.md` on this branch, one commit per phase, and the developer's
next step is reviewing the single PR.

## Steps

1. **Locate the feature.**
   - Current branch must match `feature/<ISSUE>`; otherwise stop. `<ISSUE>` is the part after
     `feature/`.
   - The spec directory is the one `specs/*/` folder added on this branch
     (`git diff --name-only origin/main...HEAD -- specs/` plus untracked files under `specs/`).
     Exactly one is allowed; otherwise stop and explain.

2. **Analyze.** Invoke the `speckit-analyze` skill. If it reports any CRITICAL or HIGH issue,
   list them, stop, and suggest fixing them with the relevant Spec Kit command.

3. **Handoff checks.** Check every item and report all failures together:
   - `spec.md`, `plan.md` and `tasks.md` exist in the spec directory.
   - No `[NEEDS CLARIFICATION` text remains in any file in the spec directory.
   - `spec.md` names exactly one slice, and it matches the issue's slice.
   - `tasks.md` is organised as `## Phase N: ...` sections with `- [ ] T### ...` tasks, and no
     task is already checked.
   - Each phase is independently testable and, by your estimate, fits in one commit of at most
     300 changed lines (see `factory/limits.toml`). For each phase print: phase name, task
     count, estimated changed lines. Any phase over the limit is a failure: suggest a split.
   - No files outside `specs/` are changed on this branch.
   - `make all` passes.
   If anything fails, stop without committing.

4. **Commit and push.**
   ```bash
   git add specs/<dir>
   git commit -m "<ISSUE>: spec, plan and tasks"
   git push -u origin feature/<ISSUE>
   ```

5. **Open the draft PR** with `gh pr create --draft --base main --head feature/<ISSUE>`:
   - Title: `<ISSUE>: <issue title>`
   - Body:
     ```
     Linear: <issue url>
     Spec: specs/<dir>
     Slice: <slice>

     ## Phases
     | Phase | Tasks | Est. lines | Commit | CI |
     |-------|-------|------------|--------|----|
     | Phase 1: ... | T001-T004 | ~120 | pending | pending |

     ## Status
     Handed to the factory. This PR will be marked ready for review when every phase is
     implemented and speckit-converge reports converged.

     <!-- factory:spec=specs/<dir> issue=<ISSUE> -->
     ```
   - If a PR for this branch already exists, update its body instead.

6. **Hand over in Linear:** move the issue to `Ready for agent` and comment:
   `Handed to the factory: <N> phases. PR: <pr url>`.

7. **Report** the PR link and the phase table. Tell the developer the factory will post
   progress on the issue and the PR, and that their next step is reviewing the PR when it is
   marked ready.
