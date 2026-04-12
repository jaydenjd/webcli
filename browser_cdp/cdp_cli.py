#!/usr/bin/env python3
"""
webcli - Browser automation via Chrome DevTools Protocol

Provides a CLI wrapper for the CDP Proxy, automatically managing the Proxy lifecycle.
All commands correspond to real endpoints in cdp_proxy.py.
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

import click
from importlib.metadata import version as pkg_version

try:
    __version__ = pkg_version("webcli")
except Exception:
    __version__ = "dev"

PROXY_PORT = int(os.environ.get("CDP_PROXY_PORT", "3456"))
PROXY_URL = f"http://127.0.0.1:{PROXY_PORT}"
SCRIPT_DIR = Path(__file__).parent
# When set, Proxy will be started with this Chrome port (passed as --chrome-port arg).
CHROME_PORT_OVERRIDE: Optional[int] = int(os.environ["CDP_CHROME_PORT"]) if os.environ.get("CDP_CHROME_PORT") else None


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _do_request(req: urllib.request.Request, timeout_seconds: float, retries: int = 0) -> bytes:
    """Execute a urllib request and return raw response bytes.

    When retries > 0, automatically retries on transient 500/503/504 errors
    with a short delay between attempts. 400/404 errors are never retried.
    """
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        if attempt > 0:
            time.sleep(1.5)
            # Re-create the request object so the body can be re-sent.
            new_req = urllib.request.Request(
                req.full_url,
                data=req.data,
                headers=dict(req.headers),
                method=req.get_method(),
            )
            req = new_req
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            # Try to extract a clean error message from JSON response body.
            try:
                error_msg = json.loads(body).get("error", body)
            except Exception:
                error_msg = body
            if exc.code == 400:
                raise RuntimeError(f"Bad request: {error_msg}") from exc
            if exc.code == 404:
                raise RuntimeError(f"Not found: {error_msg}") from exc
            if exc.code in (500, 503, 504):
                lower_msg = error_msg.lower()
                is_chrome_down = any(kw in lower_msg for kw in (
                    "chrome", "remote debugging", "websocket", "connection refused",
                    "not connected", "no browser",
                ))
                if is_chrome_down:
                    raise RuntimeError("Chrome 未运行或连接已断开。请手动打开浏览器") from exc
                if exc.code == 503:
                    raise RuntimeError(f"Proxy/Chrome not ready: {error_msg}") from exc
                if exc.code == 504:
                    raise RuntimeError(f"CDP command timed out: {error_msg}") from exc
                if retries == 0:
                    raise RuntimeError(f"Internal error: {error_msg}") from exc
                last_error = RuntimeError(f"Proxy internal error: {error_msg}")
                if attempt < retries:
                    click.echo(f"[retry {attempt + 1}/{retries}] transient {exc.code}, retrying…", err=True)
            else:
                raise RuntimeError(f"HTTP {exc.code}: {error_msg}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接到 Proxy（是否正在运行？）: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError(f"请求超时（{timeout_seconds:.0f}秒）") from exc
    raise last_error  # type: ignore[misc]


def http_get(path: str, timeout: int = 30000) -> dict:
    """Make HTTP GET request and return JSON."""
    req = urllib.request.Request(f"{PROXY_URL}{path}")
    return json.loads(_do_request(req, timeout / 1000))


def http_post(path: str, body: str, timeout: int = 30000, retries: int = 0) -> dict:
    """Make HTTP POST request with plain-text body and return JSON."""
    data = body.encode()
    req = urllib.request.Request(
        f"{PROXY_URL}{path}",
        data=data,
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    return json.loads(_do_request(req, timeout / 1000, retries=retries))


def http_post_json(path: str, body: dict, timeout: int = 30000) -> dict:
    """Make HTTP POST request with JSON body and return JSON."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{PROXY_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    return json.loads(_do_request(req, timeout / 1000))


def http_get_binary(path: str, timeout: int = 30000) -> bytes:
    """Make HTTP GET request and return binary data."""
    req = urllib.request.Request(f"{PROXY_URL}{path}")
    return _do_request(req, timeout / 1000)


# ─── Proxy lifecycle ──────────────────────────────────────────────────────────

def _is_port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def _health_check(timeout_seconds: float = 2.0) -> Optional[dict]:
    try:
        with urllib.request.urlopen(f"{PROXY_URL}/health", timeout=timeout_seconds) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _kill_proxy_on_port(port: int) -> None:
    try:
        result = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True)
        for pid in result.stdout.strip().splitlines():
            subprocess.run(["kill", "-9", pid], capture_output=True)
        time.sleep(0.5)
    except Exception:
        pass


