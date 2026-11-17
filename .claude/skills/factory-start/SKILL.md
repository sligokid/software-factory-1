---
name: "factory-start"
description: "Start a factory feature from a Linear issue: pull the issue, create the feature branch, move the issue to In spec and draft the spec with speckit-specify."
argument-hint: "Linear issue key, e.g. ENG-123"
user-invocable: true
disable-model-invocation: true
---

## Input

```text
$ARGUMENTS
```

The input is a Linear issue key (for example `ENG-123`). If it is empty or does not look like
an issue key, ask the developer for one and stop.

## Steps

1. **Check the working tree.** Run `git status --porcelain`. If there are uncommitted changes,
   stop and ask the developer to commit or stash them.

2. **Fetch the issue from Linear** using the Linear MCP tools: title, description, team,
   current state, labels and URL. If the Linear tools are unavailable, tell the developer to
   connect the Linear MCP server from `.mcp.json` and stop.
   - If the issue is already in `Ready for agent`, `Agent working` or `Awaiting approval`,
     stop: the factory owns it.
   - Read the `Slice:` line. If it is missing, ask the developer which slice this changes
     (existing name, or a new snake_case name). One spec changes exactly one slice.

3. **Create the feature branch** from the latest `main`:
   ```bash
   git fetch origin main
   git switch -c feature/<ISSUE> origin/main
   ```
   If `feature/<ISSUE>` already exists locally or on origin, switch to it instead and tell the
   developer you are resuming.

4. **Update Linear:** move the issue to `In spec`, assign it to the developer if unassigned, and
   add a comment: `Spec started on branch feature/<ISSUE>.`

5. **Draft the spec.** Invoke the `speckit-specify` skill with this description:
   ```
   <ISSUE>: <title>
   Slice: <slice>
   Linear: <url>

   <full issue description>
   ```
   Use a short name of the form `<issue-key-lowercase>-<2-3 words>` (for example
   `eng-123-daily-prices`).

6. **Report** the branch, the spec directory and any `[NEEDS CLARIFICATION]` markers, then
   suggest the next steps:
   `/speckit-clarify` -> `/speckit-plan` -> `/speckit-checklist` (optional) -> `/speckit-tasks`
   -> `/factory-handoff`.

Do not commit or push in this command.
