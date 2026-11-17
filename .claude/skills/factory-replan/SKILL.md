---
name: "factory-replan"
description: "Revise the remaining phases of a factory feature that is in Needs replan, then hand it back to the factory."
argument-hint: "Linear issue key, e.g. ENG-123"
user-invocable: true
disable-model-invocation: true
---

## Input

```text
$ARGUMENTS
```

The input is a Linear issue key. If it is empty, use the issue from the current
`feature/<ISSUE>` branch name.

## Steps

1. **Load context.**
   - Fetch the Linear issue and its recent comments with the Linear MCP tools. The issue
     should be in `Needs replan` or `Agent failed`; if the factory is still working on it
     (`Agent working`), stop.
   - Find the PR for `feature/<ISSUE>` with `gh pr view`. Read its review comments and the
     reason it was sent to replan.
   - `git fetch origin && git switch feature/<ISSUE> && git pull --ff-only`.

2. **Summarise the state** for the developer:
   - Phases done (all tasks checked, with their commits) and phases remaining.
   - What went wrong, from the review comments, Linear comments and failure logs.

3. **Revise with the developer.** Discuss what should change, then edit only the remaining
   (unchecked) part of `tasks.md`, and `plan.md` or `spec.md` if the approach itself changes.
   Never edit or uncheck completed phases; if completed work must be undone, add a new phase
   that does it. Use `/speckit-plan` or `/speckit-tasks` if a larger rewrite is needed.

4. **Check and hand back.** Run the same checks as `/factory-handoff` steps 2 and 3, for the
   remaining phases only. Then:
   ```bash
   git add specs/<dir>
   git commit -m "<ISSUE>: replan remaining phases"
   git push
   ```
   Update the PR body phase table, reopen the PR as a draft if it was closed, move the
   Linear issue to `Ready for agent`, and comment with a short summary of what changed.

5. **Report** what changed and that the factory will resume at the first unfinished phase.
