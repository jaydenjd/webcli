#!/usr/bin/env python3
"""
CDP Proxy - Chrome DevTools Protocol HTTP Proxy

This module provides an HTTP API to control Chrome browser via CDP.
It connects to Chrome's remote debugging port and exposes a REST API.
"""

import asyncio
import json
import os
import socket
import sys
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiohttp import web as aiohttp_web
import websockets
from websockets.asyncio.client import ClientConnection
from websockets.connection import State

# Configuration
PORT = int(os.environ.get("CDP_PROXY_PORT", "3456"))
CHROME_HOST = "127.0.0.1"
# When set, Proxy will try this Chrome port first before auto-discovery.
CHROME_PORT_OVERRIDE: Optional[int] = int(os.environ["CDP_CHROME_PORT"]) if os.environ.get("CDP_CHROME_PORT") else None

# Global state
ws: Optional[ClientConnection] = None
cmd_id = 0
pending: Dict[int, asyncio.Future] = {}
sessions: Dict[str, str] = {}  # targetId -> sessionId
chrome_port: Optional[int] = None
chrome_ws_path: Optional[str] = None
connecting: Optional[asyncio.Task] = None
ws_ready: asyncio.Event = asyncio.Event()  # set when ws is OPEN
port_guarded_sessions: set = set()

# Network capture state: targetId -> bounded deque of request records
MAX_CAPTURES_PER_TARGET = 2000
network_captures: Dict[str, Deque[dict]] = {}
network_request_map: Dict[str, dict] = {}  # requestId -> record (cross-target)

# Dialog state: targetId -> dialog info
pending_dialogs: Dict[str, dict] = {}

# Script capture state: targetId -> list of script info
# Each script: {scriptId, url, source (lazy loaded)}
script_captures: Dict[str, list] = {}
script_id_map: Dict[str, dict] = {}  # scriptId -> {targetId, url, source}


async def check_port(port: int, host: str = CHROME_HOST, timeout: float = 2.0) -> bool:
    """Check if a port is open via TCP connection."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False


def get_devtools_active_port_paths() -> list:
    """Get possible paths for DevToolsActivePort file based on platform."""
    paths = []
    platform = sys.platform
    
    if platform == "darwin":
        home = Path.home()
        paths.extend([
            home / "Library/Application Support/Google/Chrome/DevToolsActivePort",
            home / "Library/Application Support/Google/Chrome Canary/DevToolsActivePort",
            home / "Library/Application Support/Chromium/DevToolsActivePort",
        ])
    elif platform == "linux":
        home = Path.home()
        paths.extend([
            home / ".config/google-chrome/DevToolsActivePort",
            home / ".config/chromium/DevToolsActivePort",
        ])
    elif platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        paths.extend([
            Path(local_app_data) / "Google/Chrome/User Data/DevToolsActivePort",
            Path(local_app_data) / "Chromium/User Data/DevToolsActivePort",
        ])
    
    return paths


async def _fetch_ws_url_via_http(port: int) -> Optional[str]:
    """Try to get the real WebSocket debugger URL from Chrome's HTTP endpoint."""
    import urllib.request as _urllib_request
    for path in ["/json/version", "/json"]:
        try:
            url = f"http://{CHROME_HOST}:{port}{path}"
            req = _urllib_request.Request(url, headers={"Host": f"{CHROME_HOST}:{port}"})
            with _urllib_request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
                # /json/version returns a dict, /json returns a list
                if isinstance(data, dict):
                    ws_url = data.get("webSocketDebuggerUrl")
                    if ws_url:
                        return ws_url
                elif isinstance(data, list) and data:
                    ws_url = data[0].get("webSocketDebuggerUrl")
                    if ws_url:
                        return ws_url
        except Exception:
            continue
    return None


async def discover_chrome_port() -> Optional[Dict[str, Any]]:
    """Discover Chrome's remote debugging port and WebSocket URL.

    Strategy (in order):
    1. CDP_CHROME_PORT env override (highest priority)
    2. Candidate ports from DevToolsActivePort files
    3. Common fallback ports (9222, 9223, 9229, 9333)

    For each candidate port, first try to get the real WebSocket URL via
    Chrome's HTTP endpoint (/json/version). Only fall back to the wsPath
    from the DevToolsActivePort file when the HTTP endpoint is unavailable.
    """
    candidate_ports: list[tuple[int, Optional[str]]] = []

    # Highest priority: explicit port override via environment variable.
    if CHROME_PORT_OVERRIDE:
        candidate_ports.append((CHROME_PORT_OVERRIDE, None))

    # Collect candidates from DevToolsActivePort files
    for path in get_devtools_active_port_paths():
        try:
            content = path.read_text().strip()
            lines = content.split("\n")
            port = int(lines[0])
            if 0 < port < 65536:
                ws_path = lines[1] if len(lines) > 1 else None
                candidate_ports.append((port, ws_path))
        except (FileNotFoundError, ValueError, IndexError):
            continue

    # Add common ports as fallback (avoid duplicates).
    # 9223 is reserved for manually launched Chrome instances to avoid
    # conflicting with the user's existing Chrome on 9222.
    existing_ports = {p for p, _ in candidate_ports}
    for port in [9222, 9223, 9229, 9333]:
        if port not in existing_ports:
            candidate_ports.append((port, None))

    for port, file_ws_path in candidate_ports:
        if not await check_port(port):
            continue

        # Prefer the real WebSocket URL from Chrome's HTTP endpoint
        real_ws_url = await _fetch_ws_url_via_http(port)
        if real_ws_url:
            # Extract just the path from the full ws:// URL
            ws_path = real_ws_url.replace(f"ws://{CHROME_HOST}:{port}", "")
            print(f"[CDP Proxy] Found Chrome via HTTP endpoint: port={port}, wsPath={ws_path}")
            return {"port": port, "ws_path": ws_path}

        # Fall back to the path from DevToolsActivePort file
        if file_ws_path:
            print(f"[CDP Proxy] Found port from DevToolsActivePort: {port} (wsPath from file, HTTP unavailable)")
            return {"port": port, "ws_path": file_ws_path}

        print(f"[CDP Proxy] Found Chrome debugging port: {port} (no wsPath)")
        return {"port": port, "ws_path": None}

    return None


def get_websocket_url(port: int, ws_path: Optional[str]) -> str:
    """Get WebSocket URL for Chrome CDP."""
    if ws_path:
        return f"ws://{CHROME_HOST}:{port}{ws_path}"
    return f"ws://{CHROME_HOST}:{port}/devtools/browser"


