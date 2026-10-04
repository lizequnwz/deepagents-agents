"""Fixed Playwright checks for one application-selected local HTTP origin."""

from __future__ import annotations

import asyncio
import ctypes
import json
import math
import os
from pathlib import Path
import struct
import sys
from urllib.parse import urlsplit

WIDTH, HEIGHT = 1280, 720
MAX_PNG_BYTES = 5 * 1024 * 1024


def _protect_controller() -> None:
    library = ctypes.CDLL(None, use_errno=True)
    library.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    library.prctl.restype = ctypes.c_int
    if library.prctl(4, 0, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Unable to protect browser evidence descriptors")


def allowed_url(url: str, port: int, *, websocket: bool = False) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == ("ws" if websocket else "http") and parsed.hostname == "127.0.0.1"
            and (parsed.port or 80) == port and parsed.username is None and parsed.password is None
        )
    except ValueError:
        return False


def validate_request(request: dict) -> None:
    port, path, timeout = request.get("port"), request.get("path"), request.get("timeout")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid owned browser port")
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or len(path) > 2048 or "\\" in path or any(ord(value) < 32 for value in path):
        raise ValueError("Invalid server-relative browser path")
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ValueError("Invalid browser deadline")
    for field, maximum in (("selector", 500), ("expected_text", 1000)):
        value = request.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > maximum):
            raise ValueError("Invalid browser assertion")


async def _wait_server(port: int, timeout: float) -> None:
    deadline = asyncio.get_running_loop().time() + min(5, timeout)
    while True:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 0.25)
            writer.close()
            await writer.wait_closed()
            return
        except (OSError, TimeoutError):
            if asyncio.get_running_loop().time() >= deadline:
                raise ValueError("The owned preview server is not listening")
            await asyncio.sleep(0.05)


async def probe(request: dict, playwright_factory, *, local_directory: Path | None = None) -> tuple[dict, bytes]:
    validate_request(request)
    port, timeout = request["port"], request["timeout"]
    url = f"http://127.0.0.1:{port}{request['path']}"
    await _wait_server(port, timeout)
    errors: list[str] = []
    blocked: list[str] = []
    metadata = {"protocol": 1, "url": url, "status": "failed", "width": WIDTH, "height": HEIGHT,
                "http_status": None, "title": "", "errors": errors, "blocked_requests": blocked}

    def remember(target: list[str], value: str) -> None:
        if len(target) < 10:
            target.append(value[:500])

    async with playwright_factory() as playwright:
        environment = {"PATH": "/usr/local/bin:/usr/bin:/bin",
                       "HOME": str(local_directory / "home") if local_directory else "/work/tmp/home",
                       "TMPDIR": str(local_directory) if local_directory else "/work/tmp"}
        browser = await playwright.chromium.launch(
            headless=True, chromium_sandbox=local_directory is not None,
            args=["--disable-dev-shm-usage"], timeout=10_000, env=environment,
        )
        try:
            context = await browser.new_context(viewport={"width": WIDTH, "height": HEIGHT},
                                                accept_downloads=False, service_workers="block")
            try:
                context.set_default_timeout(timeout * 1000)

                async def route_http(route):
                    if allowed_url(route.request.url, port):
                        await route.continue_()
                    else:
                        remember(blocked, route.request.url)
                        await route.abort("blockedbyclient")

                async def route_websocket(route):
                    if allowed_url(route.url, port, websocket=True):
                        route.connect_to_server()
                    else:
                        remember(blocked, route.url)
                        await route.close()

                await context.route("**/*", route_http)
                await context.route_web_socket("**/*", route_websocket)
                page = await context.new_page()
                page.on("pageerror", lambda error: remember(errors, str(error)))
                page.on("console", lambda message: remember(errors, message.text) if message.type == "error" else None)
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                    metadata["http_status"] = response.status if response else None
                    metadata["title"] = (await page.title())[:1000]
                    if not allowed_url(page.url, port):
                        raise ValueError("The page navigated outside its owned origin")
                    locator = page.locator(request.get("selector") or "body").first
                    await locator.wait_for(state="visible", timeout=timeout * 1000)
                    expected = request.get("expected_text")
                    if expected is not None and expected not in (await locator.inner_text())[:20_000]:
                        raise ValueError("Expected text was not observed")
                    if response is not None and 200 <= response.status < 400 and not errors:
                        metadata["status"] = "passed"
                except Exception as exc:
                    remember(errors, str(exc))
                png = await page.screenshot(type="png", full_page=False, timeout=timeout * 1000)
                if len(png) > MAX_PNG_BYTES:
                    raise ValueError("Browser screenshot exceeds its size bound")
                return metadata, png
            finally:
                await context.close()
        finally:
            await browser.close()


async def main() -> None:
    local_directory = None
    if sys.argv[1] == "--local":
        local_directory = Path(sys.argv[2])
        if not local_directory.is_absolute() or local_directory.is_symlink() or not local_directory.is_dir():
            raise ValueError("An application-owned local temporary directory is required")
        request = json.loads(sys.argv[3])
        # Keep the browser driver out of repository-installed modules. -I sets
        # Python's import path to the application environment, without source.
        (local_directory / "home").mkdir(exist_ok=True)
    else:
        _protect_controller()
        request = json.loads(sys.argv[1])
    validate_request(request)
    # Driver imports and browser discovery come exclusively from the read-only
    # SDK baked into the explicitly selected image, never project dependencies.
    if local_directory is None:
        os.environ.clear()
        os.environ.update(PATH="/usr/local/bin:/usr/bin:/bin", HOME="/work/tmp/home", TMPDIR="/work/tmp",
                          PLAYWRIGHT_BROWSERS_PATH="/opt/general-agent/browsers")
        sys.path.insert(0, "/opt/general-agent/browser-sdk")
    from playwright.async_api import async_playwright

    async with asyncio.timeout(request["timeout"] + 4):
        metadata, png = await probe(request, async_playwright, local_directory=local_directory)
    encoded = json.dumps(metadata, ensure_ascii=True).encode()
    if len(encoded) > 65_536:
        raise ValueError("Browser metadata exceeds its size bound")
    sys.stdout.buffer.write(struct.pack(">I", len(encoded)) + encoded + png)


if __name__ == "__main__":
    asyncio.run(main())
