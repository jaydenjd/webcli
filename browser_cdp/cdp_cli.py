#!/usr/bin/env python3
"""
webcli - Browser automation via Chrome DevTools Protocol

Provides a CLI wrapper for the CDP Proxy, automatically managing the Proxy lifecycle.
All commands correspond to real endpoints in cdp_proxy.py.
"""

import json
import os
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
                # Check if this is a Chrome not running error
                if "Chrome" in error_msg or "remote debugging" in error_msg.lower():
                    raise RuntimeError(
                        f"Chrome 未运行。请手动打开浏览器\n\n"
                    ) from exc
                # For 500 errors without retries, provide a friendly error message
                if retries == 0:
                    raise RuntimeError(
                        f"Chrome 未运行。请手动打开浏览器\n\n"
                    ) from exc
                last_error = RuntimeError(
                    f"{'Proxy internal error' if exc.code == 500 else 'Proxy/Chrome not ready'}: {error_msg}"
                )
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
def new(url: str, id_only: bool):
    """新建标签页并等待加载完成。

    \b
    示例：
      webcli new https://example.com
      TARGET=$(webcli new https://example.com --id-only)
    """
    encoded_url = urllib.parse.quote(url, safe=':/?#[]@!$&\'()*+,;=')
    result = http_get(f"/new?url={encoded_url}")
    target_id = result.get("targetId", "")
    if id_only:
        print(target_id)
    else:
        print(json.dumps(result, indent=2))
        if target_id:
            print(f"\n# Next: webcli snapshot {target_id}  |  webcli eval {target_id} \"...\"  |  webcli screenshot {target_id} shot.png")


@cli.command(name="open-monitored")
@click.argument("url")
@click.option("--id-only", is_flag=True, default=False, help="Print only the targetId (useful for shell assignment).")
def open_monitored(url: str, id_only: bool):
    """新建标签页并从第一个请求起开启网络监控。

    原子操作：创建空白标签页 → 启动网络捕获 → 导航，确保不遗漏任何初始 XHR/fetch 请求。

    \b
    示例：
      webcli open-monitored https://yiche.com
      TARGET=$(webcli open-monitored https://yiche.com --id-only)
      # 随后使用：webcli network-requests $TARGET --type xhr,fetch
    """
    encoded_url = urllib.parse.quote(url, safe=':/?#[]@!$&\'()*+,;=')
    result = http_get(f"/network/open-monitored?url={encoded_url}", timeout=30000)
    target_id = result.get("targetId", "")
    if id_only:
        print(target_id)
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
def navigate(target_id: str, url: str):
    """在当前标签页导航到指定 URL。"""
    encoded_url = urllib.parse.quote(url, safe=':/?#[]@!$&\'()*+,;=')
    result = http_get(f"/navigate?target={target_id}&url={encoded_url}")
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
def click_element(target_id: str, selector: str):
    """点击元素（JS el.click() 方式）。"""
    result = http_post(f"/click?target={target_id}", selector)
    print(json.dumps(result, indent=2))


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
def find(target_id: str, by: str, value: str, action: str, name_filter: str, exact: bool, nth: int, fill_value: str):
    """按语义定位器查找元素并执行操作（无需知道 CSS 选择器）。

    \b
    示例：
      webcli find <id> role button click --name "提交"
      webcli find <id> text "登录" click
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


@cli.command(name="network-requests")
@click.argument("target_id")
@click.option("--filter", "url_filter", default="", help="Filter by URL substring.")
@click.option("--method", default="", help="Filter by HTTP method (GET, POST, PUT...).")
@click.option("--type", "res_type", default="", help="Filter by resource type (xhr, fetch, document, script, stylesheet, image...).")
@click.option("--status", default="", help="Filter by status code (200, 2xx, 400-499).")
@click.option("--limit", default=0, help="Return only the most recent N requests (0 = all).")
def network_requests(target_id: str, url_filter: str, method: str, res_type: str, status: str, limit: int):
    """列出捕获的网络请求，支持多种过滤条件。

    \b
    示例：
      webcli network-requests <id>
      webcli network-requests <id> --type xhr,fetch
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
    result = http_get(path)
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