def ensure_proxy() -> bool:
    """Ensure CDP Proxy is running. Chrome connection is established lazily on first request."""
    if _is_port_open(PROXY_PORT):
        health = _health_check()
        if health and health.get("status") == "ok":
            # Proxy is up — whether or not Chrome is connected yet, let the
            # Proxy handle reconnection lazily when the first request arrives.
            return True
        print("[CDP CLI] Detected stale proxy process, restarting...", file=sys.stderr)
        _kill_proxy_on_port(PROXY_PORT)

    print("[CDP CLI] Starting CDP Proxy...", file=sys.stderr)
    proxy_script = SCRIPT_DIR / "cdp_proxy.py"
    log_file = Path(os.environ.get("TMPDIR", "/tmp")) / "cdp-proxy.log"

    proxy_args = [sys.executable, str(proxy_script), "--port", str(PROXY_PORT)]
    if CHROME_PORT_OVERRIDE:
        proxy_args += ["--chrome-port", str(CHROME_PORT_OVERRIDE)]

    with open(log_file, "a") as log_fd:
        subprocess.Popen(
            proxy_args,
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

    for _ in range(15):
        time.sleep(1)
        if not _is_port_open(PROXY_PORT):
            continue
        health = _health_check()
        if health and health.get("status") == "ok":
            if health.get("connected"):
                print("[CDP CLI] CDP Proxy is ready", file=sys.stderr)
            else:
                print("[CDP CLI] CDP Proxy started (Chrome not yet connected)", file=sys.stderr)
                print("[CDP CLI] Please ensure Chrome has remote debugging enabled:", file=sys.stderr)
                print("[CDP CLI]   - Desktop: Open chrome://inspect/#remote-debugging and check 'Allow remote debugging'", file=sys.stderr)
                print("[CDP CLI]   - Linux Headless: google-chrome --headless=new --remote-debugging-port=9223 --user-data-dir=/tmp/chrome-9223 --no-first-run &", file=sys.stderr)
            return True

    print("[CDP CLI] Proxy startup timeout", file=sys.stderr)
    print(f"[CDP CLI] Log: {log_file}", file=sys.stderr)
    return False


# ─── CLI group ────────────────────────────────────────────────────────────────

class AliasUnderscoreGroup(click.Group):
    """Click Group that treats underscores as hyphens in command names.

    Allows `webcli network_requests` to work as `webcli network-requests`,
    and prints a helpful hint so callers learn the canonical name.
    Also shows full help (with Examples) when a subcommand is missing arguments.
    """

    def get_command(self, ctx: click.Context, command_name: str) -> Optional[click.Command]:
        command = super().get_command(ctx, command_name)
        if command is not None:
            return command
        # Try replacing underscores with hyphens before giving up.
        hyphenated_name = command_name.replace("_", "-")
        if hyphenated_name == command_name:
            return None
        aliased_command = super().get_command(ctx, hyphenated_name)
        if aliased_command is not None:
            click.echo(
                f"Hint: command '{command_name}' not found; "
                f"using '{hyphenated_name}' (use hyphens, not underscores).",
                err=True,
            )
            return aliased_command
        return None

    def invoke(self, ctx: click.Context) -> None:
        try:
            super().invoke(ctx)
        except click.exceptions.NoArgsIsHelpError:
            # Subcommand received no args — Click will print its own help.
            # Just re-raise so Click handles it cleanly without double output.
            raise
        except click.UsageError as exc:
            # "No such command" errors should propagate normally.
            if "No such command" in exc.format_message():
                raise
            # For other UsageErrors (missing args, bad options), show full help
            # (including Examples) instead of bare error line.
            help_ctx = exc.ctx if exc.ctx else ctx
            click.echo(help_ctx.get_help(), err=True)
            click.echo(f"\nError: {exc.format_message()}", err=True)
            ctx.exit(2)



@click.group(cls=AliasUnderscoreGroup, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="webcli")
@click.pass_context
def cli(ctx: click.Context):
    """webcli - Browser automation via Chrome DevTools Protocol"""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ─── Tab management ───────────────────────────────────────────────────────────

@cli.command()
def browser():
    """检查 Chrome 状态，如果未运行则显示启动说明。"""
    result = http_get("/browser")
    if result.get("status") == "running":
        print(json.dumps(result, indent=2))
    else:
        click.echo("Chrome 未运行（未启用远程调试端口）。", err=True)
        click.echo("\n启动方式：", err=True)
        for instr in result.get("instructions", []):
            click.echo(f"  {instr}", err=True)
        sys.exit(1)

@cli.command()
@click.option("--type", "target_type", default="", help="Filter by type (page, worker...).")
def targets(target_type: str):
    """列出所有浏览器标签页。"""
    path = "/targets"
    if target_type:
        path += f"?type={target_type}"
    result = http_get(path)
    print(json.dumps(result, indent=2))
    print("\n# Next: webcli new <url>  |  webcli open-monitored <url>  |  webcli close <targetId>")

@cli.command()
@click.option("--type", "target_type", default="", help="Filter by type (page, worker...).")
def tabs(target_type: str):
    """列出所有浏览器标签页（targets 的别名）。"""
    path = "/targets"
    if target_type:
        path += f"?type={target_type}"
    result = http_get(path)
    print(json.dumps(result, indent=2))
    print("\n# Next: webcli new <url>  |  webcli open-monitored <url>  |  webcli close <targetId>")


@cli.command()
@click.argument("url")
@click.option("--id-only", is_flag=True, default=False, help="Print only the targetId (useful for shell assignment).")
@click.option("--snapshot", is_flag=True, default=False, help="Auto-capture accessibility tree after page load.")
@click.option("--depth", default=3, help="Snapshot tree depth (default: 3, only used with --snapshot).")
def new(url: str, id_only: bool, snapshot: bool, depth: int):
    """新建标签页并等待加载完成。

    \b
    示例：
      webcli new https://example.com
      webcli new https://example.com --snapshot          # 导航 + 自动获取无障碍树
      TARGET=$(webcli new https://example.com --id-only)
    """
    encoded_url = urllib.parse.quote(url, safe=':/?#[]@!$&\'()*+,;=')
    path = f"/new?url={encoded_url}"
    if snapshot:
        path += f"&snapshot=1&depth={depth}"
    result = http_get(path)
    target_id = result.get("targetId", "")
    if id_only:
        print(target_id)
    else:
        snapshot_text = result.get("snapshot", "")
        if snapshot_text:
            print(f"# targetId: {target_id}\n")
            print(snapshot_text)
            node_count = result.get("nodeCount", 0)
            ref_count = len(result.get("refs", {}))
            if node_count:
                print(f"\n# {node_count} nodes, {ref_count} refs (depth={depth})")
        else:
            print(json.dumps(result, indent=2))
            if target_id:
                print(f"\n# Next: webcli snapshot {target_id}  |  webcli eval {target_id} \"...\"  |  webcli screenshot {target_id} shot.png")


@cli.command(name="open-monitored")
@click.argument("url")
@click.option("--id-only", is_flag=True, default=False, help="Print only the targetId (useful for shell assignment).")
@click.option("--snapshot", is_flag=True, default=False, help="Auto-capture accessibility tree after page load.")
@click.option("--depth", default=3, help="Snapshot tree depth (default: 3, only used with --snapshot).")
def open_monitored(url: str, id_only: bool, snapshot: bool, depth: int):
    """新建标签页并从第一个请求起开启网络监控。

    原子操作：创建空白标签页 → 启动网络捕获 → 导航，确保不遗漏任何初始 XHR/fetch 请求。

    \b
    示例：
      webcli open-monitored https://yiche.com
      webcli open-monitored https://yiche.com --snapshot  # 导航 + 监控 + 自动获取无障碍树
      TARGET=$(webcli open-monitored https://yiche.com --id-only)
      # 随后使用：webcli network-requests $TARGET --type xhr,fetch
    """
    encoded_url = urllib.parse.quote(url, safe=':/?#[]@!$&\'()*+,;=')
    path = f"/network/open-monitored?url={encoded_url}"
    if snapshot:
        path += f"&snapshot=1&depth={depth}"
    result = http_get(path, timeout=30000)
    target_id = result.get("targetId", "")
    if id_only:
        print(target_id)
    else:
        snapshot_text = result.get("snapshot", "")
        if snapshot_text:
            print(f"# targetId: {target_id}  |  capturing: network\n")
            print(snapshot_text)
            node_count = result.get("nodeCount", 0)
            ref_count = len(result.get("refs", {}))
            if node_count:
                print(f"\n# {node_count} nodes, {ref_count} refs (depth={depth})")
        else:
            print(json.dumps(result, indent=2))
            if target_id:
                print(f"\n# Next: webcli network-requests {target_id} --type xhr,fetch  |  webcli snapshot {target_id}  |  webcli eval {target_id} \"...\"")

@cli.command()
@click.argument("target_id")
def close(target_id: str):
    """关闭标签页。"""
    result = http_get(f"/close?target={target_id}")
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
@click.argument("url")
@click.option("--snapshot", is_flag=True, default=False, help="Auto-capture accessibility tree after navigation.")
@click.option("--depth", default=3, help="Snapshot tree depth (default: 3, only used with --snapshot).")
def navigate(target_id: str, url: str, snapshot: bool, depth: int):
    """在当前标签页导航到指定 URL。

    \b
    示例：
      webcli navigate <id> https://example.com
      webcli navigate <id> https://example.com --snapshot  # 导航 + 自动获取无障碍树
    """
    encoded_url = urllib.parse.quote(url, safe=':/?#[]@!$&\'()*+,;=')
    path = f"/navigate?target={target_id}&url={encoded_url}"
    if snapshot:
        path += f"&snapshot=1&depth={depth}"
    result = http_get(path)
    snapshot_text = result.get("snapshot", "")
    if snapshot_text:
        print(f"# targetId: {target_id}  |  url: {result.get('url', '')}\n")
        print(snapshot_text)
        node_count = result.get("nodeCount", 0)
        ref_count = len(result.get("refs", {}))
        if node_count:
            print(f"\n# {node_count} nodes, {ref_count} refs (depth={depth})")
    else:
        print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
def back(target_id: str):
    """后退到上一页。"""
    result = http_get(f"/back?target={target_id}")
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
def forward(target_id: str):
    """前进到下一页。"""
    result = http_get(f"/forward?target={target_id}")
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
def reload(target_id: str):
    """刷新标签页并等待加载完成。"""
    result = http_get(f"/reload?target={target_id}")
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
def info(target_id: str):
    """获取页面基本信息（标题、URL、尺寸）。"""
    result = http_get(f"/info?target={target_id}")
    print(json.dumps(result, indent=2))


# ─── JavaScript ───────────────────────────────────────────────────────────────

@cli.command()
@click.argument("target_id")
@click.argument("expression", required=False)
@click.option("-f", "--file", "script_file", type=click.Path(exists=True), help="Read JS from file.")
def eval(target_id: str, expression: Optional[str], script_file: Optional[str]):
    """执行 JavaScript。可直接传表达式、用 -f 指定文件，或通过 stdin 管道输入。

    \b
    示例：
      webcli eval <id> "document.title"
      webcli eval <id> -f script.js
      echo "document.title" | webcli eval <id>
    """
    if script_file:
        expression = Path(script_file).read_text()
    elif not expression:
        if not sys.stdin.isatty():
            expression = sys.stdin.read()
        else:
            click.echo("Error: Provide an expression argument, use -f <file>, or pipe via stdin.", err=True)
            sys.exit(1)
    result = http_post(f"/eval?target={target_id}", expression, retries=2)
    print(json.dumps(result, indent=2))


# ─── Mouse & Keyboard ─────────────────────────────────────────────────────────

@cli.command(name="click")
@click.argument("target_id")
@click.argument("selector")
@click.option("--snapshot", is_flag=True, default=False, help="Auto-capture accessibility tree after click.")
@click.option("--depth", default=3, help="Snapshot tree depth (default: 3, only used with --snapshot).")
def click_element(target_id: str, selector: str, snapshot: bool, depth: int):
    """点击元素（JS el.click() 方式）。支持 CSS 选择器或 snapshot ref（如 @e27、[@e27]）。"""
    result = http_post(f"/click?target={target_id}", selector)
    print(json.dumps(result, indent=2))
    if snapshot and result.get("clicked"):
        import time
        time.sleep(0.5)
        snap = http_get(f"/snapshot?target={target_id}&depth={depth}")
        print(snap.get("snapshot", ""))


@cli.command(name="click-at")
@click.argument("target_id")
@click.argument("selector")
def click_at(target_id: str, selector: str):
    """点击元素（CDP 真实鼠标事件，适用于滑块、Canvas 等）。"""
    result = http_post(f"/clickAt?target={target_id}", selector)
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
@click.argument("selector")
def hover(target_id: str, selector: str):
    """悬停到指定元素上。"""
    result = http_post(f"/hover?target={target_id}", selector)
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
@click.argument("key")
def press(target_id: str, key: str):
    """按下按键或组合键（如 Enter、Tab、Control+a、Shift+ArrowDown）。"""
    result = http_post(f"/press?target={target_id}", key)
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
@click.argument("selector")
def focus(target_id: str, selector: str):
    """聚焦到指定元素。"""
    result = http_post(f"/focus?target={target_id}", selector)
    print(json.dumps(result, indent=2))


# ─── Form interaction ─────────────────────────────────────────────────────────

@cli.command()
@click.argument("target_id")
@click.argument("selector")
@click.argument("value")
def fill(target_id: str, selector: str, value: str):
    """清空并填写输入框（直接设置 value，触发 input/change 事件）。"""
    result = http_post_json(f"/fill?target={target_id}", {"selector": selector, "value": value})
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
@click.argument("selector")
@click.argument("text")
def type(target_id: str, selector: str, text: str):
    """逐字符输入文本（模拟真实键盘事件）。"""
    result = http_post_json(f"/type?target={target_id}", {"selector": selector, "text": text})
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
@click.argument("selector")
@click.argument("value")
def select(target_id: str, selector: str, value: str):
    """按值或可见文本选择下拉框选项。"""
    result = http_post_json(f"/select?target={target_id}", {"selector": selector, "value": value})
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
@click.argument("selector")
def check(target_id: str, selector: str):
    """勾选复选框。"""
    result = http_post(f"/check?target={target_id}&checked=true", selector)
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
@click.argument("selector")
def uncheck(target_id: str, selector: str):
    """取消勾选复选框。"""
    result = http_post(f"/check?target={target_id}&checked=false", selector)
    print(json.dumps(result, indent=2))



@cli.command()
@click.argument("target_id")
@click.argument("from_spec")
@click.argument("to_spec")
def drag(target_id: str, from_spec: str, to_spec: str):
    """拖拽元素。from_spec 和 to_spec 可以是 CSS 选择器或坐标（如 "100,200"）。"""
    def parse_spec(spec):
        if ',' in spec:
            parts = spec.split(',')
            return {"x": float(parts[0]), "y": float(parts[1])}
        return spec
    
    result = http_post_json(f"/drag?target={target_id}", {
        "from": parse_spec(from_spec),
        "to": parse_spec(to_spec)
    })
    print(json.dumps(result, indent=2))

@cli.command()
@click.argument("target_id")
@click.option("--init", is_flag=True, default=True, help="Initialize error interceptor if not already done.")
def page_errors(target_id: str, init: bool):
    """获取页面错误信息（JavaScript 错误、未处理的 Promise 拒绝、console.error）。"""
    path = f"/page-errors?target={target_id}"
    if not init:
        path += "&init=0"
    result = http_get(path)
    print(json.dumps(result, indent=2))

@cli.command(name="set-files")
@click.argument("target_id")
@click.argument("selector")
@click.argument("files", nargs=-1)
def set_files(target_id: str, selector: str, files: tuple):
    """为文件输入框设置文件（绕过系统文件选择对话框）。"""
    if not files:
        click.echo("Error: At least one file path is required", err=True)
        sys.exit(1)
    result = http_post_json(f"/setFiles?target={target_id}", {"selector": selector, "files": list(files)})
    print(json.dumps(result, indent=2))


# ─── Page interaction ─────────────────────────────────────────────────────────

@cli.command()
@click.argument("target_id")
@click.argument("param", required=False)
def scroll(target_id: str, param: Optional[str]):
    """滚动页面。参数：top | bottom | up | down | <像素数>。"""
    path = f"/scroll?target={target_id}"
    if param:
        if param in ("top", "bottom", "up", "down"):
            path += f"&direction={param}"
        else:
            path += f"&y={param}"
    result = http_get(path)
    print(json.dumps(result, indent=2))


@cli.command()
@click.argument("target_id")
@click.argument("file_path", required=False)
def screenshot(target_id: str, file_path: Optional[str]):
    """截图。指定路径则保存到文件，否则输出二进制到 stdout。"""
    # Resolve relative paths against the caller's cwd, not the Proxy's working directory.
    abs_file_path = str(Path(file_path).resolve()) if file_path else None
    path = f"/screenshot?target={target_id}"
    if abs_file_path:
        path += f"&file={abs_file_path}"
    data = http_get_binary(path)
    if abs_file_path:
        print(json.dumps({"saved": abs_file_path}, indent=2))
    else:
        sys.stdout.buffer.write(data)


# ─── Page inspection ──────────────────────────────────────────────────────────

@cli.command()
@click.argument("target_id")
@click.option("--depth", default=3, help="Max tree depth to render (default: 3). Use higher values for deeper inspection.")
def snapshot(target_id: str, depth: int):
    """获取无障碍树（含元素引用），AI 导航首选。

    \b
    示例：
      webcli snapshot <id>            # 默认 3 层
      webcli snapshot <id> --depth 6  # 更深层级
    """
    result = http_get(f"/snapshot?target={target_id}&depth={depth}", timeout=30000)
    print(result.get("snapshot", ""))
    node_count = result.get("nodeCount", 0)
    ref_count = len(result.get("refs", {}))
    if node_count:
        print(f"\n# {node_count} nodes, {ref_count} refs (depth={depth})")
    print(f"# Next: webcli eval {target_id} \"...\"  |  webcli click {target_id} \"<selector>\"  |  webcli find {target_id} text \"<text>\" click  |  webcli screenshot {target_id} shot.png")


@cli.command()
@click.argument("target_id")
@click.argument("prop", type=click.Choice(["text", "html", "value", "title", "url", "attr", "count", "box", "styles"]))
@click.argument("selector", required=False)
@click.option("--attr", "attr_name", default="", help="Attribute name (required when prop=attr).")
def get(target_id: str, prop: str, selector: Optional[str], attr_name: str):
    """获取页面或元素属性。

    \b
    不需要选择器：title、url、text（body 文本）、html（完整页面）
    需要选择器：  text、html、value、attr、count、box、styles
    """
    path = f"/get?target={target_id}&prop={prop}"
    if selector:
        path += f"&selector={urllib.parse.quote(selector, safe='')}"
    if attr_name:
        path += f"&attr={urllib.parse.quote(attr_name, safe='')}"
    result = http_get(path)
    value = result.get("value")
    if isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, indent=2, ensure_ascii=False))