async def connect() -> None:
    """Connect to Chrome via WebSocket and wait until the connection is ready."""
    global ws, connecting, chrome_port, chrome_ws_path

    # Already connected
    if ws and ws.state == State.OPEN:
        return

    # Another coroutine is already connecting — wait for ws_ready instead of
    # awaiting the task (which runs the message loop forever and never returns).
    if connecting and not connecting.done():
        try:
            await asyncio.wait_for(ws_ready.wait(), timeout=15)
        except asyncio.TimeoutError:
            raise RuntimeError("Timed out waiting for WebSocket connection to Chrome")
        return

    if chrome_port is None:
        discovered = await discover_chrome_port()
        if not discovered:
            raise RuntimeError(
                "Chrome not running with remote debugging port. "
                "Start Chrome with --remote-debugging-port=9222 or "
                "enable remote debugging in chrome://inspect/#remote-debugging"
            )
        chrome_port = discovered["port"]
        chrome_ws_path = discovered["ws_path"]

    ws_url = get_websocket_url(chrome_port, chrome_ws_path)

    async def _connect():
        global ws, chrome_port, chrome_ws_path
        # Build a list of URLs to try: the discovered URL first, then fallbacks.
        urls_to_try = [ws_url]
        if chrome_ws_path and chrome_ws_path != "/devtools/browser":
            urls_to_try.append(f"ws://{CHROME_HOST}:{chrome_port}/devtools/browser")

        connected = False
        for candidate_url in urls_to_try:
            try:
                async with websockets.connect(candidate_url, open_timeout=10, max_size=100 * 1024 * 1024) as websocket:
                    ws = websocket
                    ws_ready.set()  # signal that the connection is ready
                    print(f"[CDP Proxy] Connected to Chrome (port {chrome_port})")
                    connected = True

                    async for message in websocket:
                        data = json.loads(message)

                        if data.get("method") == "Target.attachedToTarget":
                            session_id = data["params"]["sessionId"]
                            target_info = data["params"]["targetInfo"]
                            sessions[target_info["targetId"]] = session_id

                        # Network capture events
                        method = data.get("method", "")
                        params = data.get("params", {})
                        msg_session = data.get("sessionId")

                        if method == "Network.requestWillBeSent" and msg_session:
                            target_id_for_session = next(
                                (tid for tid, sid in sessions.items() if sid == msg_session), None
                            )
                            if target_id_for_session and target_id_for_session in network_captures:
                                req = params.get("request", {})
                                record = {
                                    "requestId": params.get("requestId"),
                                    "url": req.get("url"),
                                    "method": req.get("method"),
                                    "headers": req.get("headers", {}),
                                    "postData": req.get("postData"),
                                    "resourceType": params.get("type"),
                                    "timestamp": params.get("timestamp"),
                                    "status": None,
                                    "responseHeaders": {},
                                    "mimeType": None,
                                    "responseBody": None,
                                    "_sessionId": msg_session,
                                }
                                network_captures[target_id_for_session].append(record)
                                network_request_map[params.get("requestId")] = record

                        elif method == "Network.responseReceived" and msg_session:
                            req_id = params.get("requestId")
                            if req_id in network_request_map:
                                resp = params.get("response", {})
                                network_request_map[req_id]["status"] = resp.get("status")
                                network_request_map[req_id]["responseHeaders"] = resp.get("headers", {})
                                network_request_map[req_id]["mimeType"] = resp.get("mimeType")

                        elif method == "Network.loadingFinished" and msg_session:
                            req_id = params.get("requestId")
                            if req_id in network_request_map:
                                network_request_map[req_id]["_loaded"] = True
                                network_request_map[req_id]["_sessionId"] = msg_session

                        elif method == "Network.loadingFailed" and msg_session:
                            req_id = params.get("requestId")
                            if req_id in network_request_map:
                                network_request_map[req_id]["_loaded"] = False
                                network_request_map[req_id]["_failed"] = True
                                network_request_map[req_id]["_errorText"] = params.get("errorText", "")

                        # Dialog events
                        elif method == "Page.javascriptDialogOpening" and msg_session:
                            target_id_for_session = next(
                                (tid for tid, sid in sessions.items() if sid == msg_session), None
                            )
                            if target_id_for_session:
                                pending_dialogs[target_id_for_session] = {
                                    "type": params.get("type"),
                                    "message": params.get("message"),
                                    "defaultPrompt": params.get("defaultPrompt", ""),
                                    "_sessionId": msg_session,
                                }

                        elif method == "Page.javascriptDialogClosed" and msg_session:
                            target_id_for_session = next(
                                (tid for tid, sid in sessions.items() if sid == msg_session), None
                            )
                            if target_id_for_session:
                                pending_dialogs.pop(target_id_for_session, None)

                        # Script capture: Debugger.scriptParsed events
                        elif method == "Debugger.scriptParsed" and msg_session:
                            target_id_for_session = next(
                                (tid for tid, sid in sessions.items() if sid == msg_session), None
                            )
                            if target_id_for_session and target_id_for_session in script_captures:
                                script_info = params
                                script_captures[target_id_for_session].append(script_info)
                                script_id_map[params["scriptId"]] = {
                                    "targetId": target_id_for_session,
                                    "url": params.get("url", ""),
                                }

                        # Intercept requests to Chrome debugging port (anti-detection)
                        if data.get("method") == "Fetch.requestPaused":
                            request_id = data["params"]["requestId"]
                            session_id = data["params"]["sessionId"]
                            await send_cdp("Fetch.failRequest",
                                          {"requestId": request_id, "errorReason": "ConnectionRefused"},
                                          session_id)

                        if data.get("id") and data["id"] in pending:
                            future = pending.pop(data["id"])
                            if not future.done():
                                future.set_result(data)

                # Connection closed normally — no need to try fallback URLs
                break
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception:
                # This URL failed to connect; try the next candidate
                ws_ready.clear()
                continue
        if not connected:
            ws_ready.clear()
        # Always clean up state when the connection loop exits
        ws = None
        chrome_port = None
        chrome_ws_path = None
        ws_ready.clear()
        sessions.clear()
    # Launch the message-loop task in the background
    connecting = asyncio.create_task(_connect())

    # Wait until _connect() signals that the WebSocket is open
    try:
        await asyncio.wait_for(ws_ready.wait(), timeout=15)
    except asyncio.TimeoutError:
        connecting.cancel()
        raise RuntimeError("Timed out waiting for WebSocket connection to Chrome")


async def send_cdp(method: str, params: Optional[Dict] = None, 
                   session_id: Optional[str] = None) -> Dict:
    """Send a CDP command and wait for response."""
    global cmd_id
    
    if not ws or ws.state != State.OPEN:
        raise RuntimeError("WebSocket not connected")
    
    cmd_id += 1
    msg = {"id": cmd_id, "method": method}
    if params:
        msg["params"] = params
    if session_id:
        msg["sessionId"] = session_id
    
    future = asyncio.get_running_loop().create_future()
    pending[cmd_id] = future
    
    try:
        await ws.send(json.dumps(msg))
        return await asyncio.wait_for(future, timeout=30)
    except asyncio.TimeoutError:
        pending.pop(cmd_id, None)
        raise TimeoutError(f"CDP command timeout: {method}")


async def _enable_page_events(session_id: str) -> None:
    """Enable Page domain events for a session in the background.

    Uses a short timeout so a blocked tab (e.g. one with an open dialog) does
    not hold the session hostage and prevent other CDP commands from completing.
    """
    try:
        await asyncio.wait_for(send_cdp("Page.enable", {}, session_id), timeout=3)
    except Exception:
        pass

async def ensure_session(target_id: str) -> str:
    """Ensure a session exists for the given target."""
    if target_id in sessions:
        return sessions[target_id]
    
    resp = await send_cdp("Target.attachToTarget", {"targetId": target_id, "flatten": True})
    if "result" in resp and "sessionId" in resp["result"]:
        session_id = resp["result"]["sessionId"]
        sessions[target_id] = session_id
        await enable_port_guard(session_id)
        # Fire Page.enable in the background so it doesn't block session creation.
        # This ensures dialog/navigation events are received without delaying callers.
        asyncio.ensure_future(_enable_page_events(session_id))
        return session_id
    
    raise RuntimeError(f"Attach failed: {resp.get('error', 'Unknown error')}")


async def enable_port_guard(session_id: str) -> None:
    """Enable interception of requests to Chrome debugging port."""
    global chrome_port
    
    if not chrome_port or session_id in port_guarded_sessions:
        return
    
    try:
        await send_cdp("Fetch.enable", {
            "patterns": [
                {"urlPattern": f"http://127.0.0.1:{chrome_port}/*", "requestStage": "Request"},
                {"urlPattern": f"http://localhost:{chrome_port}/*", "requestStage": "Request"},
            ]
        }, session_id)
        port_guarded_sessions.add(session_id)
    except Exception:
        pass  # Non-fatal


async def wait_for_load(session_id: str, timeout: int = 15000) -> str:
    """Wait for page to finish loading."""
    await send_cdp("Page.enable", {}, session_id)
    
    async def check_ready():
        while True:
            try:
                resp = await send_cdp("Runtime.evaluate", {
                    "expression": "document.readyState",
                    "returnByValue": True,
                }, session_id)
                if resp.get("result", {}).get("result", {}).get("value") == "complete":
                    return "complete"
            except Exception:
                pass
            await asyncio.sleep(0.5)
    
    try:
        return await asyncio.wait_for(check_ready(), timeout=timeout/1000)
    except asyncio.TimeoutError:
        return "timeout"


