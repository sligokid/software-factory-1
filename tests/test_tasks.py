from factory import tasks

TASKS = """# Tasks: demo

## Phase 1: Setup
- [X] T001 Create src/app.py
- [x] T002 Add tests/test_app.py

## Phase 2: Core
### Tests
- [ ] T003 [P] Test greeting in tests/test_app.py
- [ ] T004 Implement greeting in src/app.py

## Phase 3: Polish
- [ ] T005 Docs

## Dependencies
- [ ] T999 not a task of phase 3
"""


def test_parse_phases_and_tasks() -> None:
    phases = tasks.parse(TASKS)
    assert [p.name for p in phases] == ["Phase 1: Setup", "Phase 2: Core", "Phase 3: Polish"]
    assert [t.id for t in phases[1].tasks] == ["T003", "T004"]
    assert phases[0].done and not phases[1].done
    assert [t.id for t in phases[2].tasks] == ["T005"]


def test_next_open_and_find() -> None:
    phases = tasks.parse(TASKS)
    assert tasks.next_open(phases) == phases[1]
    assert tasks.find(phases, 3) == phases[2]
    assert tasks.find(phases, 9) is None