@cli.command()
@click.argument("target_id")
def console(target_id: str):
    """获取页面拦截到的 console 日志。"""
    result = http_get(f"/console?target={target_id}")
    messages = result.get("messages", [])
    if not messages:
        print("(no console messages — run this after page interaction to capture logs)")
    else:
        for msg in messages:
            level = msg.get("level", "log").upper()
            text = msg.get("text", "")
            print(f"[{level}] {text}")


# ─── Wait & State ─────────────────────────────────────────────────────────────

@cli.command()
@click.argument("target_id")
@click.argument("selector_or_ms", required=False)
@click.option("--text", "wait_text", default="", help="Wait for text to appear on page.")
@click.option("--fn", "wait_fn", default="", help="Wait for JS expression to be truthy.")
@click.option("--state", default="visible", type=click.Choice(["visible", "hidden"]), help="Element state to wait for.")
@click.option("--timeout", default=15000, help="Timeout in ms (default: 15000).")
def wait(target_id: str, selector_or_ms: Optional[str], wait_text: str, wait_fn: str, state: str, timeout: int):
    """等待元素、毫秒数、文本出现或 JS 条件成立。

    \b
    示例：
      webcli wait <id> "#submit-btn"           # 等待元素可见
      webcli wait <id> 2000                    # 等待 2 秒
      webcli wait <id> --text "加载完成"        # 等待页面出现指定文本
      webcli wait <id> --fn "window.loaded"    # 等待 JS 条件为真
    """
    path = f"/wait?target={target_id}&timeout={timeout}&state={state}"
    if selector_or_ms:
        if selector_or_ms.isdigit():
            path += f"&ms={selector_or_ms}"
        else:
            path += f"&selector={urllib.parse.quote(selector_or_ms, safe='')}"
    if wait_text:
        path += f"&text={urllib.parse.quote(wait_text, safe='')}"
    if wait_fn:
        path += f"&fn={urllib.parse.quote(wait_fn, safe='')}"
    result = http_get(path, timeout=timeout + 5000)
    print(json.dumps(result, indent=2))


@cli.command(name="is")
@click.argument("target_id")
@click.argument("check", type=click.Choice(["visible", "enabled", "checked"]))
@click.argument("selector")
def is_state(target_id: str, check: str, selector: str):
    """检查元素状态：visible（可见）、enabled（可用）、checked（已勾选）。"""
    path = f"/is?target={target_id}&check={check}&selector={urllib.parse.quote(selector, safe='')}"
    result = http_get(path)
    print(json.dumps(result, indent=2))


# ─── Semantic Find ────────────────────────────────────────────────────────────