# HTTP Server handlers
async def handle_health(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Health check endpoint."""
    connected = ws is not None and ws.state == State.OPEN
    return aiohttp_web.json_response({
        "status": "ok",
        "connected": connected,
        "sessions": len(sessions),
        "chromePort": chrome_port
    })

async def handle_browser(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Check Chrome status and provide launch instructions if not running."""
    discovered = await discover_chrome_port()
    if discovered:
        ws_url = get_websocket_url(discovered["port"], discovered["ws_path"])
        return aiohttp_web.json_response({
            "status": "running",
            "port": discovered["port"],
            "wsPath": discovered["ws_path"],
            "wsUrl": ws_url,
            "message": "Chrome is running with remote debugging enabled."
        })
    else:
        return aiohttp_web.json_response({
            "status": "not_running",
            "message": "Chrome is not running with remote debugging port.",
            "instructions": [
                "Option 1: open Chrome",
                "Option 2: Enable remote debugging in an existing Chrome:",
                "  1. Open chrome://inspect/#remote-debugging",
                "  2. Click 'Show all' and enable 'Discover network targets'",
                "  3. Note the port number shown"
            ]
        }, status=404)


async def handle_targets(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """List all browser targets. Optional ?type= filter (e.g. page, worker)."""
    await connect()
    resp = await send_cdp("Target.getTargets")
    targets = resp["result"]["targetInfos"]
    target_type = request.query.get("type")
    if target_type:
        targets = [t for t in targets if t["type"] == target_type]
    else:
        targets = [t for t in targets if t["type"] == "page"]
    return aiohttp_web.json_response(targets)


async def handle_new(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Create a new background tab."""
    await connect()
    url = request.query.get("url", "about:blank")
    resp = await send_cdp("Target.createTarget", {"url": url, "background": True})
    target_id = resp["result"]["targetId"]
    
    if url != "about:blank":
        try:
            session_id = await ensure_session(target_id)
            await wait_for_load(session_id)
        except Exception:
            pass  # Non-fatal
    
    return aiohttp_web.json_response({"targetId": target_id})


async def handle_close(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Close a tab."""
    await connect()
    target_id = request.query["target"]
    await send_cdp("Target.closeTarget", {"targetId": target_id})
    sessions.pop(target_id, None)
    # Clean up network capture memory for this tab.
    evicted = network_captures.pop(target_id, None)
    if evicted:
        ids_to_remove = {r.get("requestId") for r in evicted}
        for rid in ids_to_remove:
            network_request_map.pop(rid, None)
    return aiohttp_web.json_response({"closed": True, "targetId": target_id})


async def handle_navigate(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Navigate to a URL."""
    await connect()
    target_id = request.query["target"]
    url = request.query["url"]
    session_id = await ensure_session(target_id)
    await send_cdp("Page.navigate", {"url": url}, session_id)
    await wait_for_load(session_id)
    url_resp = await send_cdp("Runtime.evaluate", {
        "expression": "location.href", "returnByValue": True,
    }, session_id)
    current_url = url_resp.get("result", {}).get("result", {}).get("value", url)
    return aiohttp_web.json_response({"url": current_url, "ok": True})


async def handle_back(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Go back in history."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    await send_cdp("Runtime.evaluate", {"expression": "history.back()"}, session_id)
    await wait_for_load(session_id)
    return aiohttp_web.json_response({"ok": True})


async def handle_eval(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Execute JavaScript."""
    try:
        await connect()
        target_id = request.query["target"]
        session_id = await ensure_session(target_id)

        body = await request.text()
        expr = body or request.query.get("expr", "document.title")

        resp = await send_cdp("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        }, session_id)

        if "result" in resp and "result" in resp["result"]:
            cdp_result = resp["result"]["result"]
            result_type = cdp_result.get("type", "")
            if "value" in cdp_result:
                return aiohttp_web.json_response({"value": cdp_result["value"]})
            elif result_type == "undefined":
                return aiohttp_web.json_response({"value": None})
            else:
                # 对象/数组等复杂类型，返回 type 和 description 供调用方参考
                return aiohttp_web.json_response({
                    "value": None,
                    "type": result_type,
                    "description": cdp_result.get("description", ""),
                })
        elif "result" in resp and "exceptionDetails" in resp["result"]:
            return aiohttp_web.json_response(
                {"error": resp["result"]["exceptionDetails"]["text"]}, status=400
            )
        return aiohttp_web.json_response(resp.get("result", {}))
    except TimeoutError as exc:
        return aiohttp_web.json_response({"error": f"CDP command timed out: {exc}"}, status=504)
    except RuntimeError as exc:
        return aiohttp_web.json_response({"error": str(exc)}, status=503)
    except Exception as exc:
        return aiohttp_web.json_response({"error": f"Internal error: {exc}"}, status=500)


async def handle_click(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Click an element using JS."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    
    selector = await request.text()
    if not selector:
        return aiohttp_web.json_response(
            {"error": "POST body requires CSS selector"}, status=400
        )
    
    js = f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return {{ error: 'Element not found: ' + {json.dumps(selector)} }};
        el.scrollIntoView({{ block: 'center' }});
        el.click();
        return {{ clicked: true, tag: el.tagName, text: (el.textContent || '').slice(0, 100) }};
    }})()"""
    
    resp = await send_cdp("Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
        "awaitPromise": True,
    }, session_id)
    
    if "result" in resp and "result" in resp["result"]:
        val = resp["result"]["result"]["value"]
        if "error" in val:
            return aiohttp_web.json_response(val, status=400)
        return aiohttp_web.json_response(val)
    return aiohttp_web.json_response(resp.get("result", {}))


async def handle_click_at(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Click an element using real mouse events."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    
    selector = await request.text()
    if not selector:
        return aiohttp_web.json_response(
            {"error": "POST body requires CSS selector"}, status=400
        )
    
    # Get element coordinates
    js = f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return {{ error: 'Element not found: ' + {json.dumps(selector)} }};
        el.scrollIntoView({{ block: 'center' }});
        const rect = el.getBoundingClientRect();
        return {{ x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, 
                  tag: el.tagName, text: (el.textContent || '').slice(0, 100) }};
    }})()"""
    
    coord_resp = await send_cdp("Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
        "awaitPromise": True,
    }, session_id)
    
    coord = coord_resp.get("result", {}).get("result", {}).get("value")
    if not coord or "error" in coord:
        return aiohttp_web.json_response(coord or coord_resp.get("result", {}), status=400)
    
    # Dispatch mouse events
    await send_cdp("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": coord["x"], "y": coord["y"],
        "button": "left", "clickCount": 1
    }, session_id)
    await send_cdp("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": coord["x"], "y": coord["y"],
        "button": "left", "clickCount": 1
    }, session_id)
    
    return aiohttp_web.json_response({
        "clicked": True, "x": coord["x"], "y": coord["y"],
        "tag": coord["tag"], "text": coord["text"]
    })


