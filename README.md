# Software Factory

A vertical-slice Python service built with an AI software factory: developers write the spec
and tasks interactively with Claude Code and GitHub Spec Kit, then the factory implements each
phase in a sandboxed headless Claude Code run and delivers one PR per feature.

See `PLAN.md` for the build plan, `.specify/memory/constitution.md` for the rules and
`CLAUDE.md` for the day-to-day guide.

## Quick start

```bash
uv tool install specify-cli==1.4.1   # Spec Kit CLI (pinned)
make install
make all
```

## Developer flow

```text
/factory-start ENG-123   ->  /speckit-clarify  ->  /speckit-plan  ->  /speckit-tasks  ->  /factory-handoff
```

Claude Code connects to Linear through the MCP server in `.mcp.json` (first use asks you to
sign in). `gh` must be installed and authenticated for `/factory-handoff`.
