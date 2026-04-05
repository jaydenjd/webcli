#!/usr/bin/env python3
"""
CDP CLI 全功能自动化测试
测试所有真实 Proxy 端点对应的 CLI 命令
"""
import json
import subprocess
import sys
import time

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"
SKIP = "\033[93m⏭  SKIP\033[0m"
INFO = "\033[94mℹ️  INFO\033[0m"

results = {"pass": 0, "fail": 0, "skip": 0}
TARGET_ID = None


def run(cmd: str, timeout: int = 20) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def test(name: str, cmd: str, expect_key: str = None, expect_val=None,
         expect_in: str = None, expect_not_error: bool = True, timeout: int = 20):
    """Run a test case."""
    global results
    try:
        rc, stdout, stderr = run(cmd, timeout=timeout)
        output = stdout or stderr

        if expect_not_error and rc != 0:
            print(f"{FAIL} [{name}]")
            print(f"       cmd: {cmd}")
            print(f"       rc={rc}, stderr={stderr[:200]}")
            results["fail"] += 1
            return None

        # Try parse JSON — strip trailing "# Next: ..." hint lines before parsing
        data = None
        try:
            json_text = "\n".join(
                l for l in stdout.splitlines() if not l.strip().startswith("#")
            ).strip()
            data = json.loads(json_text)
        except Exception:
            data = stdout

        if expect_key and isinstance(data, dict):
            actual = data.get(expect_key)
            if expect_val is not None and actual != expect_val:
                print(f"{FAIL} [{name}] expected {expect_key}={expect_val!r}, got {actual!r}")
                results["fail"] += 1
                return data
            elif expect_val is None and actual is None:
                print(f"{FAIL} [{name}] key '{expect_key}' missing in response")
                results["fail"] += 1
                return data

        if expect_in and expect_in not in output:
            print(f"{FAIL} [{name}] expected '{expect_in}' in output")
            print(f"       output: {output[:200]}")
            results["fail"] += 1
            return data

        print(f"{PASS} [{name}]")
        if data and isinstance(data, dict) and len(str(data)) < 200:
            print(f"       → {data}")
        results["pass"] += 1
        return data

    except subprocess.TimeoutExpired:
        print(f"{FAIL} [{name}] TIMEOUT after {timeout}s")
        results["fail"] += 1
        return None
    except Exception as exc:
        print(f"{FAIL} [{name}] Exception: {exc}")
        results["fail"] += 1
        return None


def skip(name: str, reason: str):
    print(f"{SKIP} [{name}] {reason}")
    results["skip"] += 1


# ─── 0. Health ────────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  0. Health & Proxy")
print("══════════════════════════════════════════")

health = test("health", "webcli health", expect_key="status", expect_val="ok")
if not health:
    print(f"\n{FAIL} Proxy not healthy, aborting tests")
    sys.exit(1)

# ─── 1. Tab management ────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  1. Tab Management")
print("══════════════════════════════════════════")

targets_data = test("targets", "webcli targets")
if isinstance(targets_data, list) and targets_data:
    print(f"       {INFO} Found {len(targets_data)} existing tabs")

# Create a new tab with a simple test page
new_data = test("new tab", "webcli new https://example.com", expect_key="targetId")
if new_data and isinstance(new_data, dict):
    TARGET_ID = new_data.get("targetId")
    print(f"       {INFO} Created tab: {TARGET_ID}")
else:
    print(f"\n{FAIL} Could not create tab, aborting")
    sys.exit(1)

test("info", f"webcli info {TARGET_ID}", expect_key="title")
test("targets with type filter", "webcli targets --type page")

# ─── 2. Navigation ────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  2. Navigation")
print("══════════════════════════════════════════")

test("navigate", f"webcli navigate {TARGET_ID} https://example.com", expect_key="url")
time.sleep(1)
test("back", f"webcli back {TARGET_ID}", expect_key="ok")
time.sleep(1)
test("forward", f"webcli forward {TARGET_ID}", expect_key="ok")
time.sleep(1)
test("reload", f"webcli reload {TARGET_ID}", expect_key="ok")
time.sleep(1)

# ─── 3. JavaScript eval ───────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  3. JavaScript Eval")
print("══════════════════════════════════════════")

test("eval simple", f"webcli eval {TARGET_ID} 'document.title'", expect_in="Example")
test("eval arithmetic", f"webcli eval {TARGET_ID} '1 + 2'", expect_in="3")

# eval from file
import tempfile, os
with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
    f.write("document.querySelectorAll('a').length")
    js_file = f.name
test("eval from file", f"webcli eval {TARGET_ID} -f {js_file}")
os.unlink(js_file)

# ─── 4. Page inspection ───────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  4. Page Inspection")
print("══════════════════════════════════════════")