async def handle_set_files(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Set files for a file input."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    
    body = await request.json()
    if not body.get("selector") or not body.get("files"):
        return aiohttp_web.json_response(
            {"error": "Requires selector and files fields"}, status=400
        )
    
    # Get DOM node
    await send_cdp("DOM.enable", {}, session_id)
    doc = await send_cdp("DOM.getDocument", {}, session_id)
    node = await send_cdp("DOM.querySelector", {
        "nodeId": doc["result"]["root"]["nodeId"],
        "selector": body["selector"]
    }, session_id)
    
    if not node.get("result", {}).get("nodeId"):
        return aiohttp_web.json_response(
            {"error": f"Element not found: {body['selector']}"}, status=400
        )
    
    # Set files
    await send_cdp("DOM.setFileInputFiles", {
        "nodeId": node["result"]["nodeId"],
        "files": body["files"]
    }, session_id)
    
    return aiohttp_web.json_response({"success": True, "files": len(body["files"])})


async def handle_scroll(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Scroll the page."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    
    y = int(request.query.get("y", "3000"))
    direction = request.query.get("direction", "down")
    
    if direction == "top":
        js = "window.scrollTo(0, 0); 'scrolled to top'"
    elif direction == "bottom":
        js = "window.scrollTo(0, document.body.scrollHeight); 'scrolled to bottom'"
    elif direction == "up":
        js = f"window.scrollBy(0, -{abs(y)}); 'scrolled up {abs(y)}px'"
    else:
        js = f"window.scrollBy(0, {abs(y)}); 'scrolled down {abs(y)}px'"
    
    resp = await send_cdp("Runtime.evaluate", {
        "expression": js,
        "returnByValue": True,
    }, session_id)
    
    # Wait for lazy loading
    await asyncio.sleep(0.8)
    
    return aiohttp_web.json_response({
        "value": resp.get("result", {}).get("result", {}).get("value")
    })


async def handle_screenshot(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Take a screenshot."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    
    fmt = request.query.get("format", "png")
    screenshot_params: Dict = {"format": fmt}
    if fmt == "jpeg":
        screenshot_params["quality"] = 80
    resp = await send_cdp("Page.captureScreenshot", screenshot_params, session_id)
    
    file_path = request.query.get("file")
    if file_path:
        import base64
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(resp["result"]["data"]))
        return aiohttp_web.json_response({"saved": file_path})
    else:
        import base64
        return aiohttp_web.Response(
            body=base64.b64decode(resp["result"]["data"]),
            content_type=f"image/{fmt}"
        )


async def handle_info(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Get page information."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    
    resp = await send_cdp("Runtime.evaluate", {
        "expression": "JSON.stringify({title: document.title, url: location.href, ready: document.readyState})",
        "returnByValue": True,
    }, session_id)
    
    return aiohttp_web.json_response(json.loads(resp.get("result", {}).get("result", {}).get("value", "{}")))


async def handle_reload(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Reload a tab and wait for it to finish loading."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    await send_cdp("Page.reload", {}, session_id)
    await wait_for_load(session_id)
    return aiohttp_web.json_response({"ok": True})


async def handle_fill(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Clear and fill an input element."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    body = await request.json()
    selector = body.get("selector")
    value = body.get("value", "")
    if not selector:
        return aiohttp_web.json_response({"error": "Missing selector"}, status=400)

    js = f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return {{ error: 'Element not found: ' + {json.dumps(selector)} }};
        el.focus();
        el.value = '';
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.value = {json.dumps(value)};
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return {{ filled: true, value: el.value }};
    }})()"""

    resp = await send_cdp("Runtime.evaluate", {
        "expression": js, "returnByValue": True, "awaitPromise": True,
    }, session_id)

    val = resp.get("result", {}).get("result", {}).get("value", {})
    if isinstance(val, dict) and "error" in val:
        return aiohttp_web.json_response(val, status=400)
    return aiohttp_web.json_response(val)


async def handle_type(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Type text into an element character by character."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    body = await request.json()
    selector = body.get("selector")
    text = body.get("text", "")
    if not selector:
        return aiohttp_web.json_response({"error": "Missing selector"}, status=400)

    # Focus element first
    js = f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return {{ error: 'Element not found: ' + {json.dumps(selector)} }};
        el.focus();
        return {{ focused: true }};
    }})()"""
    resp = await send_cdp("Runtime.evaluate", {
        "expression": js, "returnByValue": True,
    }, session_id)
    val = resp.get("result", {}).get("result", {}).get("value", {})
    if isinstance(val, dict) and "error" in val:
        return aiohttp_web.json_response(val, status=400)

    # Type each character
    for char in text:
        await send_cdp("Input.dispatchKeyEvent", {
            "type": "keyDown", "text": char,
        }, session_id)
        await send_cdp("Input.dispatchKeyEvent", {
            "type": "keyUp", "text": char,
        }, session_id)

    return aiohttp_web.json_response({"typed": True, "length": len(text)})


async def handle_hover(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Hover over an element."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    selector = await request.text()
    if not selector:
        return aiohttp_web.json_response({"error": "POST body requires CSS selector"}, status=400)

    js = f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return {{ error: 'Element not found: ' + {json.dumps(selector)} }};
        el.scrollIntoView({{ block: 'center' }});
        const rect = el.getBoundingClientRect();
        return {{ x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }};
    }})()"""

    coord_resp = await send_cdp("Runtime.evaluate", {
        "expression": js, "returnByValue": True,
    }, session_id)
    coord = coord_resp.get("result", {}).get("result", {}).get("value")
    if not coord or "error" in coord:
        return aiohttp_web.json_response(coord or {"error": "Element not found"}, status=400)

    await send_cdp("Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": coord["x"], "y": coord["y"],
    }, session_id)

    return aiohttp_web.json_response({"hovered": True, "x": coord["x"], "y": coord["y"]})


async def handle_press(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Press a key or key combination (e.g. Enter, Tab, Control+a)."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    key_combo = await request.text()
    if not key_combo:
        return aiohttp_web.json_response({"error": "POST body requires key name"}, status=400)

    # Parse modifiers: Control+Shift+a -> modifiers=3, key=a
    KEY_MAP = {
        "enter": "Return", "return": "Return", "tab": "Tab",
        "escape": "Escape", "esc": "Escape", "space": "Space",
        "backspace": "Backspace", "delete": "Delete", "del": "Delete",
        "arrowup": "ArrowUp", "arrowdown": "ArrowDown",
        "arrowleft": "ArrowLeft", "arrowright": "ArrowRight",
        "home": "Home", "end": "End", "pageup": "PageUp", "pagedown": "PageDown",
        "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5",
        "f6": "F6", "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10",
        "f11": "F11", "f12": "F12",
    }
    parts = key_combo.split("+")
    modifiers = 0
    key = parts[-1]
    for mod in parts[:-1]:
        mod_lower = mod.lower()
        if mod_lower in ("control", "ctrl"):
            modifiers |= 2
        elif mod_lower in ("shift",):
            modifiers |= 8
        elif mod_lower in ("alt",):
            modifiers |= 1
        elif mod_lower in ("meta", "command", "cmd"):
            modifiers |= 4

    key_name = KEY_MAP.get(key.lower(), key)

    await send_cdp("Input.dispatchKeyEvent", {
        "type": "keyDown", "key": key_name, "modifiers": modifiers,
        "text": key if len(key) == 1 and not modifiers else "",
    }, session_id)
    await send_cdp("Input.dispatchKeyEvent", {
        "type": "keyUp", "key": key_name, "modifiers": modifiers,
    }, session_id)

    return aiohttp_web.json_response({"pressed": key_combo})


async def handle_forward(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Go forward in history."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    await send_cdp("Runtime.evaluate", {"expression": "history.forward()"}, session_id)
    await wait_for_load(session_id)
    return aiohttp_web.json_response({"ok": True})


async def handle_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Get page/element property: text, html, value, title, url, attr, count, box."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    prop = request.query.get("prop", "title")
    selector = request.query.get("selector", "")
    attr = request.query.get("attr", "")

    if prop == "title":
        js = "document.title"
    elif prop == "url":
        js = "location.href"
    elif prop == "text":
        js = f"document.querySelector({json.dumps(selector)})?.innerText ?? null" if selector else "document.body.innerText"
    elif prop == "html":
        js = f"document.querySelector({json.dumps(selector)})?.innerHTML ?? null" if selector else "document.documentElement.outerHTML"
    elif prop == "value":
        js = f"document.querySelector({json.dumps(selector)})?.value ?? null"
    elif prop == "attr":
        js = f"document.querySelector({json.dumps(selector)})?.getAttribute({json.dumps(attr)}) ?? null"
    elif prop == "count":
        js = f"document.querySelectorAll({json.dumps(selector)}).length"
    elif prop == "box":
        js = f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{ x: r.x, y: r.y, width: r.width, height: r.height, top: r.top, right: r.right, bottom: r.bottom, left: r.left }};
        }})()"""
    elif prop == "styles":
        js = f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            const s = window.getComputedStyle(el);
            const result = {{}};
            for (let i = 0; i < s.length; i++) result[s[i]] = s.getPropertyValue(s[i]);
            return result;
        }})()"""
    else:
        return aiohttp_web.json_response({"error": f"Unknown prop: {prop}"}, status=400)

    resp = await send_cdp("Runtime.evaluate", {
        "expression": js, "returnByValue": True,
    }, session_id)
    value = resp.get("result", {}).get("result", {}).get("value")
    return aiohttp_web.json_response({"value": value})


async def handle_wait(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Wait for element, time, text, or JS condition."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    timeout_ms = int(request.query.get("timeout", "15000"))
    selector = request.query.get("selector", "")
    ms = request.query.get("ms", "")
    text = request.query.get("text", "")
    fn = request.query.get("fn", "")
    state = request.query.get("state", "visible")  # visible | hidden

    if ms:
        await asyncio.sleep(float(ms) / 1000)
        return aiohttp_web.json_response({"waited": f"{ms}ms"})

    if text:
        fn = f"document.body.innerText.includes({json.dumps(text)})"
    elif selector and state == "hidden":
        fn = f"!document.querySelector({json.dumps(selector)}) || getComputedStyle(document.querySelector({json.dumps(selector)})).display === 'none'"
    elif selector:
        fn = f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        }})()"""

    if not fn:
        return aiohttp_web.json_response({"error": "Provide selector, ms, text, or fn"}, status=400)

    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    while asyncio.get_event_loop().time() < deadline:
        resp = await send_cdp("Runtime.evaluate", {
            "expression": fn, "returnByValue": True,
        }, session_id)
        value = resp.get("result", {}).get("result", {}).get("value")
        if value:
            return aiohttp_web.json_response({"ok": True})
        await asyncio.sleep(0.3)

    return aiohttp_web.json_response({"error": "Wait timeout", "condition": fn}, status=408)


