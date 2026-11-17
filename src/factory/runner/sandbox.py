"""Docker command lines for one sandboxed run: an internal network, an egress proxy, the agent.

The agent container has no route out except the proxy, runs as a non-root user with no
capabilities on a read-only root, has CPU, memory and process limits, and never gets the Docker
socket or a host mount (only anonymous volumes and tmpfs, removed with the container).
"""

from dataclasses import dataclass

PROXY_ALIAS = "egress"
PROXY_PORT = 3128
AGENT_UID = "10001:10001"


@dataclass(frozen=True)
class Limits:
    cpus: str = "2"
    memory: str = "4g"
    pids: int = 512


def hardening(limits: Limits) -> list[str]:
    return [
        "--user", AGENT_UID,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--init",
        "--cpus", limits.cpus,
        "--memory", limits.memory,
        "--memory-swap", limits.memory,
        "--pids-limit", str(limits.pids),
    ]  # fmt: skip


def network_create(network: str) -> list[str]:
    return ["docker", "network", "create", "--internal", "--label", "factory.run=1", network]


def proxy_run(name: str, image: str, allow: list[str]) -> list[str]:
    """Started on the default bridge (outbound), then connected to the run's network."""
    return [
        "docker", "run", "-d", "--rm", "--name", name,
        *hardening(Limits(cpus="0.5", memory="256m", pids=64)),
        "--entrypoint", "factory-egress",
        image, "--allow", ",".join(allow), "--port", str(PROXY_PORT),
    ]  # fmt: skip


def proxy_connect(network: str, name: str) -> list[str]:
    return ["docker", "network", "connect", "--alias", PROXY_ALIAS, network, name]


def agent_run(
    name: str,
    image: str,
    network: str,
    env: dict[str, str],
    limits: Limits,
    passthrough: tuple[str, ...] = ("CLAUDE_CODE_OAUTH_TOKEN",),
) -> list[str]:
    """`passthrough` names host variables (secrets) passed by name, never on the argv."""
    proxy = f"http://{PROXY_ALIAS}:{PROXY_PORT}"
    cmd = [
        "docker", "run", "-i", "--rm", "--name", name,
        *hardening(limits),
        "--network", network,
        "--tmpfs", "/tmp:rw,exec,nosuid,size=1g",  # noqa: S108 - container tmpfs
        "--mount", "type=volume,dst=/workspace",
        "--mount", "type=volume,dst=/home/agent",
    ]  # fmt: skip
    proxy_env = {"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "https_proxy": proxy}
    proxy_env |= {"http_proxy": proxy, "NO_PROXY": "", "no_proxy": ""}
    for key, value in {**proxy_env, **env}.items():
        cmd += ["-e", f"{key}={value}"]
    for key in passthrough:
        cmd += ["-e", key]
    return [*cmd, image]