@cli.command()
@click.argument("target_id")
@click.argument("by", type=click.Choice(["role", "text", "label", "placeholder", "testid", "alt"]))
@click.argument("value")
@click.argument("action", type=click.Choice(["click", "text", "html", "fill", "focus", "hover"]), default="click")
@click.option("--name", "name_filter", default="", help="Filter role elements by accessible name.")
@click.option("--exact", is_flag=True, help="Require exact text/name match.")
@click.option("--nth", default=0, help="Use nth match (0-indexed, default: 0).")
@click.option("--fill-value", default="", help="Value to fill (required when action=fill).")
@click.option("--snapshot", is_flag=True, default=False, help="Auto-capture accessibility tree after action.")
@click.option("--depth", default=3, help="Snapshot tree depth (default: 3, only used with --snapshot).")
def find(target_id: str, by: str, value: str, action: str, name_filter: str, exact: bool, nth: int, fill_value: str, snapshot: bool, depth: int):
    """按语义定位器查找元素并执行操作（无需知道 CSS 选择器）。

    \b
    示例：
      webcli find <id> role button click --name "提交"
      webcli find <id> text "登录" click
      webcli find <id> text "登录" click --snapshot    # 点击后自动获取无障碍树
      webcli find <id> label "邮箱" fill --fill-value "user@example.com"
      webcli find <id> placeholder "搜索..." fill --fill-value "hello"
      webcli find <id> testid "submit-btn" click
      webcli find <id> text "item" click --nth 2
    """
    path = f"/find?target={target_id}&by={by}&value={urllib.parse.quote(value, safe='')}&action={action}"
    if name_filter:
        path += f"&name={urllib.parse.quote(name_filter, safe='')}"
    if exact:
        path += "&exact=true"
    if nth:
        path += f"&nth={nth}"
    if fill_value:
        path += f"&fill_value={urllib.parse.quote(fill_value, safe='')}"
    result = http_get(path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if snapshot and action == "click" and result.get("clicked"):
        import time
        time.sleep(0.5)
        snap = http_get(f"/snapshot?target={target_id}&depth={depth}")
        print(snap.get("snapshot", ""))


# ─── Cookies ─────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("target_id")
@click.option("--domain", default="", help="Filter cookies by domain (substring match).")
@click.option("--url", "url_filter", default="", help="Get cookies for a specific URL.")
def cookies(target_id: str, domain: str, url_filter: str):
    """获取当前页面的 Cookie。

    \b
    示例：
      webcli cookies <id>                          # 当前页面所有 Cookie
      webcli cookies <id> --domain .example.com    # 按域名过滤
      webcli cookies <id> --url https://api.example.com/
    """
    path = f"/cookies?target={target_id}"
    if domain:
        path += f"&domain={urllib.parse.quote(domain, safe='')}"
    if url_filter:
        encoded_url = urllib.parse.quote(url_filter, safe=':/?#[]@!$&\'()*+,;=')
        path += f"&url={encoded_url}"
    result = http_get(path)
    print(json.dumps(result, indent=2, ensure_ascii=False))


@cli.command(name="cookies-set")
@click.argument("target_id")
@click.argument("name")
@click.argument("value")
@click.option("--domain", default="", help="Cookie domain.")
@click.option("--path", "cookie_path", default="/", help="Cookie path.")
@click.option("--http-only", is_flag=True, help="Set HttpOnly flag.")
@click.option("--secure", is_flag=True, help="Set Secure flag.")
def cookies_set(target_id: str, name: str, value: str, domain: str, cookie_path: str, http_only: bool, secure: bool):
    """设置 Cookie。"""
    body: dict = {"name": name, "value": value, "path": cookie_path}
    if domain:
        body["domain"] = domain
    if http_only:
        body["httpOnly"] = True
    if secure:
        body["secure"] = True
    result = http_post_json(f"/cookies/set?target={target_id}", body)
    print(json.dumps(result, indent=2))


@cli.command(name="cookies-clear")
@click.argument("target_id")
def cookies_clear(target_id: str):
    """清除浏览器中所有 Cookie。"""
    result = http_get(f"/cookies/clear?target={target_id}")
    print(json.dumps(result, indent=2))


# ─── Storage ─────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("target_id")
@click.argument("key", required=False)
@click.option("--type", "storage_type", default="local", type=click.Choice(["local", "session"]), help="Storage type (default: local).")
def storage(target_id: str, key: Optional[str], storage_type: str):
    """获取 localStorage 或 sessionStorage 的值。

    \b
    示例：
      webcli storage <id>                    # 所有 localStorage 条目
      webcli storage <id> --type session     # 所有 sessionStorage 条目
      webcli storage <id> token              # 获取指定 key 的值
    """
    path = f"/storage?target={target_id}&type={storage_type}"
    if key:
        path += f"&key={urllib.parse.quote(key, safe='')}"
    result = http_get(path)
    value = result.get("value")
    if isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, indent=2, ensure_ascii=False))


@cli.command(name="storage-set")
@click.argument("target_id")
@click.argument("key")
@click.argument("value")
@click.option("--type", "storage_type", default="local", type=click.Choice(["local", "session"]), help="Storage type (default: local).")
def storage_set(target_id: str, key: str, value: str, storage_type: str):
    """设置 localStorage 或 sessionStorage 的值。"""
    result = http_post_json(f"/storage/set?target={target_id}&type={storage_type}", {"key": key, "value": value})
    print(json.dumps(result, indent=2))


@cli.command(name="storage-clear")
@click.argument("target_id")
@click.option("--type", "storage_type", default="local", type=click.Choice(["local", "session"]), help="Storage type (default: local).")
def storage_clear(target_id: str, storage_type: str):
    """清空 localStorage 或 sessionStorage。"""
    result = http_get(f"/storage/clear?target={target_id}&type={storage_type}")
    print(json.dumps(result, indent=2))


# ─── Dialog ──────────────────────────────────────────────────────────────────

@cli.command(name="dialog-status")
@click.argument("target_id")
def dialog_status(target_id: str):
    """检查当前是否有 JavaScript 对话框（alert/confirm/prompt）弹出。"""
    result = http_get(f"/dialog/status?target={target_id}")
    print(json.dumps(result, indent=2))


@cli.command(name="dialog-accept")
@click.argument("target_id")
@click.argument("prompt_text", required=False, default="")
def dialog_accept(target_id: str, prompt_text: str):
    """确认（接受）JavaScript 对话框。prompt 对话框可传入文本。"""
    result = http_post(f"/dialog/accept?target={target_id}", prompt_text)
    print(json.dumps(result, indent=2))


@cli.command(name="dialog-dismiss")
@click.argument("target_id")
def dialog_dismiss(target_id: str):
    """取消（关闭）JavaScript 对话框。"""
    result = http_get(f"/dialog/dismiss?target={target_id}")
    print(json.dumps(result, indent=2))


# ─── Network capture ─────────────────────────────────────────────────────────

@cli.command(name="network-start")
@click.argument("target_id")
def network_start(target_id: str):
    """开始捕获标签页的网络请求。"""
    result = http_get(f"/network/start?target={target_id}")
    print(json.dumps(result, indent=2))


@cli.command(name="network-stop")
@click.argument("target_id")
def network_stop(target_id: str):
    """停止捕获网络请求。"""
    result = http_get(f"/network/stop?target={target_id}")
    print(json.dumps(result, indent=2))


# ─── Page analysis ─────────────────────────────────────────────────────────────

