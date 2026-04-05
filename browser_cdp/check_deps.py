#!/usr/bin/env python3
"""
Check Dependencies - Environment check and CDP Proxy readiness

This module checks Chrome debugging port availability and ensures
CDP Proxy is running.
"""

import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional


def check_port(port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> bool:
    """Check if a port is open via TCP connection."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def get_devtools_active_port_paths() -> list:
    """Get possible paths for DevToolsActivePort file based on platform."""
    paths = []
    plat = platform.system()

    if plat == "Darwin":
        home = Path.home()
        paths.extend([
            home / "Library/Application Support/Google/Chrome/DevToolsActivePort",
            home / "Library/Application Support/Google/Chrome Canary/DevToolsActivePort",
            home / "Library/Application Support/Chromium/DevToolsActivePort",
        ])
    elif plat == "Linux":
        home = Path.home()
        paths.extend([
            home / ".config/google-chrome/DevToolsActivePort",
            home / ".config/chromium/DevToolsActivePort",
        ])
    elif plat == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        paths.extend([
            Path(local_app_data) / "Google/Chrome/User Data/DevToolsActivePort",
            Path(local_app_data) / "Chromium/User Data/DevToolsActivePort",
        ])

    return paths


def detect_chrome_port() -> Optional[int]:
    """Detect Chrome's remote debugging port."""
    # Try DevToolsActivePort file first
    for path in get_devtools_active_port_paths():
        try:
            content = path.read_text().strip()
            lines = content.split("\n")
            port = int(lines[0])
            if 0 < port < 65536 and check_port(port):
                return port
        except (FileNotFoundError, ValueError, IndexError):
            continue

    # Try common ports
    for port in [9222, 9229, 9333]:
        if check_port(port):
            return port

    return None


def http_get_json(url: str, timeout_seconds: float = 3.0) -> Optional[dict]:
    """Make HTTP GET request and return JSON using urllib (no event loop needed)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def start_proxy_detached() -> None:
    """Start CDP Proxy as a detached process."""
    script_path = Path(__file__).parent / "cdp_proxy.py"
    log_file = Path(os.environ.get("TMPDIR", "/tmp")) / "cdp-proxy.log"

    with open(log_file, "a") as log_fd:
        subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
        )


def ensure_proxy(proxy_port: int) -> bool:
    """Ensure CDP Proxy is running and healthy."""
    health_url = f"http://127.0.0.1:{proxy_port}/health"

    # Fast path: proxy already up and healthy
    if check_port(proxy_port):
        health = http_get_json(health_url)
        if health and health.get("status") == "ok":
            print("proxy: ready")
            return True

    # Start Proxy
    print("proxy: connecting...")
    start_proxy_detached()

    # Wait for Proxy HTTP server to be ready (TCP + health check)
    for i in range(15):
        time.sleep(1)
        if not check_port(proxy_port):
            continue
        health = http_get_json(health_url)
        if health and health.get("status") == "ok":
            print("proxy: ready")
            return True
        if i == 0:
            print("⚠️  Chrome may have an authorization popup, please click 'Allow' and wait...")

    print("❌ Connection timeout, please check Chrome debugging settings")
    log_file = Path(os.environ.get("TMPDIR", "/tmp")) / "cdp-proxy.log"
    print(f"  Log: {log_file}")
    return False


def show_chrome_help() -> None:
    """Show Chrome remote debugging setup instructions."""
    plat = platform.system()
    print("\n📋 Chrome Remote Debugging Setup:")

    if plat == "Darwin":
        print("  Desktop Environment:")
        print("    1. Open Chrome, visit chrome://inspect/#remote-debugging")
        print('    2. Check "Allow remote debugging for this browser instance"')
        print("    3. May need to restart browser")
        print("\n  Headless Mode:")
        print("    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --headless=new --remote-debugging-port=9222")
    elif plat == "Linux":
        print("  Desktop Environment:")
        print("    1. Open Chrome, visit chrome://inspect/#remote-debugging")
        print('    2. Check "Allow remote debugging for this browser instance"')
        print("    3. May need to restart browser")
        print("\n  Headless Mode (Recommended):")
        print("    google-chrome --headless=new --remote-debugging-port=9222")
        print("\n  Docker Environment:")
        print("    google-chrome --headless=new --remote-debugging-port=9222 --no-sandbox --disable-dev-shm-usage")
    elif plat == "Windows":
        print("  Desktop Environment:")
        print("    1. Open Chrome, visit chrome://inspect/#remote-debugging")
        print('    2. Check "Allow remote debugging for this browser instance"')
        print("    3. May need to restart browser")
        print("\n  Headless Mode:")
        print('    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --headless=new --remote-debugging-port=9222')


def main() -> None:
    """Main entry point."""
    chrome_port = detect_chrome_port()
    if not chrome_port:
        print("chrome: not connected")
        show_chrome_help()
        sys.exit(1)

    print(f"chrome: ok (port {chrome_port})")

    proxy_port = int(os.environ.get("CDP_PROXY_PORT", "3456"))
    if not ensure_proxy(proxy_port):
        sys.exit(1)


if __name__ == "__main__":
    main()
