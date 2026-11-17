"""`factory screenshots`: Playwright screenshots of a preview, once it serves the expected commit.

Playwright is optional (`software-factory[ui]`); the reviewer image has it with Chromium.
"""

from pathlib import Path

VIEWPORTS = {"desktop": (1280, 800), "mobile": (390, 844)}


class ScreenshotError(RuntimeError):
    """Playwright is missing or a page could not be captured."""


def take(url: str, paths: list[str], out: Path, auth: str | None = None) -> list[Path]:
    try:
        from playwright.sync_api import HttpCredentials, sync_playwright
    except ImportError as exc:
        raise ScreenshotError("playwright is not installed: use the reviewer image") from exc
    out.mkdir(parents=True, exist_ok=True)
    files = []
    credentials: HttpCredentials | None = None
    if auth:
        user, _, password = auth.partition(":")
        credentials = {"username": user, "password": password}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, (width, height) in VIEWPORTS.items():
            context = browser.new_context(
                viewport={"width": width, "height": height}, http_credentials=credentials
            )
            page = context.new_page()
            for path in paths:
                slug = path.strip("/").replace("/", "_") or "root"
                target = out / f"{slug}-{name}.png"
                page.goto(url.rstrip("/") + path, wait_until="networkidle", timeout=60_000)
                page.screenshot(path=str(target), full_page=True)
                files.append(target)
            context.close()
        browser.close()
    return files
