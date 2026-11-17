"""`factory preview`: one live preview per feature, from the product's preview compose file.

`up` exports the commit, starts the product's compose stack as project `factory-preview-<id>`,
adds an ngrok tunnel at `https://<id>.<domain>` (basic auth or an IP allowlist, and an
`x-factory-commit` response header), and health-checks the service. Running `up` again
redeploys; `down` removes everything. Runs on the factory host, never in the agent sandbox.
"""

import base64
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from factory import NGROK_IMAGE
from factory.contract import CONTRACT_PATH, Preview, parse
from factory.runner import image

COMMIT_HEADER = "x-factory-commit"
COMMIT_LABEL = "factory.commit"
TUNNEL = "factory-tunnel"
DOMAIN_ENV = "FACTORY_PREVIEW_DOMAIN"  # wildcard ngrok domain: previews at <id>.<domain>
AUTH_ENV = "FACTORY_PREVIEW_AUTH"  # user:password for basic auth
ALLOW_IPS_ENV = "FACTORY_PREVIEW_ALLOW_IPS"  # comma-separated CIDRs
STATE_ENV = "FACTORY_PREVIEWS_DIR"


class PreviewError(RuntimeError):
    """The preview could not be deployed or is not healthy."""


@dataclass
class State:
    id: str
    branch: str
    commit: str
    url: str | None
    deployed: str


def preview_id(branch: str) -> str:
    """eng-123 for feature/ENG-123: a DNS label and a compose project name."""
    slug = re.sub(r"[^a-z0-9]+", "-", branch.removeprefix("feature/").lower()).strip("-")
    if not slug:
        raise PreviewError(f"cannot derive a preview id from {branch!r}")
    return slug[:40].rstrip("-")


def preview_url(branch: str, domain: str | None = None) -> str | None:
    domain = domain or os.environ.get(DOMAIN_ENV)
    return f"https://{preview_id(branch)}.{domain}" if domain else None


def project(pid: str) -> str:
    return f"factory-preview-{pid}"


def state_dir(pid: str) -> Path:
    return Path(os.environ.get(STATE_ENV, Path.home() / ".factory" / "previews")) / pid


def traffic_policy(commit: str, auth: str | None, allow_ips: list[str]) -> dict[str, Any]:
    request: list[dict[str, Any]] = []
    if allow_ips:
        request.append({"actions": [{"type": "restrict-ips", "config": {"allow": allow_ips}}]})
    if auth:
        request.append({"actions": [{"type": "basic-auth", "config": {"credentials": [auth]}}]})
    headers = {"actions": [{"type": "add-headers", "config": {"headers": {COMMIT_HEADER: commit}}}]}
    return {"on_http_request": request, "on_http_response": [headers]}


def override(
    preview: Preview, commit: str, url: str | None, networks: list[str], policy: Path
) -> dict[str, Any]:
    """Compose override: commit label on the service, plus the ngrok tunnel when url is set."""
    services: dict[str, Any] = {preview.service: {"labels": {COMMIT_LABEL: commit}}}
    if url:
        services[TUNNEL] = {
            "image": NGROK_IMAGE,
            "command": [
                "http", "--url", url, "--traffic-policy-file", "/etc/factory/policy.yml",
                f"http://{preview.service}:{preview.port}",
            ],
            "environment": ["NGROK_AUTHTOKEN"],
            "volumes": [f"{policy}:/etc/factory/policy.yml:ro"],
            "networks": networks,
            "depends_on": [preview.service],
            "labels": {COMMIT_LABEL: commit},
            "restart": "unless-stopped",
        }  # fmt: skip
    return {"services": services}


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


def _check(cmd: list[str], **kwargs: Any) -> str:
    proc = _run(cmd, **kwargs)
    if proc.returncode != 0:
        raise PreviewError(f"{' '.join(cmd[:4])} failed: {(proc.stderr or proc.stdout)[-2000:]}")
    return proc.stdout


def export(product: Path, commit: str, dest: Path) -> None:
    """The commit's tree, without .git, into dest (replacing it)."""
    data = subprocess.run(
        ["git", "-C", str(product), "archive", "--format=tar", commit],
        capture_output=True,
        check=True,
    ).stdout
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")


def compose_cmd(pid: str, src: Path, preview: Preview, extra: Path | None) -> list[str]:
    cmd = ["docker", "compose", "-p", project(pid), "--project-directory", str(src)]
    cmd += ["-f", str(src / preview.compose)]
    return cmd + (["-f", str(extra)] if extra else [])


def service_networks(base_cmd: list[str], service: str, env: dict[str, str]) -> list[str]:
    config = json.loads(_check([*base_cmd, "config", "--format", "json"], env=env))
    networks = config["services"].get(service, {}).get("networks") or {"default": None}
    return sorted(networks)