async def handle_is(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Check element state: visible, enabled, checked."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    check = request.query.get("check", "visible")
    selector = request.query.get("selector", "")
    if not selector:
        return aiohttp_web.json_response({"error": "Missing selector"}, status=400)

    if check == "visible":
        js = f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
        }})()"""
    elif check == "enabled":
        js = f"!document.querySelector({json.dumps(selector)})?.disabled ?? false"
    elif check == "checked":
        js = f"document.querySelector({json.dumps(selector)})?.checked ?? false"
    else:
        return aiohttp_web.json_response({"error": f"Unknown check: {check}"}, status=400)

    resp = await send_cdp("Runtime.evaluate", {
        "expression": js, "returnByValue": True,
    }, session_id)
    value = resp.get("result", {}).get("result", {}).get("value", False)
    return aiohttp_web.json_response({"result": value, "check": check, "selector": selector})


async def handle_snapshot(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Get accessibility tree with element refs for AI navigation."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    max_depth = int(request.query.get("depth", "3"))

    await send_cdp("Accessibility.enable", {}, session_id)
    resp = await send_cdp("Accessibility.getFullAXTree", {}, session_id)
    nodes = resp.get("result", {}).get("nodes", [])

    # Build compact ref-indexed tree for AI consumption
    ref_counter = [0]
    ref_map = {}

    def node_to_text(node: dict, depth: int = 0) -> list:
        role = node.get("role", {}).get("value", "")
        name_obj = node.get("name", {})
        name = name_obj.get("value", "") if isinstance(name_obj, dict) else ""
        ignored = node.get("ignored", False)

        if ignored or role in ("none", "generic", "InlineTextBox", "StaticText"):
            if depth >= max_depth:
                return []
            lines = []
            for child_id in node.get("childIds", []):
                child = next((n for n in nodes if n.get("nodeId") == child_id), None)
                if child:
                    lines.extend(node_to_text(child, depth))
            return lines

        ref_counter[0] += 1
        ref = f"@e{ref_counter[0]}"
        ref_map[ref] = node.get("backendDOMNodeId")

        indent = "  " * depth
        label = f"{indent}[{ref}] {role}"
        if name:
            label += f' "{name}"'

        # Add value for inputs
        value_obj = node.get("value", {})
        if isinstance(value_obj, dict) and value_obj.get("value"):
            label += f' value="{value_obj["value"]}"'

        lines = [label]
        if depth < max_depth:
            for child_id in node.get("childIds", []):
                child = next((n for n in nodes if n.get("nodeId") == child_id), None)
                if child:
                    lines.extend(node_to_text(child, depth + 1))
        return lines

    tree_lines = node_to_text(nodes[0]) if nodes else []
    tree_text = "\n".join(tree_lines)

    return aiohttp_web.json_response({
        "snapshot": tree_text,
        "refs": ref_map,
        "nodeCount": len(nodes),
    })


async def handle_console(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Get console messages collected since last call."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    # Enable Runtime to collect console messages via evaluate
    resp = await send_cdp("Runtime.evaluate", {
        "expression": """(() => {
            if (!window.__cdp_console_log) return [];
            const msgs = window.__cdp_console_log;
            window.__cdp_console_log = [];
            return msgs;
        })()""",
        "returnByValue": True,
    }, session_id)

    messages = resp.get("result", {}).get("result", {}).get("value") or []

    # If not yet initialized, inject console interceptor
    if not messages and request.query.get("init") != "0":
        await send_cdp("Runtime.evaluate", {
            "expression": """(() => {
                if (window.__cdp_console_patched) return;
                window.__cdp_console_log = [];
                window.__cdp_console_patched = true;
                const orig = {};
                ['log','warn','error','info','debug'].forEach(level => {
                    orig[level] = console[level].bind(console);
                    console[level] = (...args) => {
                        window.__cdp_console_log.push({
                            level,
                            text: args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' '),
                            timestamp: Date.now()
                        });
                        orig[level](...args);
                    };
                });
            })()""",
            "returnByValue": True,
        }, session_id)
        messages = []

    return aiohttp_web.json_response({"messages": messages, "count": len(messages)})


async def handle_focus(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Focus an element."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    selector = await request.text()
    if not selector:
        return aiohttp_web.json_response({"error": "POST body requires CSS selector"}, status=400)

    js = f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return {{ error: 'Element not found: ' + {json.dumps(selector)} }};
        el.focus();
        return {{ focused: true, tag: el.tagName }};
    }})()"""

    resp = await send_cdp("Runtime.evaluate", {
        "expression": js, "returnByValue": True,
    }, session_id)
    val = resp.get("result", {}).get("result", {}).get("value", {})
    if isinstance(val, dict) and "error" in val:
        return aiohttp_web.json_response(val, status=400)
    return aiohttp_web.json_response(val)


