import asyncio
import json
from pathlib import Path

import pytest

from factory.contract import Contract
from factory.runner import Mode, host, image, prompts, proxy, sandbox
from factory.runner.tools import allowed_tools, claude_command, command_parts
from factory.tasks import Phase, Task

CONTRACT = Contract(
    runner="node", setup="pnpm install", verify="pnpm lint && pnpm test", checks="pnpm arch"
)


def test_command_parts_split_shell_lists() -> None:
    assert command_parts("a b && c || d; e | f") == ["a b", "c", "d", "e", "f"]


def test_allowed_tools_cover_git_speckit_and_contract_commands() -> None:
    rules = allowed_tools(CONTRACT)
    for rule in ("Bash(git commit*)", "Bash(pnpm lint*)", "Bash(pnpm test*)", "Bash(pnpm arch*)"):
        assert rule in rules
    assert "Bash(pnpm install*)" in rules
    assert "Bash(.specify/scripts/bash/*)" in rules
    assert not any("push" in r for r in rules)


def test_claude_command_is_headless_and_locked_down() -> None:
    cmd = claude_command("do it", CONTRACT, max_turns=5, model="opus")
    assert cmd[:3] == ["claude", "--print", "do it"]
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "--strict-mcp-config" in cmd
    denied = cmd[cmd.index("--disallowedTools") + 1 : cmd.index("--model")]
    assert "Bash(git push*)" in denied and "WebFetch" in denied


def test_prompts_name_the_phase_and_feedback() -> None:
    phase = Phase(2, "Core", [Task("T003", False, "x"), Task("T004", False, "y")])
    text = prompts.build(Mode.IMPLEMENT, CONTRACT, "specs/001-x", phase=phase)
    assert "only Phase 2: Core" in text and "T003-T004" in text and "pnpm arch" in text
    assert "previous attempt" not in text
    retry = prompts.build(Mode.IMPLEMENT, CONTRACT, "specs/001-x", phase=phase, feedback="boom")
    assert "A previous attempt failed" in retry and "boom" in retry
    text = prompts.build(Mode.REWORK, CONTRACT, "specs/001-x", feedback="rename foo")
    assert "rename foo" in text


def test_image_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACTORY_IMAGE_PREFIX", "ghcr.io/acme/runner")
    assert image("python").startswith("ghcr.io/acme/runner-python:")


@pytest.mark.parametrize(
    ("host_", "port", "ok"),
    [
        ("api.anthropic.com", 443, True),
        ("API.Anthropic.com.", 443, True),
        ("api.anthropic.com", 80, False),
        ("evil.com", 443, False),
        ("anthropic.com.evil.com", 443, False),
        ("files.pythonhosted.org", 443, True),
        ("pythonhosted.org", 443, True),
        ("notpythonhosted.org", 443, False),
    ],
)
def test_proxy_allowlist(host_: str, port: int, ok: bool) -> None:
    allow = ["api.anthropic.com", ".pythonhosted.org"]
    assert proxy.allowed(host_, port, allow) is ok


def test_proxy_parse_connect() -> None:
    assert proxy.parse_connect(b"CONNECT github.com:443 HTTP/1.1\r\nHost: x\r\n\r\n") == (
        "github.com",
        443,
    )
    assert proxy.parse_connect(b"GET http://github.com/ HTTP/1.1\r\n\r\n") is None
    assert proxy.parse_connect(b"CONNECT github.com HTTP/1.1\r\n\r\n") is None


async def _exchange(proxy_port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(request)
    await writer.drain()
    data = await asyncio.wait_for(reader.read(1024), 5)
    writer.close()
    return data


def test_proxy_tunnels_allowed_and_refuses_others() -> None:
    async def scenario() -> tuple[bytes, bytes]:
        async def echo(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
            w.write(await r.read(100))
            await w.drain()
            w.close()

        upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
        up_port = upstream.sockets[0].getsockname()[1]
        server = await proxy.start(["localhost"], "127.0.0.1", 0, ports=frozenset({up_port}))
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"CONNECT localhost:{up_port} HTTP/1.1\r\n\r\n".encode())
        status = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        writer.write(b"ping")
        echoed = await asyncio.wait_for(reader.read(4), 5)
        writer.close()
        denied = await _exchange(port, b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
        server.close()
        upstream.close()
        return status + echoed, denied

    tunnel, denied = asyncio.run(scenario())
    assert tunnel.startswith(b"HTTP/1.1 200") and tunnel.endswith(b"ping")
    assert denied.startswith(b"HTTP/1.1 403")


def test_agent_container_is_hardened_and_has_no_host_mounts() -> None:
    cmd = sandbox.agent_run(
        "run1", "img:1", "net1", {"FACTORY_MODE": "implement"}, sandbox.Limits(pids=100)
    )
    joined = " ".join(cmd)
    for flag in ("--read-only", "--cap-drop ALL", "no-new-privileges", "--pids-limit 100"):
        assert flag in joined
    assert "--user 10001:10001" in joined and "--network net1" in joined
    assert "-v" not in cmd and "docker.sock" not in joined and "type=bind" not in joined
    assert "HTTPS_PROXY=http://egress:3128" in cmd
    i = cmd.index("CLAUDE_CODE_OAUTH_TOKEN")
    assert cmd[i - 1] == "-e"  # passed by name: the value never appears on the argv
    assert sandbox.network_create("net1")[-2:] == ["factory.run=1", "net1"]
    assert "--internal" in sandbox.network_create("net1")


def test_host_reads_transcript_result_and_usage(tmp_path: Path) -> None:
    lines = [
        json.dumps({"type": "system"}),
        json.dumps({"type": "result", "num_turns": 7, "total_cost_usd": 0.5, "usage": {}}),
        json.dumps({"type": "factory_result", "status": "ok", "bundle": "aGk="}),
    ]
    stream = [(line + "\n").encode() for line in lines]
    result = host._read_output(iter(stream), tmp_path)  # type: ignore[arg-type]
    assert result == {"type": "factory_result", "status": "ok"}
    assert (tmp_path / "result.bundle").read_bytes() == b"hi"
    assert "aGk=" not in (tmp_path / "transcript.jsonl").read_text()
    assert host._usage(tmp_path)["num_turns"] == 7


def test_run_id_is_docker_safe() -> None:
    rid = host.run_id("feature/ENG-123_x", Mode.IMPLEMENT, 2)
    assert rid.startswith("eng-123-x-implement2-")