# Experience root: unified under ~/.agents/skills/references/
# This path is agent-platform-agnostic — the same experience library is shared
# across Claude, Cursor, Windsurf, and any other agent that installs this skill.
# Override via WEB_CLI_EXPERIENCE_DIR env var if needed.
EXPERIENCE_DIR = Path(
    os.environ.get("WEB_CLI_EXPERIENCE_DIR")
    or Path.home() / ".agents" / "skills" / "references"
)

# Site-scoped categories: experience/sites/{domain}/{category}/{name}.md
# Cross-site categories: experience/{category}/{name}.md
VALID_CATEGORIES = ("api", "login", "action", "anti-crawl", "workflow")
SITE_SCOPED_CATEGORIES = ("api", "login", "action")
GLOBAL_CATEGORIES = ("anti-crawl", "workflow")


def _exp_path(category: str, site: str, name: str) -> Path:
    """Resolve the markdown file path for a given experience entry.

    Site-scoped (api/login/action): experience/sites/{domain}/{category}/{name}.md
    Global (anti-crawl/workflow):   experience/{category}/{name}.md
    """
    if category in SITE_SCOPED_CATEGORIES:
        return EXPERIENCE_DIR / "sites" / site / category / f"{name}.md"
    return EXPERIENCE_DIR / category / f"{name}.md"


def _exp_frontmatter(category: str, site: str, name: str) -> str:
    """Generate default frontmatter for a new experience file."""
    from datetime import date
    today = date.today().isoformat()
    if category in SITE_SCOPED_CATEGORIES:
        base = f"site: {site}\ncategory: {category}\nstatus: verified\ncreated_at: {today}\nupdated_at: {today}\n"
    else:
        base = f"category: {category}\nstatus: verified\ncreated_at: {today}\nupdated_at: {today}\n"
    return f"---\n{base}---\n\n"


@cli.group(cls=AliasUnderscoreGroup)
def exp():
    """经验库管理（纯本地文件操作，不依赖 Proxy）。

    \b
    分类说明（站点级）：
      api        接口数据获取经验（URL、参数、响应字段、加密破解）
      login      自动化登录经验（登录流程、Cookie 获取、验证码处理）
      action     自动化操作经验（页面交互流程、表单提交、上传等）

    \b
    分类说明（全局级，不绑定站点）：
      anti-crawl 反爬对抗经验（跨站点通用，按反爬类型组织）
      workflow   多步骤任务流程经验（可跨站点，按任务目标命名）

    \b
    示例：
      webcli exp list                          # 列出所有经验
      webcli exp list yiche.com                # 列出某站点经验
      webcli exp api yiche.com rank            # 查看易车销量榜接口经验
      webcli exp login taobao.com              # 查看淘宝登录经验
      webcli exp action xiaohongshu.com post   # 查看小红书发帖操作经验
      webcli exp anti-crawl cloudflare         # 查看 Cloudflare 对抗经验
      webcli exp workflow query-sls-log        # 查看查询 SLS 日志的流程经验
      webcli exp save api yiche.com rank       # 从 stdin 保存/更新站点级经验
      webcli exp save workflow - deploy-ude    # 从 stdin 保存/更新流程经验
      webcli exp edit api yiche.com rank       # 用编辑器打开经验文件
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



# Shortcut for site-scoped categories: webcli exp api <site> [name]
def _make_site_shortcut(cat: str) -> None:
    @exp.command(name=cat)
    @click.argument("site")
    @click.argument("name", required=False, default="")
    @click.pass_context
    def _shortcut(ctx: click.Context, site: str, name: str) -> None:
        """快捷方式：查看指定站点分类的经验（省略 show 子命令）。"""
        if not name:
            ctx.invoke(exp_list, site=site)
        else:
            ctx.invoke(exp_show, category=cat, site=site, name=name)
    _shortcut.__name__ = f"exp_{cat.replace('-', '_')}"

# Shortcut for global categories: webcli exp workflow [name]  (no site arg)
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