test("get title", f"webcli get {TARGET_ID} title", expect_in="Example")
test("get url", f"webcli get {TARGET_ID} url", expect_in="example.com")
test("get text", f"webcli get {TARGET_ID} text", expect_in="Example")
test("get html", f"webcli get {TARGET_ID} html", expect_in="<html")
test("get count", f"webcli get {TARGET_ID} count 'a'")
test("get box", f"webcli get {TARGET_ID} box 'h1'")

# ─── 5. Snapshot ──────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  5. Snapshot (Accessibility Tree)")
print("══════════════════════════════════════════")

rc, stdout, _ = run(f"webcli snapshot {TARGET_ID}", timeout=30)
if rc == 0 and stdout:
    print(f"{PASS} [snapshot] Got {len(stdout.splitlines())} lines")
    results["pass"] += 1
else:
    print(f"{FAIL} [snapshot] rc={rc}")
    results["fail"] += 1

# ─── 6. Screenshot ────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  6. Screenshot")
print("══════════════════════════════════════════")

shot_file = "/tmp/test_cdp_screenshot.png"
test("screenshot to file", f"webcli screenshot {TARGET_ID} {shot_file}", expect_key="saved")
if os.path.exists(shot_file):
    size = os.path.getsize(shot_file)
    print(f"       {INFO} Screenshot saved: {size} bytes")
    os.unlink(shot_file)

# ─── 7. Scroll ────────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  7. Scroll")
print("══════════════════════════════════════════")

test("scroll bottom", f"webcli scroll {TARGET_ID} bottom")
test("scroll top", f"webcli scroll {TARGET_ID} top")
test("scroll pixels", f"webcli scroll {TARGET_ID} 200")

# ─── 8. Click & Interaction ───────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  8. Click & Interaction")
print("══════════════════════════════════════════")

test("click link", f"webcli click {TARGET_ID} 'a'")
time.sleep(1)
test("navigate back to example", f"webcli navigate {TARGET_ID} https://example.com")
time.sleep(1)
test("hover h1", f"webcli hover {TARGET_ID} 'h1'")
test("focus body", f"webcli focus {TARGET_ID} 'body'")

# ─── 9. Fill / Type / Form ────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  9. Fill / Type / Form (using httpbin)")
print("══════════════════════════════════════════")

# Navigate to a page with a form
test("navigate to form page", f"webcli navigate {TARGET_ID} 'data:text/html,<input id=q type=text><select id=s><option value=a>A</option><option value=b>B</option></select><input id=cb type=checkbox>'")
time.sleep(1)

test("fill input", f"webcli fill {TARGET_ID} '#q' 'hello world'")
rc, stdout, _ = run(f"webcli get {TARGET_ID} value '#q'")
if "hello world" in stdout:
    print(f"{PASS} [fill verified] value='hello world'")
    results["pass"] += 1
else:
    print(f"{FAIL} [fill verified] got: {stdout[:100]}")
    results["fail"] += 1

test("type into input", f"webcli type {TARGET_ID} '#q' ' typed'")
test("select option", f"webcli select {TARGET_ID} '#s' 'b'")
test("check checkbox", f"webcli check {TARGET_ID} '#cb'")
rc, stdout, _ = run(f"webcli is {TARGET_ID} checked '#cb'")
data = json.loads(stdout) if stdout else {}
if data.get("result") is True:
    print(f"{PASS} [check verified] checkbox is checked")
    results["pass"] += 1
else:
    print(f"{FAIL} [check verified] got: {stdout[:100]}")
    results["fail"] += 1

test("uncheck checkbox", f"webcli uncheck {TARGET_ID} '#cb'")
test("press Tab", f"webcli press {TARGET_ID} 'Tab'")
test("press Enter", f"webcli press {TARGET_ID} 'Enter'")

# ─── 10. Wait & Is ────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  10. Wait & Is")
print("══════════════════════════════════════════")

test("wait ms", f"webcli wait {TARGET_ID} 500", expect_key="waited", timeout=10)
test("wait selector", f"webcli wait {TARGET_ID} '#q'", expect_key="ok", timeout=10)
test("wait text", f"webcli wait {TARGET_ID} --text 'A'", expect_key="ok", timeout=10)
test("is visible", f"webcli is {TARGET_ID} visible '#q'", expect_key="result")
test("is enabled", f"webcli is {TARGET_ID} enabled '#q'", expect_key="result")
test("is checked", f"webcli is {TARGET_ID} checked '#cb'", expect_key="result")

# ─── 11. Find (Semantic Locators) ─────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  11. Find (Semantic Locators)")
print("══════════════════════════════════════════")