def _fetch_raw_html(url: str, timeout_seconds: int = 15) -> str:
    """Fetch raw HTML via urllib (no browser) for SSR detection."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _detect_rendering(snapshot_text: str, raw_html: str) -> dict:
    """Compare snapshot (accessibility tree) vs raw HTML to determine rendering type."""
    # Count meaningful text nodes in snapshot (lines with actual text, not just tag names)
    snapshot_lines = snapshot_text.strip().splitlines() if snapshot_text else []
    snapshot_text_nodes = [line for line in snapshot_lines if '"' in line or any(c.isdigit() for c in line.split(']')[-1] if c)]
    snapshot_node_count = len(snapshot_lines)

    # Analyze raw HTML
    html_length = len(raw_html)
    has_initial_state = bool(re.search(r'window\.__\w+\s*=\s*[{\[]', raw_html))
    has_json_script = bool(re.search(r'<script[^>]*type="application/json"[^>]*>', raw_html))
    has_next_data = bool(re.search(r'__NEXT_DATA__|__NUXT__|__INITIAL_STATE__', raw_html))

    # Count text content density in HTML body
    body_match = re.search(r'<body[^>]*>(.*)</body>', raw_html, re.DOTALL)
    body_html = body_match.group(1) if body_match else raw_html
    # Strip tags to get pure text
    pure_text = re.sub(r'<script[^>]*>.*?</script>', '', body_html, flags=re.DOTALL)
    pure_text = re.sub(r'<style[^>]*>.*?</style>', '', pure_text, flags=re.DOTALL)
    pure_text = re.sub(r'<[^>]+>', ' ', pure_text)
    pure_text = re.sub(r'\s+', ' ', pure_text).strip()
    html_text_length = len(pure_text)

    # Detect frameworks
    frameworks = []
    if re.search(r'react|__REACT|_reactRoot|data-reactroot', raw_html, re.I):
        frameworks.append("React")
    if re.search(r'ng-app|ng-controller|angular', raw_html, re.I):
        frameworks.append("Angular")
    if re.search(r'__vue__|data-v-|vue\.js|vue\.min\.js', raw_html, re.I):
        frameworks.append("Vue")
    if re.search(r'__NEXT_DATA__|_next/', raw_html):
        frameworks.append("Next.js")
    if re.search(r'__NUXT__|_nuxt/', raw_html):
        frameworks.append("Nuxt")
    if re.search(r'svelte|__svelte', raw_html, re.I):
        frameworks.append("Svelte")

    # Determine rendering type
    # SSR: raw HTML has substantial text content (>200 chars of pure text in body)
    # CSR: raw HTML is mostly empty shell, data loaded via JS
    is_ssr = html_text_length > 200
    is_hydrated = is_ssr and (has_initial_state or has_next_data or has_json_script)

    if is_ssr and not is_hydrated:
        rendering = "SSR (传统服务端渲染)"
        rendering_detail = "HTML 直出完整内容，无需 JS 即可获取数据"
    elif is_hydrated:
        rendering = "SSR + Hydration (同构渲染)"
        rendering_detail = "服务端直出 HTML + 客户端 JS 激活交互"
    elif html_text_length < 50:
        rendering = "CSR (客户端渲染)"
        rendering_detail = "HTML 为空壳，所有内容由 JS 动态生成"
    else:
        rendering = "混合渲染"
        rendering_detail = "部分内容直出，部分由 JS 动态加载"

    return {
        "rendering": rendering,
        "rendering_detail": rendering_detail,
        "is_ssr": is_ssr,
        "is_hydrated": is_hydrated,
        "frameworks": frameworks,
        "html_text_length": html_text_length,
        "html_total_length": html_length,
        "snapshot_node_count": snapshot_node_count,
        "has_initial_state": has_initial_state,
    }


def _detect_page_features(raw_html: str, snapshot_text: str) -> dict:
    """Detect page features like pagination, lazy loading, search, etc."""
    features = {}

    # Pagination
    has_pagination = bool(re.search(r'page=\d|pagination|pager|pg-item|page-num|下一页|上一页|totalPage', raw_html, re.I))
    pagination_pattern = ""
    page_match = re.search(r'totalPage\s*=\s*(\d+)', raw_html)
    if page_match:
        pagination_pattern = f"共 {page_match.group(1)} 页, URL 参数 ?page=N"
    elif has_pagination:
        pagination_pattern = "检测到分页控件"
    features["pagination"] = {"detected": has_pagination, "pattern": pagination_pattern}

    # Lazy loading
    has_lazy = bool(re.search(r'lazyload|lazy-load|data-src|data-original|loading="lazy"|IntersectionObserver', raw_html, re.I))
    features["lazy_loading"] = has_lazy

    # Infinite scroll
    has_infinite = bool(re.search(r'infinite.?scroll|load.?more|scroll.?load|滚动加载|加载更多', raw_html, re.I))
    features["infinite_scroll"] = has_infinite

    # Search
    has_search = bool(re.search(r'<input[^>]*type="search"|searchbox|search-input|搜索', raw_html, re.I))
    if not has_search and snapshot_text:
        has_search = bool(re.search(r'searchbox|textbox.*搜索|textbox.*search', snapshot_text, re.I))
    features["search"] = has_search

    # Login
    has_login = bool(re.search(r'登录|login|sign.?in|log.?in', raw_html, re.I))
    features["login_required"] = has_login

    # WebSocket
    has_websocket = bool(re.search(r'WebSocket|wss?://', raw_html, re.I))
    features["websocket"] = has_websocket

    # Filters
    has_filters = bool(re.search(r'filter|筛选|排序|sort|tab-btn|sub-type', raw_html, re.I))
    features["filters"] = has_filters

    return features


def _analyze_api_requests(requests_list: list) -> list:
    """Identify likely data API requests from network captures."""
    api_requests = []
    skip_extensions = {'.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.eot', '.map'}
    skip_domains = {'google', 'facebook', 'doubleclick', 'analytics', 'tracking', 'beacon', 'monitor', 'apm', 'sentry', 'log.'}

    for req in requests_list:
        url = req.get("url", "")
        resource_type = (req.get("resourceType") or "").lower()
        method = req.get("method", "GET")
        status = req.get("status", 0)

        # Skip static resources
        if any(url.lower().endswith(ext) for ext in skip_extensions):
            continue
        # Skip tracking/analytics
        if any(domain in url.lower() for domain in skip_domains):
            continue
        # Only interested in XHR/Fetch or unknown types with JSON-like URLs
        if resource_type not in ("xhr", "fetch", ""):
            continue
        # Skip failed requests (0 status = pending)
        if status and (status < 200 or status >= 400):
            continue

        api_requests.append({
            "url": url[:200],
            "method": method,
            "status": status,
            "type": resource_type,
            "request_id": req.get("requestId", ""),
            "has_body": req.get("hasBody", False),
        })

    return api_requests


@cli.command()
@click.argument("url")
@click.option("--close", "auto_close", is_flag=True, default=False, help="Auto-close the tab after analysis.")
@click.option("--wait", "wait_seconds", default=3, help="Seconds to wait for XHR requests after page load (default: 3).")
@click.option("--depth", default=5, help="Snapshot tree depth (default: 5).")
def analyze(url: str, auto_close: bool, wait_seconds: int, depth: int):
    """分析页面结构，输出渲染类型、数据来源、关键接口等结构化报告。

    自动完成：打开页面 → 获取无障碍树 → 抓取原始 HTML → 分析网络请求 → 输出报告。

    \b
    示例：
      webcli analyze https://car.yiche.com/newcar/salesrank/
      webcli analyze https://example.com --close     # 分析完自动关闭 tab
      webcli analyze https://example.com --wait 5    # 等待 5 秒让异步请求完成
    """
    from urllib.parse import urlparse as _urlparse

    parsed = _urlparse(url)
    domain = parsed.netloc or parsed.hostname or url

    print(f"📋 正在分析页面: {url}")
    print(f"{'─' * 60}")

    # Step 1: Open page with monitoring + snapshot
    print("\n⏳ [1/4] 打开页面 + 网络监控 + 无障碍树...")
    encoded_url = urllib.parse.quote(url, safe=':/?#[]@!$&\'()*+,;=')
    path = f"/network/open-monitored?url={encoded_url}&snapshot=1&depth={depth}"
    try:
        result = http_get(path, timeout=30000)
    except Exception as exc:
        print(f"❌ 打开页面失败: {exc}")
        return

    target_id = result.get("targetId", "")
    snapshot_text = result.get("snapshot", "")
    final_url = result.get("url", url)
    node_count = result.get("nodeCount", 0)

    if final_url != url:
        print(f"   ↳ 重定向到: {final_url}")
    print(f"   ✅ targetId: {target_id}")
    print(f"   ✅ 无障碍树: {node_count} 个节点")

    # Step 2: Fetch raw HTML via curl (no browser)
    print("\n⏳ [2/4] 获取原始 HTML (curl)...")
    raw_html = _fetch_raw_html(final_url or url)
    if raw_html:
        print(f"   ✅ HTML 大小: {len(raw_html):,} 字节")
    else:
        print("   ⚠️  无法通过 curl 获取 HTML（可能需要登录或有反爬）")

    # Step 3: Wait for XHR and collect network requests
    print(f"\n⏳ [3/4] 等待异步请求 ({wait_seconds}s)...")
    time.sleep(wait_seconds)
    try:
        net_result = http_get(f"/network/requests?target={target_id}&type=xhr,fetch", timeout=10000)
        network_list = net_result.get("requests", [])
        print(f"   ✅ 捕获 {len(network_list)} 个 XHR/Fetch 请求")
    except Exception:
        network_list = []
        print("   ⚠️  获取网络请求失败")

    # Step 4: Analyze and output report
    print(f"\n⏳ [4/4] 生成分析报告...")

    rendering_info = _detect_rendering(snapshot_text, raw_html)
    page_features = _detect_page_features(raw_html, snapshot_text)
    api_list = _analyze_api_requests(network_list)

    print(f"\n{'═' * 60}")
    print(f"📊 页面分析报告")
    print(f"{'═' * 60}")

    # Basic info
    print(f"\n🔹 **URL**: {final_url or url}")
    print(f"🔹 **域名**: {domain}")

    # Rendering
    print(f"\n### 渲染方式")
    print(f"   类型: {rendering_info['rendering']}")
    print(f"   说明: {rendering_info['rendering_detail']}")
    if rendering_info['frameworks']:
        print(f"   框架: {', '.join(rendering_info['frameworks'])}")
    print(f"   HTML 文本量: {rendering_info['html_text_length']:,} 字符")
    print(f"   HTML 总大小: {rendering_info['html_total_length']:,} 字节")
    print(f"   无障碍树节点: {rendering_info['snapshot_node_count']} 个")

    # Data source recommendation
    print(f"\n### 数据来源判断")
    if rendering_info['is_ssr'] and not api_list:
        print(f"   ✅ 推荐方案: requests + 正则/BeautifulSoup 解析 HTML")
        print(f"   原因: SSR 直出，数据在 HTML 中，无需浏览器")
    elif api_list:
        print(f"   ✅ 推荐方案: requests 直接调用 API 接口")
        print(f"   原因: 发现 {len(api_list)} 个数据接口")
    elif rendering_info['is_ssr']:
        print(f"   ✅ 推荐方案: requests 解析 HTML + API 接口补充")
        print(f"   原因: SSR 直出 + 有异步数据接口")
    else:
        print(f"   ⚠️  推荐方案: 浏览器自动化 (eval 提取 DOM)")
        print(f"   原因: CSR 渲染，数据由 JS 动态生成")

    # Page features
    print(f"\n### 页面特征")
    pagination = page_features.get("pagination", {})
    print(f"   分页: {'✅ ' + pagination.get('pattern', '有') if pagination.get('detected') else '❌ 无'}")
    print(f"   图片懒加载: {'✅' if page_features.get('lazy_loading') else '❌'}")
    print(f"   无限滚动: {'✅' if page_features.get('infinite_scroll') else '❌'}")
    print(f"   搜索框: {'✅' if page_features.get('search') else '❌'}")
    print(f"   筛选控件: {'✅' if page_features.get('filters') else '❌'}")
    print(f"   登录入口: {'✅' if page_features.get('login_required') else '❌'}")
    print(f"   WebSocket: {'✅' if page_features.get('websocket') else '❌'}")

    # API requests
    if api_list:
        print(f"\n### 关键接口 ({len(api_list)} 个)")
        for i, api in enumerate(api_list[:10], 1):
            status_str = str(api['status']) if api['status'] else "pending"
            body_flag = " 📦" if api['has_body'] else ""
            print(f"   {i}. [{status_str}] {api['method']} {api['url']}{body_flag}")
            if api['request_id']:
                print(f"      webcli network-request {target_id} {api['request_id']}")
        if len(api_list) > 10:
            print(f"   ... 还有 {len(api_list) - 10} 个接口")
    else:
        print(f"\n### 关键接口")
        print(f"   未发现 XHR/Fetch 数据接口（纯 SSR 或请求尚未触发）")

    # Next steps
    print(f"\n### 后续操作")
    print(f"   webcli snapshot {target_id}              # 查看完整无障碍树")
    print(f"   webcli network-requests {target_id}      # 查看所有网络请求")
    print(f"   webcli eval {target_id} \"...\"            # 执行 JS 提取数据")
    print(f"   webcli close {target_id}                 # 关闭标签页")

    # Auto close
    if auto_close:
        try:
            http_get(f"/close?target={target_id}")
            print(f"\n🧹 已自动关闭标签页 {target_id}")
        except Exception:
            print(f"\n⚠️  关闭标签页失败: {target_id}")
    else:
        print(f"\n💡 标签页保持打开: {target_id}")

    # JSON output for programmatic use
    report = {
        "url": final_url or url,
        "domain": domain,
        "targetId": target_id,
        "rendering": rendering_info,
        "features": page_features,
        "apis": api_list,
        "snapshot_nodes": node_count,
    }
    print(f"\n# JSON: {json.dumps(report, ensure_ascii=False)}")


@cli.command(name="network-requests")
@click.argument("target_id")
@click.option("--filter", "url_filter", default="", help="Filter by URL substring.")
@click.option("--method", default="", help="Filter by HTTP method (GET, POST, PUT...).")
@click.option("--type", "res_type", default="", help="Filter by resource type (xhr, fetch, document, script, stylesheet, image...).")
@click.option("--status", default="", help="Filter by status code (200, 2xx, 400-499).")
@click.option("--limit", default=0, help="Return only the most recent N requests (0 = all).")
@click.option("--body", is_flag=True, default=False, help="Include response body for each request (saves a separate network-request call).")
def network_requests(target_id: str, url_filter: str, method: str, res_type: str, status: str, limit: int, body: bool):
    """列出捕获的网络请求，支持多种过滤条件。

    \b
    示例：
      webcli network-requests <id>
      webcli network-requests <id> --type xhr,fetch
      webcli network-requests <id> --type xhr,fetch --body   # 列表 + 响应体一步到位
      webcli network-requests <id> --filter /api/ --method POST
      webcli network-requests <id> --status 2xx
      webcli network-requests <id> --limit 20
    """
    path = f"/network/requests?target={target_id}"
    if url_filter:
        path += f"&filter={urllib.parse.quote(url_filter, safe='')}"
    if method:
        path += f"&method={method.upper()}"
    if res_type:
        path += f"&type={urllib.parse.quote(res_type, safe='')}"
    if status:
        path += f"&status={status}"
    if limit:
        path += f"&limit={limit}"
    if body:
        path += "&body=1"
    result = http_get(path, timeout=60000)
    requests_list = result.get("requests", [])
    total = result.get("total", 0)
    returned = result.get("returned", len(requests_list))
    suffix = f" (showing {returned})" if returned < total else ""
    print(f"Total: {total} requests{suffix}\n")
    print(f"  {'':4} {'ST':<6} {'METHOD':<6} {'TYPE':<12} {'REQUEST-ID':<16} URL")
    print(f"  {'-'*4} {'-'*6} {'-'*6} {'-'*12} {'-'*16} {'-'*40}")
    for req in requests_list:
        status_str = str(req.get("status") or "-").ljust(4)
        method_str = (req.get("method") or "-").ljust(6)
        type_str = (req.get("resourceType") or "-").ljust(12)
        url_str = (req.get("url") or "")[:70]
        req_id = req.get("requestId") or ""
        body_flag = "📦" if req.get("hasBody") else "  "
        failed_flag = "❌" if req.get("failed") else "  "
        print(f"  {body_flag}{failed_flag} [{status_str}] {method_str} {type_str} {url_str}")
        print(f"       webcli network-request {target_id} {req_id}")
        response_body = req.get("responseBody")
        if response_body is not None:
            print(f"       --- response body ---")
            print(f"       {response_body[:2000]}")
            if len(response_body) > 2000:
                print(f"       ... ({len(response_body)} chars total, truncated)")
            print()


@cli.command(name="network-request")
@click.argument("target_id")
@click.argument("request_id")
def network_request(target_id: str, request_id: str):
    """获取单个请求的完整详情（含响应体）。

    \b
    示例：
      webcli network-request <targetId> <requestId>
      # targetId 来自：webcli targets
      # requestId 来自：webcli network-requests <targetId>
    """
    result = http_get(f"/network/request?target={target_id}&id={request_id}", timeout=30000)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n# Next: webcli network-requests {target_id}  |  webcli network-clear {target_id}")


@cli.command(name="network-clear")
@click.argument("target_id")
def network_clear(target_id: str):
    """清空已捕获的请求记录（保持捕获继续运行）。"""
    result = http_get(f"/network/clear?target={target_id}")
    print(json.dumps(result, indent=2))


# ─── Script Capture ──────────────────────────────────────────────────────────

@cli.command(name="scripts-enable")
@click.argument("target_id")
def scripts_enable(target_id: str):
    """启用 Debugger 域，开始捕获标签页加载的所有脚本。

    必须在页面加载前调用，之后页面加载的所有脚本都会被追踪。

    \b
    示例：
      webcli scripts-enable <id>
      TARGET=$(webcli new https://example.com --id-only)
      webcli scripts-enable $TARGET
      webcli navigate $TARGET https://example.com
      webcli scripts-list $TARGET
    """
    result = http_get(f"/scripts/enable?target={target_id}")
    print(json.dumps(result, indent=2))


@cli.command(name="scripts-list")
@click.argument("target_id", required=False, default="")
@click.option("--filter", "url_filter", default="", help="Filter scripts by URL keyword (case-insensitive).")
@click.option("--all", "include_all", is_flag=True, default=False, help="Include chrome-extension:// scripts (not retrievable via scripts-source).")
def scripts_list(target_id: str, url_filter: str, include_all: bool):
    """列出标签页已捕获的脚本（默认排除 chrome-extension 脚本）。

    \b
    示例：
      webcli scripts-list                             # 所有标签页的页面脚本
      webcli scripts-list <targetId>                  # 指定标签页
      webcli scripts-list <targetId> --filter chunk   # 按 URL 关键词过滤
      webcli scripts-list <targetId> --all            # 包含 chrome-extension 脚本
    """
    params = []
    if target_id:
        params.append(f"target={target_id}")
    if url_filter:
        params.append(f"filter={urllib.parse.quote(url_filter)}")
    if include_all:
        params.append("all=1")
    path = "/scripts/list" + (f"?{'&'.join(params)}" if params else "")
    result = http_get(path)
    print(json.dumps(result, indent=2, ensure_ascii=False))


@cli.command(name="scripts-source")
@click.argument("target_id")
@click.argument("script_id")
@click.option("--output", "-o", default="", help="Save source to file instead of printing.")
def scripts_source(target_id: str, script_id: str, output: str):
    """获取指定脚本的源码。

    \b
    示例：
      webcli scripts-source <targetId> <scriptId>
      webcli scripts-source <targetId> <scriptId> -o script.js
    """
    result = http_get(f"/scripts/source?target={target_id}&scriptId={script_id}", timeout=30000)
    if output:
        Path(output).write_text(result.get("source", ""), encoding="utf-8")
        print(json.dumps({
            "scriptId": result.get("scriptId"),
            "url": result.get("url"),
            "sourceLength": result.get("sourceLength"),
            "savedTo": output,
        }, indent=2))
    else:
        print(f"# Script: {result.get('scriptId')}")
        print(f"# URL: {result.get('url')}")
        print(f"# Length: {result.get('sourceLength')} characters\n")
        print(result.get("source", ""))


# ─── Utility ─────────────────────────────────────────────────────────────────

@cli.command()
def health():
    """健康检查 — 显示 Proxy 状态和 Chrome 连接情况。"""
    result = http_get("/health")
    print(json.dumps(result, indent=2))


# ─── Experience commands (pure local file ops, no Proxy needed) ───────────────

# Experience root: unified under ~/.agents/skills/webcli_exp/
# This path is agent-platform-agnostic — the same experience library is shared
# across Claude, Cursor, Windsurf, and any other agent that installs this skill.
# Override via WEB_CLI_EXPERIENCE_DIR env var if needed.
EXPERIENCE_DIR = Path(
    os.environ.get("WEB_CLI_EXPERIENCE_DIR")
    or Path.home() / ".agents" / "skills" / "webcli_exp"
)

# Site-scoped categories: experience/sites/{domain}/{category}/{name}.md
# Global categories: experience/{category}/{name}.md
VALID_CATEGORIES = ("api", "login", "action", "anti-crawl")
SITE_SCOPED_CATEGORIES = ("api", "login", "action")
GLOBAL_CATEGORIES = ("anti-crawl",)


def _exp_path(category: str, site: str, name: str) -> Path:
    """Resolve the markdown file path for a given experience entry.

    Site-scoped (api/login/action): experience/sites/{domain}/{category}/{name}.md
    Global (anti-crawl):            experience/{category}/{name}.md
    """
    if category in SITE_SCOPED_CATEGORIES:
        return EXPERIENCE_DIR / "sites" / site / category / f"{name}.md"
    return EXPERIENCE_DIR / category / f"{name}.md"


def _exp_frontmatter(category: str, site: str, name: str) -> str:
    """Generate default frontmatter for a new experience file."""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if category in SITE_SCOPED_CATEGORIES:
        base = f"site: {site}\ncategory: {category}\ndescription: {name} 经验\ntags: []\nstatus: verified\ncreated_at: {now}\nupdated_at: {now}\nlast_used_at: {now}\nlast_used_status: success\n"
    else:
        base = f"category: {category}\ndescription: {name} 经验\ntags: []\nstatus: verified\ncreated_at: {now}\nupdated_at: {now}\nlast_used_at: {now}\nlast_used_status: success\n"
    return f"---\n{base}---\n\n"


@cli.group(cls=AliasUnderscoreGroup)
def exp():
    """经验库管理（纯本地文件操作，不依赖 Proxy）。

    \b
    分类说明（站点级）：
      api        接口数据获取经验（URL、参数、响应字段、加密破解）
      login      自动化登录经验（登录流程、Cookie 获取、验证码处理）
      action     自动化操作经验（页面交互流程、表单提交、上传、跨站点流程等）

    \b
    分类说明（全局级，不绑定站点）：
      anti-crawl 反爬对抗经验（跨站点通用，按反爬类型组织）

    \b
    示例：
      webcli exp list                          # 列出所有经验
      webcli exp list yiche.com                # 列出某站点经验
      webcli exp api yiche.com rank            # 查看易车销量榜接口经验
      webcli exp login taobao.com              # 查看淘宝登录经验
      webcli exp action xiaohongshu.com post   # 查看小红书发帖操作经验
      webcli exp action sls query-log          # 查看查询 SLS 日志的流程经验
      webcli exp anti-crawl cloudflare         # 查看 Cloudflare 对抗经验
      webcli exp save api yiche.com rank       # 从 stdin 保存/更新站点级经验
      webcli exp save action sls query-log     # 从 stdin 保存/更新流程经验
      webcli exp edit api yiche.com rank       # 用编辑器打开经验文件
      webcli exp update api yiche.com rank --last-used-status success  # 更新使用状态
      webcli exp del api yiche.com rank         # 删除经验（有确认提示）
      webcli exp del api yiche.com rank --yes   # 跳过确认直接删除
    """


@exp.command(name="list")
@click.argument("site", required=False, default="")
def exp_list(site: str):
    """列出所有经验，或指定站点的经验。"""
    if not EXPERIENCE_DIR.exists():
        click.echo("经验库为空（references/ 目录不存在）")
        return

    entries: list[tuple[str, str, str]] = []

    sites_dir = EXPERIENCE_DIR / "sites"
    if sites_dir.exists():
        for site_dir in sorted(p for p in sites_dir.iterdir() if p.is_dir()):
            if site and site_dir.name != site:
                continue
            for category_dir in sorted(site_dir.iterdir()):
                if not category_dir.is_dir():
                    continue
                for exp_file in sorted(category_dir.glob("*.md")):
                    entries.append((category_dir.name, site_dir.name, exp_file.stem))

    for global_cat in GLOBAL_CATEGORIES:
        global_dir = EXPERIENCE_DIR / global_cat
        if global_dir.exists() and not site:
            for exp_file in sorted(global_dir.glob("*.md")):
                entries.append((global_cat, "-", exp_file.stem))

    if not entries:
        click.echo(f"没有找到{'站点 ' + site + ' 的' if site else ''}经验记录")
        return

    click.echo(f"{'分类':<12} {'站点':<25} {'名称'}")
    click.echo("-" * 60)
    for category, site_name, name in entries:
        click.echo(f"{category:<12} {site_name:<25} {name}")


@exp.command(name="show")
@click.argument("category", type=click.Choice(VALID_CATEGORIES))
@click.argument("site")
@click.argument("name")
def exp_show(category: str, site: str, name: str):
    """查看某条经验的完整内容。"""
    exp_file = _exp_path(category, site, name)
    if not exp_file.exists():
        click.echo(f"经验不存在：{exp_file}", err=True)
        click.echo(f"提示：使用 'webcli exp save {category} {site} {name}' 创建", err=True)
        sys.exit(1)
    click.echo(exp_file.read_text(encoding="utf-8"))


@exp.command(name="save")
@click.argument("category", type=click.Choice(VALID_CATEGORIES))
@click.argument("site")
@click.argument("name")
@click.option("--append", is_flag=True, default=False, help="追加到已有文件末尾（默认覆盖）")
def exp_save(category: str, site: str, name: str, append: bool):
    """从 stdin 保存经验（Agent 写入时使用）。

    \b
    示例：
      echo '# 易车销量榜接口' | webcli exp save api yiche.com rank
      cat experience.md | webcli exp save login taobao.com main
    """
    exp_file = _exp_path(category, site, name)
    exp_file.parent.mkdir(parents=True, exist_ok=True)

    content = sys.stdin.read()
    if not content.strip():
        click.echo("错误：stdin 内容为空", err=True)
        sys.exit(1)

    if not content.startswith("---"):
        content = _exp_frontmatter(category, site, name) + content
    else:
        from datetime import date
        today = date.today().isoformat()
        content = content.replace("updated_at: ", f"updated_at: {today}  # was: ", 1)

    is_new = not exp_file.exists()
    if append and not is_new:
        existing = exp_file.read_text(encoding="utf-8")
        exp_file.write_text(existing.rstrip() + "\n\n" + content, encoding="utf-8")
        click.echo(f"✅ 已追加到：{exp_file}")
    else:
        exp_file.write_text(content, encoding="utf-8")
        click.echo(f"✅ 已{'创建' if is_new else '更新'}：{exp_file}")


@exp.command(name="edit")
@click.argument("category", type=click.Choice(VALID_CATEGORIES))
@click.argument("site")
@click.argument("name")
def exp_edit(category: str, site: str, name: str):
    """用系统编辑器打开经验文件（文件不存在时自动创建模板）。"""
    exp_file = _exp_path(category, site, name)
    exp_file.parent.mkdir(parents=True, exist_ok=True)

    if not exp_file.exists():
        exp_file.write_text(
            _exp_frontmatter(category, site, name) + f"# {name}\n\n",
            encoding="utf-8",
        )
        click.echo(f"已创建模板：{exp_file}")

    editor = os.environ.get("EDITOR", "vi")
    os.execvp(editor, [editor, str(exp_file)])

@exp.command(name="del")
@click.argument("category", type=click.Choice(VALID_CATEGORIES))
@click.argument("site")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, default=False, help="跳过确认直接删除。")
def exp_rm(category: str, site: str, name: str, yes: bool):
    """删除一条经验记录（默认有确认提示）。

    \b
    示例：
      webcli exp del api yiche.com rank         # 删除前需确认
      webcli exp del anti-crawl - cloudflare    # 删除全局经验
      webcli exp del api yiche.com rank --yes   # 跳过确认直接删除
    """
    exp_file = _exp_path(category, site, name)
    if not exp_file.exists():
        click.echo(f"经验不存在：{exp_file}", err=True)
        sys.exit(1)

    click.echo(f"将要删除：{exp_file}")
    if not yes:
        confirmed = click.confirm("确认删除？此操作不可撤销", default=False)
        if not confirmed:
            click.echo("已取消")
            return

    exp_file.unlink()
    click.echo(f"✅ 已删除：{exp_file}")

    # 如果父目录为空则一并清理，避免留下空目录
    parent = exp_file.parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
        click.echo(f"   （已清理空目录：{parent}）")


@exp.command(name="update")
@click.argument("category", type=click.Choice(VALID_CATEGORIES))
@click.argument("site")
@click.argument("name")
@click.option("--last-used-at", "last_used_at", default="", help="更新 last_used_at 时间（格式：YYYY-MM-DD HH:MM:SS），不指定则使用当前时间。")
@click.option("--last-used-status", "last_used_status", default="", type=click.Choice(["success", "failed"]), help="更新 last_used_status 状态。")
def exp_update(category: str, site: str, name: str, last_used_at: str, last_used_status: str):
    """更新经验的使用记录（last_used_at 和 last_used_status）或追加内容。

    \b
    示例：
      webcli exp update api yiche.com rank --last-used-status success
      webcli exp update api yiche.com rank --last-used-status failed
      webcli exp update api yiche.com rank --last-used-at "2026-04-07 13:54:00" --last-used-status success
    """
    exp_file = _exp_path(category, site, name)
    if not exp_file.exists():
        click.echo(f"经验不存在：{exp_file}", err=True)
        sys.exit(1)

    content = exp_file.read_text(encoding="utf-8")
    
    # 解析 frontmatter
    if not content.startswith("---\n"):
        click.echo("经验文件格式错误：缺少 frontmatter", err=True)
        sys.exit(1)
    
    lines = content.split("\n")
    frontmatter_end = -1
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            frontmatter_end = i
            break
    
    if frontmatter_end == -1:
        click.echo("经验文件格式错误：frontmatter 未正确闭合", err=True)
        sys.exit(1)
    
    # 更新 last_used_at
    if last_used_at:
        for i in range(1, frontmatter_end):
            if lines[i].startswith("last_used_at:"):
                lines[i] = f"last_used_at: {last_used_at}"
                break
    else:
        # 使用当前时间
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for i in range(1, frontmatter_end):
            if lines[i].startswith("last_used_at:"):
                lines[i] = f"last_used_at: {now}"
                break
    
    # 更新 last_used_status
    if last_used_status:
        for i in range(1, frontmatter_end):
            if lines[i].startswith("last_used_status:"):
                lines[i] = f"last_used_status: {last_used_status}"
                break
    
    # 写回文件
    exp_file.write_text("\n".join(lines), encoding="utf-8")
    click.echo(f"✅ 已更新：{exp_file}")


# Shortcut for site-scoped categories: webcli exp api <site> [name]
def _make_site_shortcut(cat: str) -> None:
    # Define help text for each category
    help_texts = {
        "api": "快捷方式：查看接口类经验（省略 show 子命令）。",
        "login": "快捷方式：查看登录类经验（省略 show 子命令）。",
        "action": "快捷方式：查看操作类经验（省略 show 子命令）。",
    }
    
    @exp.command(name=cat, short_help=help_texts.get(cat, "快捷方式：查看指定经验（省略 show 子命令）。"))
    @click.argument("site")
    @click.argument("name", required=False, default="")
    @click.pass_context
    def _shortcut(ctx: click.Context, site: str, name: str) -> None:
        if not name:
            ctx.invoke(exp_list, site=site)
        else:
            ctx.invoke(exp_show, category=cat, site=site, name=name)
    _shortcut.__name__ = f"exp_{cat.replace('-', '_')}"

# Shortcut for global categories: webcli exp anti-crawl [name]  (no site arg)
def _make_global_shortcut(cat: str) -> None:
    @exp.command(name=cat)
    @click.argument("name", required=False, default="")
    @click.pass_context
    def _shortcut(ctx: click.Context, name: str) -> None:
        """快捷方式：查看全局分类经验（不绑定站点，省略 show 子命令）。"""
        if not name:
            ctx.invoke(exp_list, site="")
        else:
            ctx.invoke(exp_show, category=cat, site="-", name=name)
    _shortcut.__name__ = f"exp_{cat.replace('-', '_')}"

for _cat in SITE_SCOPED_CATEGORIES:
    _make_site_shortcut(_cat)

for _cat in GLOBAL_CATEGORIES:
    _make_global_shortcut(_cat)



@cli.command(name="show-help")
def show_help():
    """Show all available commands with usage summary."""
    help_text = """
webcli - Browser automation via Chrome DevTools Protocol

── Tab Management ──────────────────────────────────────────────────────────
  targets [--type page|worker]                 List all browser tabs
  new <url>                                    Create a new background tab
  open-monitored <url>                         Create tab + enable network capture + navigate (atomic)
  close <targetId>                             Close a tab
  navigate <targetId> <url>                    Navigate to a URL
  back <targetId>                              Go back in history
  forward <targetId>                           Go forward in history
  reload <targetId>                            Reload a tab
  info <targetId>                              Get page info (title, URL)

── JavaScript ──────────────────────────────────────────────────────────────
  eval <targetId> <expression>                 Execute JavaScript
  eval <targetId> -f <script.js>               Execute JS from file

── Mouse & Keyboard ────────────────────────────────────────────────────────
  click <targetId> <selector>                  Click element (JS click)
  click-at <targetId> <selector>               Click with real mouse events
  hover <targetId> <selector>                  Hover over element
  press <targetId> <key>                       Press key (Enter, Tab, Control+a)
  focus <targetId> <selector>                  Focus element

── Form Interaction ────────────────────────────────────────────────────────
  fill <targetId> <selector> <value>           Clear and fill input
  type <targetId> <selector> <text>            Type text character by character
  select <targetId> <selector> <value>         Select dropdown option
  check <targetId> <selector>                  Check checkbox
  uncheck <targetId> <selector>                Uncheck checkbox
  set-files <targetId> <selector> <files...>   Set files for file input

── Page Interaction ────────────────────────────────────────────────────────
  scroll <targetId> [top|bottom|up|down|<px>]  Scroll the page
  screenshot <targetId> [file]                 Take a screenshot

── Page Inspection ─────────────────────────────────────────────────────────
  snapshot <targetId>                          Accessibility tree with refs
  get <targetId> <prop> [selector]             Get property (title/url/text/html/value/attr/count/box/styles)
  console <targetId>                           Get intercepted console messages

── Wait & State ────────────────────────────────────────────────────────────
  wait <targetId> [sel|ms] [--text] [--fn]     Wait for element/time/text/condition
  is <targetId> visible|enabled|checked <sel>  Check element state

── Semantic Find ───────────────────────────────────────────────────────────
  find <targetId> role|text|label|placeholder|testid|alt <value> [action]
       --name <name>  --exact  --nth <n>  --fill-value <v>

── Cookies ─────────────────────────────────────────────────────────────────
  cookies <targetId> [--domain <d>] [--url <u>]   Get cookies
  cookies-set <targetId> <name> <value>            Set a cookie
  cookies-clear <targetId>                         Clear all cookies

── Storage ─────────────────────────────────────────────────────────────────
  storage <targetId> [key] [--type local|session]  Get storage value(s)
  storage-set <targetId> <key> <value>             Set storage value
  storage-clear <targetId> [--type local|session]  Clear storage

── Dialog ──────────────────────────────────────────────────────────────────
  dialog-status <targetId>                     Check if dialog is open
  dialog-accept <targetId> [prompt_text]       Accept dialog
  dialog-dismiss <targetId>                    Dismiss dialog

── Network Capture ─────────────────────────────────────────────────────────
  network-start <targetId>                     Start capturing requests
  network-requests <targetId> [filters...]     List captured requests
  network-request <targetId> <requestId>       Get request detail + response body
  network-clear <targetId>                     Clear captured requests
  network-stop <targetId>                      Stop capturing

── Script Capture ──────────────────────────────────────────────────────────
  scripts-enable <targetId>                    Enable Debugger to capture all scripts
  scripts-list [targetId]                      List captured scripts
  scripts-source <targetId> <scriptId> [-o]    Get script source code

── Utility ─────────────────────────────────────────────────────────────────
  health                                       Proxy health check
  show-help                                    Show this help
"""
    print(help_text)


def main():
    # exp subcommands are pure local file ops — skip Proxy startup entirely.
    is_exp_command = len(sys.argv) > 1 and sys.argv[1] == "exp"
    if not is_exp_command:
        ensure_proxy()
    try:
        cli(standalone_mode=False)
    except click.exceptions.NoArgsIsHelpError as exc:
        # Subcommand invoked with no args — print its help cleanly and exit.
        if exc.ctx:
            click.echo(exc.ctx.get_help())
        sys.exit(0)
    except click.UsageError as exc:
        # Unhandled UsageErrors (e.g. bad options) — show error and exit.
        if exc.ctx:
            click.echo(exc.ctx.get_help(), err=True)
        click.echo(f"\nError: {exc.format_message()}", err=True)
        sys.exit(2)
    except click.exceptions.Exit as exc:
        sys.exit(exc.code)
    except click.Abort:
        click.echo("Aborted!", err=True)
        sys.exit(1)
    except RuntimeError as exc:
        # Show friendly error message without traceback
        click.echo(f"\nError: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