async def handle_select(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Select a dropdown option by value or text."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    body = await request.json()
    selector = body.get("selector")
    value = body.get("value", "")
    if not selector:
        return aiohttp_web.json_response({"error": "Missing selector"}, status=400)

    js = f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el || el.tagName !== 'SELECT') return {{ error: 'Select element not found: ' + {json.dumps(selector)} }};
        const opt = Array.from(el.options).find(o => o.value === {json.dumps(value)} || o.text === {json.dumps(value)});
        if (!opt) return {{ error: 'Option not found: ' + {json.dumps(value)} }};
        el.value = opt.value;
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return {{ selected: opt.value, text: opt.text }};
    }})()"""

    resp = await send_cdp("Runtime.evaluate", {
        "expression": js, "returnByValue": True,
    }, session_id)
    val = resp.get("result", {}).get("result", {}).get("value", {})
    if isinstance(val, dict) and "error" in val:
        return aiohttp_web.json_response(val, status=400)
    return aiohttp_web.json_response(val)


async def handle_check_element(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Check or uncheck a checkbox."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    selector = await request.text()
    checked = request.query.get("checked", "true").lower() != "false"

    js = f"""(() => {{
        const el = document.querySelector({json.dumps(selector)});
        if (!el) return {{ error: 'Element not found: ' + {json.dumps(selector)} }};
        if (el.checked !== {json.dumps(checked)}) {{
            el.click();
        }}
        return {{ checked: el.checked }};
    }})()"""

    resp = await send_cdp("Runtime.evaluate", {
        "expression": js, "returnByValue": True,
    }, session_id)
    val = resp.get("result", {}).get("result", {}).get("value", {})
    if isinstance(val, dict) and "error" in val:
        return aiohttp_web.json_response(val, status=400)
    return aiohttp_web.json_response(val)


# ─── Cookies ────────────────────────────────────────────────────────────────

async def handle_cookies_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Get cookies. Optional ?domain= to filter by domain, ?url= to get cookies for specific URL."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    domain_filter = request.query.get("domain", "")
    url_filter = request.query.get("url", "")

    if url_filter:
        # Get cookies for specific URL
        resp = await send_cdp("Network.getCookies", {"urls": [url_filter]}, session_id)
    else:
        # Get current page URL for context, then fetch all cookies
        url_resp = await send_cdp("Runtime.evaluate", {
            "expression": "location.href", "returnByValue": True,
        }, session_id)
        current_url = url_resp.get("result", {}).get("result", {}).get("value", "")
        resp = await send_cdp("Network.getCookies", {"urls": [current_url]} if current_url else {}, session_id)

    cookies = resp.get("result", {}).get("cookies", [])

    # Filter by domain if requested
    if domain_filter:
        cookies = [c for c in cookies if domain_filter.lower() in c.get("domain", "").lower()]

    return aiohttp_web.json_response(cookies)


async def handle_cookies_set(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Set a cookie."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    body = await request.json()
    if not body.get("name") or body.get("value") is None:
        return aiohttp_web.json_response({"error": "Missing name or value"}, status=400)

    cookie = {k: v for k, v in body.items() if v is not None}
    resp = await send_cdp("Network.setCookie", cookie, session_id)
    return aiohttp_web.json_response({"success": resp.get("result", {}).get("success", False)})


async def handle_cookies_clear(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Clear all cookies."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    await send_cdp("Network.clearBrowserCookies", {}, session_id)
    return aiohttp_web.json_response({"cleared": True})


# ─── Storage ─────────────────────────────────────────────────────────────────

async def handle_storage_get(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Get localStorage or sessionStorage value(s)."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    storage_type = request.query.get("type", "local")
    key = request.query.get("key", "")
    store = "localStorage" if storage_type == "local" else "sessionStorage"

    if key:
        js = f"window.{store}.getItem({json.dumps(key)})"
    else:
        js = f"""(() => {{
            const result = {{}};
            for (let i = 0; i < window.{store}.length; i++) {{
                const k = window.{store}.key(i);
                result[k] = window.{store}.getItem(k);
            }}
            return result;
        }})()"""

    resp = await send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True}, session_id)
    value = resp.get("result", {}).get("result", {}).get("value")
    return aiohttp_web.json_response({"value": value})


async def handle_storage_set(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Set a localStorage or sessionStorage value."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    storage_type = request.query.get("type", "local")
    store = "localStorage" if storage_type == "local" else "sessionStorage"
    body = await request.json()
    key = body.get("key")
    value = body.get("value", "")

    if not key:
        return aiohttp_web.json_response({"error": "Missing key"}, status=400)

    js = f"window.{store}.setItem({json.dumps(key)}, {json.dumps(str(value))}); true"
    await send_cdp("Runtime.evaluate", {"expression": js}, session_id)
    return aiohttp_web.json_response({"set": True, "key": key})


async def handle_storage_clear(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Clear localStorage or sessionStorage."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    storage_type = request.query.get("type", "local")
    store = "localStorage" if storage_type == "local" else "sessionStorage"
    await send_cdp("Runtime.evaluate", {"expression": f"window.{store}.clear(); true"}, session_id)
    return aiohttp_web.json_response({"cleared": True, "type": storage_type})


# ─── Dialog ──────────────────────────────────────────────────────────────────

async def handle_dialog_status(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Check if a JavaScript dialog is currently open."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    # Page.enable is already called in ensure_session when the session is created.
    # Do NOT call any CDP command here — when a dialog is open, Chrome blocks
    # all CDP commands on that session, causing a timeout.

    dialog = pending_dialogs.get(target_id)
    if dialog:
        return aiohttp_web.json_response({
            "open": True,
            "type": dialog["type"],
            "message": dialog["message"],
            "defaultPrompt": dialog.get("defaultPrompt", ""),
        })
    return aiohttp_web.json_response({"open": False})


async def handle_dialog_accept(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Accept a JavaScript dialog (alert/confirm/prompt)."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    prompt_text = await request.text()
    dialog = pending_dialogs.get(target_id)
    if not dialog:
        return aiohttp_web.json_response({"error": "No dialog open"}, status=400)

    await send_cdp("Page.handleJavaScriptDialog", {
        "accept": True,
        "promptText": prompt_text or dialog.get("defaultPrompt", ""),
    }, session_id)
    pending_dialogs.pop(target_id, None)
    return aiohttp_web.json_response({"accepted": True})


async def handle_dialog_dismiss(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Dismiss a JavaScript dialog."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    if target_id not in pending_dialogs:
        return aiohttp_web.json_response({"error": "No dialog open"}, status=400)

    await send_cdp("Page.handleJavaScriptDialog", {"accept": False}, session_id)
    pending_dialogs.pop(target_id, None)
    return aiohttp_web.json_response({"dismissed": True})


# ─── Find (Semantic Locators) ────────────────────────────────────────────────

async def handle_find(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Find element by semantic locator (role, text, label, placeholder, testid) and perform action."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    by = request.query.get("by", "text")
    value = request.query.get("value", "")
    action = request.query.get("action", "click")
    name_filter = request.query.get("name", "")
    exact = request.query.get("exact", "false").lower() == "true"
    nth = int(request.query.get("nth", "0"))

    if not value:
        return aiohttp_web.json_response({"error": "Missing value"}, status=400)

    # Build JS selector based on locator type
    if by == "role":
        name_cond = ""
        if name_filter:
            if exact:
                name_cond = f" && (el.getAttribute('aria-label') === {json.dumps(name_filter)} || el.textContent.trim() === {json.dumps(name_filter)})"
            else:
                name_cond = f" && (el.getAttribute('aria-label')?.includes({json.dumps(name_filter)}) || el.textContent.trim().includes({json.dumps(name_filter)}))"
        js_find = f"""(() => {{
            const role = {json.dumps(value)};
            const roleMap = {{
                button: ['button', '[role="button"]'],
                link: ['a', '[role="link"]'],
                input: ['input', 'textarea'],
                checkbox: ['input[type="checkbox"]', '[role="checkbox"]'],
                radio: ['input[type="radio"]', '[role="radio"]'],
                select: ['select', '[role="listbox"]'],
                heading: ['h1,h2,h3,h4,h5,h6', '[role="heading"]'],
                img: ['img', '[role="img"]'],
                list: ['ul,ol', '[role="list"]'],
                listitem: ['li', '[role="listitem"]'],
                textbox: ['input[type="text"],input:not([type]),textarea', '[role="textbox"]'],
                combobox: ['select', '[role="combobox"]'],
            }};
            const selectors = roleMap[role] || [`[role="${{role}}"]`];
            const all = Array.from(document.querySelectorAll(selectors.join(',')));
            const filtered = all.filter(el => {{
                if (!el.offsetParent && el.tagName !== 'BODY') return false;
                {f'return true{name_cond};' if not name_cond else f'return true{name_cond};'}
            }});
            return filtered[{nth}] ? true : false;
        }})()"""
        # Use a simpler approach: build selector string
        role_selector_map = {
            "button": 'button, [role="button"]',
            "link": 'a, [role="link"]',
            "input": "input, textarea",
            "checkbox": 'input[type="checkbox"], [role="checkbox"]',
            "radio": 'input[type="radio"], [role="radio"]',
            "textbox": 'input[type="text"], input:not([type]), textarea, [role="textbox"]',
            "combobox": 'select, [role="combobox"]',
            "heading": "h1, h2, h3, h4, h5, h6",
        }
        base_sel = role_selector_map.get(value, f'[role="{value}"]')
        if name_filter:
            if exact:
                find_js = f"""Array.from(document.querySelectorAll({json.dumps(base_sel)})).filter(el => el.getAttribute('aria-label') === {json.dumps(name_filter)} || el.textContent.trim() === {json.dumps(name_filter)})[{nth}]"""
            else:
                find_js = f"""Array.from(document.querySelectorAll({json.dumps(base_sel)})).filter(el => (el.getAttribute('aria-label') || '').includes({json.dumps(name_filter)}) || el.textContent.trim().includes({json.dumps(name_filter)}))[{nth}]"""
        else:
            find_js = f"""document.querySelectorAll({json.dumps(base_sel)})[{nth}]"""

    elif by == "text":
        if exact:
            find_js = f"""Array.from(document.querySelectorAll('*')).filter(el => el.children.length === 0 && el.textContent.trim() === {json.dumps(value)})[{nth}]"""
        else:
            find_js = f"""Array.from(document.querySelectorAll('*')).filter(el => el.children.length === 0 && el.textContent.trim().includes({json.dumps(value)}))[{nth}]"""

    elif by == "label":
        find_js = f"""(() => {{
            const label = Array.from(document.querySelectorAll('label')).find(l => l.textContent.trim().includes({json.dumps(value)}));
            if (!label) return null;
            return label.control || document.getElementById(label.getAttribute('for'));
        }})()"""

    elif by == "placeholder":
        find_js = f"""document.querySelector('[placeholder*={json.dumps(value)}]')"""

    elif by == "testid":
        find_js = f"""document.querySelector('[data-testid={json.dumps(value)}]')"""

    elif by == "alt":
        find_js = f"""document.querySelector('[alt*={json.dumps(value)}]')"""

    else:
        return aiohttp_web.json_response({"error": f"Unknown locator type: {by}"}, status=400)

    # Perform action on found element
    if action == "click":
        js = f"""(() => {{
            const el = {find_js};
            if (!el) return {{ error: 'Element not found by {by}={json.dumps(value)}' }};
            el.scrollIntoView({{ block: 'center' }});
            el.click();
            return {{ clicked: true, tag: el.tagName, text: (el.textContent || '').slice(0, 100) }};
        }})()"""
    elif action == "text":
        js = f"""(() => {{
            const el = {find_js};
            if (!el) return {{ error: 'Element not found by {by}={json.dumps(value)}' }};
            return {{ text: el.textContent.trim() }};
        }})()"""
    elif action == "html":
        js = f"""(() => {{
            const el = {find_js};
            if (!el) return {{ error: 'Element not found by {by}={json.dumps(value)}' }};
            return {{ html: el.innerHTML }};
        }})()"""
    elif action == "fill":
        fill_value = request.query.get("fill_value", "")
        js = f"""(() => {{
            const el = {find_js};
            if (!el) return {{ error: 'Element not found by {by}={json.dumps(value)}' }};
            el.focus();
            el.value = {json.dumps(fill_value)};
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return {{ filled: true, value: el.value }};
        }})()"""
    elif action == "focus":
        js = f"""(() => {{
            const el = {find_js};
            if (!el) return {{ error: 'Element not found by {by}={json.dumps(value)}' }};
            el.focus();
            return {{ focused: true }};
        }})()"""
    elif action == "hover":
        js = f"""(() => {{
            const el = {find_js};
            if (!el) return {{ error: 'Element not found by {by}={json.dumps(value)}' }};
            el.scrollIntoView({{ block: 'center' }});
            const rect = el.getBoundingClientRect();
            return {{ x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 }};
        }})()"""
    else:
        return aiohttp_web.json_response({"error": f"Unknown action: {action}"}, status=400)

    resp = await send_cdp("Runtime.evaluate", {
        "expression": js, "returnByValue": True, "awaitPromise": True,
    }, session_id)
    val = resp.get("result", {}).get("result", {}).get("value", {})
    if isinstance(val, dict) and "error" in val:
        return aiohttp_web.json_response(val, status=404)

    # For hover action, dispatch mouse event
    if action == "hover" and isinstance(val, dict) and "x" in val:
        await send_cdp("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": val["x"], "y": val["y"],
        }, session_id)
        return aiohttp_web.json_response({"hovered": True, "x": val["x"], "y": val["y"]})

    return aiohttp_web.json_response(val if val else {"ok": True})


# ─── Network Capture ─────────────────────────────────────────────────────────

async def handle_network_start(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Start network capture for a target."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    network_captures[target_id] = deque(maxlen=MAX_CAPTURES_PER_TARGET)
    await send_cdp("Network.enable", {
        "maxTotalBufferSize": 10 * 1024 * 1024,
        "maxResourceBufferSize": 5 * 1024 * 1024,
    }, session_id)
    return aiohttp_web.json_response({"capturing": True, "targetId": target_id})

async def handle_open_monitored(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Create a new tab with network monitoring already active, then navigate to URL.

    This atomically performs: createTarget(about:blank) → Network.enable → Page.navigate,
    guaranteeing that no initial XHR/fetch requests are missed due to timing.
    """
    await connect()
    url = request.query.get("url", "about:blank")

    # 1. Create a blank background tab.
    create_resp = await send_cdp("Target.createTarget", {"url": "about:blank", "background": True})
    target_id = create_resp["result"]["targetId"]

    # 2. Establish a session and enable network capture BEFORE navigating.
    session_id = await ensure_session(target_id)
    network_captures[target_id] = deque(maxlen=MAX_CAPTURES_PER_TARGET)
    await send_cdp("Network.enable", {
        "maxTotalBufferSize": 10 * 1024 * 1024,
        "maxResourceBufferSize": 5 * 1024 * 1024,
    }, session_id)

    # 3. Navigate to the target URL and wait for load.
    if url != "about:blank":
        await send_cdp("Page.navigate", {"url": url}, session_id)
        try:
            await wait_for_load(session_id)
        except Exception:
            pass  # Non-fatal — tab is open and monitoring is active

    return aiohttp_web.json_response({"targetId": target_id, "capturing": True, "url": url})