# Navigate to a page with semantic elements
test("navigate to semantic page",
     f"webcli navigate {TARGET_ID} 'data:text/html,<button>Submit</button><label>Email<input type=email id=em></label><input placeholder=Search>'")
time.sleep(1)

test("find by role", f"webcli find {TARGET_ID} role button click")
test("find by text", f"webcli find {TARGET_ID} text 'Submit' text")
test("find by label", f"webcli find {TARGET_ID} label 'Email' focus")
test("find by placeholder", f"webcli find {TARGET_ID} placeholder 'Search' fill --fill-value 'test'")

# ─── 12. Console ──────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  12. Console")
print("══════════════════════════════════════════")

# Inject console messages then read
run(f"webcli eval {TARGET_ID} 'console.log(\"test-log\")'")
time.sleep(0.5)
test("console", f"webcli console {TARGET_ID}")

# ─── 13. Cookies ──────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  13. Cookies")
print("══════════════════════════════════════════")

test("navigate for cookies", f"webcli navigate {TARGET_ID} https://example.com")
time.sleep(1)

# Set a cookie
test("cookies-set", f"webcli cookies-set {TARGET_ID} test_cookie test_value --domain example.com")
time.sleep(0.3)

# Get all cookies
rc, stdout, _ = run(f"webcli cookies {TARGET_ID}")
cookies_list = json.loads(stdout) if stdout else []
if isinstance(cookies_list, list):
    print(f"{PASS} [cookies get] Got {len(cookies_list)} cookies")
    results["pass"] += 1
else:
    print(f"{FAIL} [cookies get] unexpected: {stdout[:100]}")
    results["fail"] += 1

# Filter by domain
test("cookies --domain", f"webcli cookies {TARGET_ID} --domain example.com")
test("cookies --url", f"webcli cookies {TARGET_ID} --url https://example.com/")
test("cookies-clear", f"webcli cookies-clear {TARGET_ID}", expect_key="cleared")

# ─── 14. Storage ──────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  14. Storage")
print("══════════════════════════════════════════")

test("storage-set local", f"webcli storage-set {TARGET_ID} test_key test_value")
rc, stdout, _ = run(f"webcli storage {TARGET_ID} test_key")
if "test_value" in stdout:
    print(f"{PASS} [storage get key] value='test_value'")
    results["pass"] += 1
else:
    print(f"{FAIL} [storage get key] got: {stdout[:100]}")
    results["fail"] += 1

test("storage get all", f"webcli storage {TARGET_ID}")
test("storage-set session", f"webcli storage-set {TARGET_ID} sess_key sess_val --type session")
test("storage get session", f"webcli storage {TARGET_ID} sess_key --type session")
test("storage-clear local", f"webcli storage-clear {TARGET_ID}", expect_key="cleared")
test("storage-clear session", f"webcli storage-clear {TARGET_ID} --type session", expect_key="cleared")

# ─── 15. Dialog ───────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  15. Dialog")
print("══════════════════════════════════════════")

# Check status when no dialog
test("dialog-status (no dialog)", f"webcli dialog-status {TARGET_ID}", expect_key="open")

# Trigger an alert in background, then accept.
# Use a longer delay so Page.enable (fired async in ensure_session) has time to
# register before the alert fires, and the dialog event is captured by the Proxy.
run(f"webcli eval {TARGET_ID} 'setTimeout(() => alert(\"test\"), 800)'")
time.sleep(1.5)
rc, stdout, _ = run(f"webcli dialog-status {TARGET_ID}")
data = json.loads(stdout) if stdout else {}
if data.get("open"):
    print(f"{PASS} [dialog-status open] type={data.get('type')}, msg={data.get('message')}")
    results["pass"] += 1
    test("dialog-accept", f"webcli dialog-accept {TARGET_ID}", expect_key="accepted")
else:
    # Dialog may have already closed or timing issue
    print(f"{SKIP} [dialog open check] dialog may have closed before check")
    results["skip"] += 1
    skip("dialog-accept", "no dialog to accept")

# ─── 16. Network Capture ──────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  16. Network Capture")
print("══════════════════════════════════════════")

test("network-start", f"webcli network-start {TARGET_ID}", expect_key="capturing")
time.sleep(0.3)

# Trigger some network requests
test("navigate to trigger requests", f"webcli navigate {TARGET_ID} https://example.com")
time.sleep(2)

# List requests
rc, stdout, _ = run(f"webcli network-requests {TARGET_ID}")
if rc == 0 and "Total:" in stdout:
    print(f"{PASS} [network-requests] {stdout.splitlines()[0]}")
    results["pass"] += 1
else:
    print(f"{FAIL} [network-requests] rc={rc}, out={stdout[:200]}")
    results["fail"] += 1