def served_commit(url: str, auth: str | None) -> str | None:
    headers = {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode()} if auth else {}
    request = urllib.request.Request(url, method="GET", headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            value = response.headers.get(COMMIT_HEADER)
            return str(value) if value else None
    except urllib.error.HTTPError as exc:
        value = exc.headers.get(COMMIT_HEADER)
        return str(value) if value else None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def wait_for_commit(url: str, commit: str, auth: str | None, timeout: int) -> None:
    deadline, seen = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        if (seen := served_commit(url, auth)) == commit:
            return
        time.sleep(3)
    raise PreviewError(f"{url} did not serve commit {commit[:12]} within {timeout}s (saw {seen})")


def wait_healthy(preview: Preview, base_cmd: list[str], env: dict[str, str], timeout: int) -> None:
    """2xx from the service's healthcheck path, checked from inside the stack's network."""
    container = _check([*base_cmd, "ps", "-q", preview.service], env=env).strip().splitlines()
    if not container:
        raise PreviewError(f"service {preview.service} is not running")
    networks = json.loads(
        _check(["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", container[0]])
    )
    target = f"http://{preview.service}:{preview.port}{preview.healthcheck}"
    probe = ["docker", "run", "--rm", "--network", next(iter(networks)), "--entrypoint", "curl"]
    probe += [image("base"), "-fsS", "-o", "/dev/null", "-m", "5", target]
    deadline = time.monotonic() + timeout
    while True:
        result = _run(probe)
        if result.returncode == 0:
            return
        if time.monotonic() > deadline:
            logs = _run([*base_cmd, "logs", "--tail", "40", preview.service], env=env).stdout
            raise PreviewError(f"{target} not healthy after {timeout}s: {result.stderr}\n{logs}")
        time.sleep(2)


def up(
    product: Path, ref: str, branch: str, *, domain: str | None = None, timeout: int = 300
) -> State:
    product = product.resolve()
    commit = _check(["git", "-C", str(product), "rev-parse", f"{ref}^{{commit}}"]).strip()
    contract_text = _check(
        ["git", "-C", str(product), "show", f"{commit}:{CONTRACT_PATH.as_posix()}"]
    )
    contract = parse(yaml.safe_load(contract_text))
    if contract.preview is None:
        raise PreviewError("factory.yaml has no preview section")
    preview = contract.preview
    pid = preview_id(branch)
    url = preview_url(branch, domain)
    auth = os.environ.get(AUTH_ENV) or None
    allow_ips = [c.strip() for c in os.environ.get(ALLOW_IPS_ENV, "").split(",") if c.strip()]
    if url and not os.environ.get("NGROK_AUTHTOKEN"):
        raise PreviewError("NGROK_AUTHTOKEN is required for a public preview")
    if url and not (auth or allow_ips):
        raise PreviewError(f"set {AUTH_ENV} or {ALLOW_IPS_ENV}: previews are never public")

    state = state_dir(pid)
    src = state / "src"
    export(product, commit, src)
    env = {**os.environ, "FACTORY_COMMIT": commit, "FACTORY_PREVIEW_URL": url or ""}
    networks = service_networks(compose_cmd(pid, src, preview, None), preview.service, env)
    policy = state / "policy.yml"
    policy.write_text(yaml.safe_dump(traffic_policy(commit, auth, allow_ips)))
    extra = state / "override.yml"
    extra.write_text(yaml.safe_dump(override(preview, commit, url, networks, policy.resolve())))
    cmd = compose_cmd(pid, src, preview, extra)

    _check([*cmd, "up", "-d", "--build", "--remove-orphans"], env=env)
    wait_healthy(preview, cmd, env, timeout)
    if url and not allow_ips:  # with an IP allowlist this host may not be allowed in
        wait_for_commit(url + preview.healthcheck, commit, auth, timeout)
    record = State(pid, branch, commit, url, dt.datetime.now(dt.UTC).isoformat())
    (state / "state.json").write_text(json.dumps(asdict(record), indent=2) + "\n")
    return record


def down(branch: str) -> bool:
    """Remove the preview's containers, volumes and state. False if there was none."""
    pid = preview_id(branch)
    existed = state_dir(pid).exists()
    proc = _run(["docker", "compose", "-p", project(pid), "down", "-v", "--remove-orphans"])
    if proc.returncode != 0 and existed:
        raise PreviewError(f"docker compose down failed: {proc.stderr[-1000:]}")
    shutil.rmtree(state_dir(pid), ignore_errors=True)
    return existed


def status() -> list[dict[str, Any]]:
    root = state_dir("x").parent
    rows = []
    for path in sorted(root.glob("*/state.json")) if root.is_dir() else []:
        record = json.loads(path.read_text())
        ps = _run(["docker", "compose", "-p", project(record["id"]), "ps", "--format", "json"])
        lines = [json.loads(line) for line in ps.stdout.splitlines() if line.strip()]
        record["services"] = {c.get("Service"): c.get("State") for c in lines}
        rows.append(record)
    return rows