async def handle_network_stop(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Stop network capture."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)

    evicted = network_captures.pop(target_id, None)
    count = len(evicted) if evicted else 0
    if evicted:
        ids_to_remove = {r.get("requestId") for r in evicted}
        for rid in ids_to_remove:
            network_request_map.pop(rid, None)
    await send_cdp("Network.disable", {}, session_id)
    return aiohttp_web.json_response({"stopped": True, "requestsCaptured": count})


async def handle_network_requests(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """List captured network requests with optional filters."""
    target_id = request.query["target"]
    records = list(network_captures.get(target_id, []))

    url_filter = request.query.get("filter", "")
    method_filter = request.query.get("method", "").upper()
    type_filter = request.query.get("type", "")
    status_filter = request.query.get("status", "")
    limit = int(request.query.get("limit", "0"))

    if url_filter:
        records = [r for r in records if url_filter.lower() in (r.get("url") or "").lower()]
    if method_filter:
        records = [r for r in records if r.get("method", "").upper() == method_filter]
    if type_filter:
        types = [t.strip().lower() for t in type_filter.split(",")]
        records = [r for r in records if (r.get("resourceType") or "").lower() in types]
    if status_filter:
        def match_status(s):
            if s is None:
                return False
            s = int(s)
            if status_filter.endswith("xx"):
                prefix = int(status_filter[0])
                return s // 100 == prefix
            if "-" in status_filter:
                lo, hi = status_filter.split("-")
                return int(lo) <= s <= int(hi)
            return s == int(status_filter)
        records = [r for r in records if match_status(r.get("status"))]

    total = len(records)
    # Apply limit — take the most recent N records
    if limit > 0:
        records = records[-limit:]

    # Return summary (exclude body for list view)
    summary = [{
        "requestId": r.get("requestId"),
        "url": r.get("url"),
        "method": r.get("method"),
        "resourceType": r.get("resourceType"),
        "status": r.get("status"),
        "mimeType": r.get("mimeType"),
        "hasBody": r.get("_loaded", False),
    } for r in records]

    return aiohttp_web.json_response({"requests": summary, "total": total, "returned": len(summary)})


async def handle_network_request_detail(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Get full detail of a single request including response body."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    request_id = request.query.get("id")

    if not request_id:
        return aiohttp_web.json_response({"error": "Missing id parameter"}, status=400)

    record = network_request_map.get(request_id)
    if not record:
        return aiohttp_web.json_response({"error": f"Request {request_id} not found"}, status=404)

    # Fetch response body if loaded — must use the session that captured the request
    response_body = None
    response_body_base64 = False
    body_error = None
    fetch_session = record.get("_sessionId") or session_id
    if record.get("_loaded"):
        try:
            body_resp = await send_cdp("Network.getResponseBody", {
                "requestId": request_id,
            }, fetch_session)
            body_result = body_resp.get("result", {})
            response_body = body_result.get("body", "")
            response_body_base64 = body_result.get("base64Encoded", False)
        except Exception as exc:
            body_error = str(exc)

    detail = {
        "requestId": record.get("requestId"),
        "url": record.get("url"),
        "method": record.get("method"),
        "resourceType": record.get("resourceType"),
        "requestHeaders": record.get("headers", {}),
        "postData": record.get("postData"),
        "status": record.get("status"),
        "responseHeaders": record.get("responseHeaders", {}),
        "mimeType": record.get("mimeType"),
        "responseBody": response_body,
        "responseBodyBase64": response_body_base64,
        "bodyError": body_error,
    }
    return aiohttp_web.json_response(detail)


async def handle_network_clear(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Clear captured requests for a target."""
    target_id = request.query["target"]
    count = len(network_captures.get(target_id, []))
    if target_id in network_captures:
        ids_to_remove = {r.get("requestId") for r in network_captures[target_id]}
        for rid in ids_to_remove:
            network_request_map.pop(rid, None)
        network_captures[target_id] = deque(maxlen=MAX_CAPTURES_PER_TARGET)
    return aiohttp_web.json_response({"cleared": count})


async def handle_scripts_enable(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Enable Debugger domain to capture all scripts for a target."""
    await connect()
    target_id = request.query["target"]
    session_id = await ensure_session(target_id)
    
    # Initialize script capture for this target
    if target_id not in script_captures:
        script_captures[target_id] = []
    
    # Enable Debugger domain
    try:
        await send_cdp("Debugger.enable", {}, session_id)
        return aiohttp_web.json_response({"enabled": True, "targetId": target_id})
    except Exception as exc:
        return aiohttp_web.json_response({"error": str(exc)}, status=500)


async def handle_scripts_list(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """List captured scripts for a target, with optional URL keyword filter.

    By default, chrome-extension:// scripts are excluded since their source
    cannot be retrieved via the page session. Pass ?all=1 to include them.
    """
    target_id = request.query.get("target", "")
    url_filter = request.query.get("filter", "").lower()
    include_all = request.query.get("all", "0") == "1"

    def _format_script(script: dict) -> dict:
        return {"scriptId": script["scriptId"], "url": script.get("url", "")}

    def _matches(script: dict) -> bool:
        url = script.get("url", "")
        if not include_all and url.startswith("chrome-extension://"):
            return False
        return not url_filter or url_filter in url.lower()

    if not target_id:
        result = {}
        for tid, scripts in script_captures.items():
            result[tid] = [_format_script(s) for s in scripts if _matches(s)]
        return aiohttp_web.json_response(result)

    scripts = script_captures.get(target_id, [])
    matched = [_format_script(s) for s in scripts if _matches(s)]
    return aiohttp_web.json_response({
        "targetId": target_id,
        "count": len(matched),
        "scripts": matched,
    })


async def handle_scripts_source(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Get source code for a specific script."""
    await connect()
    target_id = request.query["target"]
    script_id = request.query["scriptId"]
    session_id = await ensure_session(target_id)
    
    try:
        resp = await send_cdp("Debugger.getScriptSource", {
            "scriptId": script_id,
        }, session_id)
        
        if "result" in resp:
            source = resp["result"].get("scriptSource", "")
            # Find script info
            script_info = None
            for s in script_captures.get(target_id, []):
                if s["scriptId"] == script_id:
                    script_info = s
                    break
            
            return aiohttp_web.json_response({
                "scriptId": script_id,
                "url": script_info["url"] if script_info else "",
                "sourceLength": len(source),
                "source": source,
            })
        else:
            return aiohttp_web.json_response({"error": resp.get("error", "Unknown error")}, status=400)
    except Exception as exc:
        error_msg = str(exc)
        if "No script for id" in error_msg:
            return aiohttp_web.json_response({
                "error": error_msg,
                "hint": "This script belongs to a chrome-extension and cannot be retrieved via the page session. Use 'scripts-list' (without --all) to see only retrievable scripts.",
            }, status=400)
        return aiohttp_web.json_response({"error": error_msg}, status=500)


async def handle_not_found(request: aiohttp_web.Request) -> aiohttp_web.Response:
    """Handle unknown endpoints."""
    return aiohttp_web.json_response({
        "error": "Unknown endpoint",
        "endpoints": {
            "/health": "GET - Health check",
            "/targets": "GET - List all tabs (?type= to filter)",
            "/new?url=": "GET - Create new background tab",
            "/close?target=": "GET - Close tab",
            "/navigate?target=&url=": "GET - Navigate to URL",
            "/back?target=": "GET - Go back",
            "/reload?target=": "GET - Reload tab",
            "/info?target=": "GET - Page info",
            "/eval?target=": "POST body=JS expression - Execute JS",
            "/click?target=": "POST body=CSS selector - Click element",
            "/click-at?target=": "POST body=CSS selector - Real mouse click",
            "/scroll?target=&y=&direction=": "GET - Scroll page",
            "/screenshot?target=&file=": "GET - Screenshot",
        }
    }, status=404)


def check_port_available(port: int) -> bool:
    """Check if a port is available.

    Uses SO_REUSEADDR to avoid false negatives from TIME_WAIT sockets left
    behind after a process is killed.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _check_existing_proxy(port: int) -> bool:
    """Return True if a healthy proxy instance is already listening on the port."""
    import urllib.request as _urllib_request
    try:
        with _urllib_request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok"
    except Exception:
        return False


async def main() -> None:
    """Main entry point."""
    # Check if port is available
    if not check_port_available(PORT):
        # Port is occupied — check if it's a healthy proxy we should defer to
        if _check_existing_proxy(PORT):
            print(f"[CDP Proxy] Instance already running on port {PORT}, exiting")
            return
        print(f"[CDP Proxy] Port {PORT} is already in use")
        sys.exit(1)
    
    # Create app
    app = aiohttp_web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get("/browser", handle_browser)
    app.router.add_get("/targets", handle_targets)
    app.router.add_get("/new", handle_new)
    app.router.add_get("/close", handle_close)
    app.router.add_get("/navigate", handle_navigate)
    app.router.add_get("/back", handle_back)
    app.router.add_get("/reload", handle_reload)
    app.router.add_post("/eval", handle_eval)
    app.router.add_post("/click", handle_click)
    app.router.add_post("/clickAt", handle_click_at)
    app.router.add_post("/setFiles", handle_set_files)
    app.router.add_get("/scroll", handle_scroll)
    app.router.add_get("/screenshot", handle_screenshot)
    app.router.add_get("/info", handle_info)
    app.router.add_post("/fill", handle_fill)
    app.router.add_post("/type", handle_type)
    app.router.add_post("/hover", handle_hover)
    app.router.add_post("/press", handle_press)
    app.router.add_get("/forward", handle_forward)
    app.router.add_get("/get", handle_get)
    app.router.add_get("/wait", handle_wait)
    app.router.add_get("/is", handle_is)
    app.router.add_get("/snapshot", handle_snapshot)
    app.router.add_get("/console", handle_console)
    app.router.add_post("/focus", handle_focus)
    app.router.add_post("/select", handle_select)
    app.router.add_post("/check", handle_check_element)
    app.router.add_get("/cookies", handle_cookies_get)
    app.router.add_post("/cookies/set", handle_cookies_set)
    app.router.add_get("/cookies/clear", handle_cookies_clear)
    app.router.add_get("/storage", handle_storage_get)
    app.router.add_post("/storage/set", handle_storage_set)
    app.router.add_get("/storage/clear", handle_storage_clear)
    app.router.add_get("/dialog/status", handle_dialog_status)
    app.router.add_post("/dialog/accept", handle_dialog_accept)
    app.router.add_get("/dialog/dismiss", handle_dialog_dismiss)
    app.router.add_get("/find", handle_find)
    app.router.add_get("/network/start", handle_network_start)
    app.router.add_get("/network/open-monitored", handle_open_monitored)
    app.router.add_get("/network/stop", handle_network_stop)
    app.router.add_get("/network/requests", handle_network_requests)
    app.router.add_get("/network/request", handle_network_request_detail)
    app.router.add_get("/network/clear", handle_network_clear)
    app.router.add_get("/scripts/enable", handle_scripts_enable)
    app.router.add_get("/scripts/list", handle_scripts_list)
    app.router.add_get("/scripts/source", handle_scripts_source)
    app.router.add_get("/", handle_not_found)
    
    print(f"[CDP Proxy] Running on http://localhost:{PORT}")
    
    # Start server
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    site = aiohttp_web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    
    # Try to connect to Chrome (non-blocking)
    try:
        await connect()
    except Exception as e:
        print(f"[CDP Proxy] Initial connection failed: {e} (will retry on first request)")
    
    # Keep running
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()


def _apply_cli_args(port: Optional[int], chrome_port: Optional[int]) -> None:
    """Apply command-line arguments, overriding module-level configuration."""
    global PORT, CHROME_PORT_OVERRIDE
    if port is not None:
        PORT = port
    if chrome_port is not None:
        CHROME_PORT_OVERRIDE = chrome_port


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CDP Proxy - Chrome DevTools Protocol HTTP Proxy")
    parser.add_argument("--port", type=int, default=None, help="Proxy listen port (default: CDP_PROXY_PORT env or 3456)")
    parser.add_argument("--chrome-port", type=int, default=None, help="Chrome remote debugging port to connect (default: CDP_CHROME_PORT env or auto-discover)")
    args = parser.parse_args()

    _apply_cli_args(args.port, args.chrome_port)
    asyncio.run(main())