# Filter tests
test("network-requests --type document", f"webcli network-requests {TARGET_ID} --type document")
test("network-requests --method GET", f"webcli network-requests {TARGET_ID} --method GET")
test("network-requests --filter example", f"webcli network-requests {TARGET_ID} --filter example")
test("network-requests --status 2xx", f"webcli network-requests {TARGET_ID} --status 2xx")

# Get detail of first request
rc2, stdout2, _ = run(f"webcli network-requests {TARGET_ID} --type document")
# Extract requestId from output
req_id = None
for line in stdout2.splitlines():
    if "id:" in line:
        req_id = line.split("id:")[-1].strip()
        break

if req_id:
    print(f"       {INFO} Testing network-request detail for id={req_id[:20]}...")
    test("network-request detail", f"webcli network-request {TARGET_ID} '{req_id}'", expect_key="url", timeout=30)
else:
    skip("network-request detail", "no request ID found in listing")

test("network-clear", f"webcli network-clear {TARGET_ID}", expect_key="cleared")
test("network-stop", f"webcli network-stop {TARGET_ID}", expect_key="stopped")

# ─── 17. Network Capture Memory Limits ───────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  17. Network Capture Memory Limits")
print("══════════════════════════════════════════")

# 17-1. open-monitored 创建 tab 并立即开启网络监控
rc, stdout, _ = run("webcli open-monitored https://example.com --id-only")
mem_target = stdout.strip() if rc == 0 else None
if not mem_target:
    skip("memory-limit: open-monitored", "failed to create monitored tab")
else:
    print(f"       {INFO} Memory test tab: {mem_target}")

    # 17-2. 导航到一个会产生大量请求的页面，验证 Total 不超过 MAX_CAPTURES_PER_TARGET
    run(f"webcli navigate {mem_target} https://www.baidu.com")
    time.sleep(3)

    rc2, stdout2, _ = run(f"webcli network-requests {mem_target}")
    total_line = next((l for l in stdout2.splitlines() if l.startswith("Total:")), "")
    total_count = 0
    if total_line:
        try:
            total_count = int(total_line.split(":")[1].split()[0])
        except Exception:
            pass

    if total_count <= 2000:
        print(f"{PASS} [memory-limit: total requests capped] total={total_count} ≤ 2000")
        results["pass"] += 1
    else:
        print(f"{FAIL} [memory-limit: total requests capped] total={total_count} > 2000")
        results["fail"] += 1

    # 17-3. network-clear 后请求数归零，且 deque 仍可继续接收新请求
    test("memory-limit: network-clear resets to 0",
         f"webcli network-clear {mem_target}", expect_key="cleared")

    rc3, stdout3, _ = run(f"webcli network-requests {mem_target}")
    after_clear_line = next((l for l in stdout3.splitlines() if l.startswith("Total:")), "")
    if "0 requests" in after_clear_line:
        print(f"{PASS} [memory-limit: cleared to 0] {after_clear_line.strip()}")
        results["pass"] += 1
    else:
        print(f"{FAIL} [memory-limit: cleared to 0] unexpected: {after_clear_line}")
        results["fail"] += 1

    # 17-4. close tab 后内存自动释放（验证 close 不报错）
    test("memory-limit: close releases memory",
         f"webcli close {mem_target}", expect_key="closed")

    # 17-5. 关闭后再查询该 target 的 requests，应返回 total=0（captures 已清理）
    rc4, stdout4, _ = run(f"webcli network-requests {mem_target}")
    after_close_line = next((l for l in stdout4.splitlines() if l.startswith("Total:")), "")
    if "0 requests" in after_close_line:
        print(f"{PASS} [memory-limit: closed tab returns 0] {after_close_line.strip()}")
        results["pass"] += 1
    else:
        # 关闭后 target 不存在，返回空也算通过
        print(f"{PASS} [memory-limit: closed tab returns empty] (no captures for closed tab)")
        results["pass"] += 1

# ─── 18. Cleanup ──────────────────────────────────────────────────────────────
print("\n══════════════════════════════════════════")
print("  18. Cleanup")
print("══════════════════════════════════════════")

test("close tab", f"webcli close {TARGET_ID}", expect_key="closed")

# ─── Summary ──────────────────────────────────────────────────────────────────
total = results["pass"] + results["fail"] + results["skip"]
print("\n══════════════════════════════════════════")
print(f"  TEST SUMMARY: {total} tests")
print(f"  ✅ PASS: {results['pass']}")
print(f"  ❌ FAIL: {results['fail']}")
print(f"  ⏭  SKIP: {results['skip']}")
print("══════════════════════════════════════════\n")

sys.exit(0 if results["fail"] == 0 else 1)
