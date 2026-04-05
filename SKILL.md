---
name: webcli
license: MIT
github: https://github.com/xxx/webcli
description: 所有联网操作必须通过此 skill 处理，包括：搜索、网页抓取、登录后操作、网络交互等。 触发场景：用户要求搜索信息、查看网页内容、访问需要登录的网站、操作网页界面、抓取数据、爬虫、读取动态渲染页面、以及任何需要真实浏览器环境的网络任务。
metadata:
  author: 新南 
  version: "2.4.2"
---

# webcli Skill

## 前置检查

在开始联网操作前，先检查 CDP 模式可用性：

```bash
check-deps
```

### 浏览器选择策略

> **设计说明**：macOS 用户有"日常 Chrome"（携带登录态），需要区分默认实例和隔离实例；Linux 服务器环境没有日常 Chrome，直接启动一个 headless Chrome 即可，无需区分。

#### Agent 决策规则

**使用已有 Chrome（默认，优先）**，当满足以下任一条件：
- 任务需要登录态、Cookie（如操作社交平台、内部系统）
- 用户未明确要求新开浏览器
- 用户说"帮我搜索"、"打开这个页面"、"操作一下 xxx"等日常任务

**启动隔离 Chrome（仅 macOS，需用户明确要求）**，当满足以下任一条件：
- 用户明确说"开个新浏览器"、"隔离环境"、"不要用我的账号"、"用新的 Chrome"
- 任务需要多账号并行操作（同时操作两个账号）
- 任务需要干净的无 Cookie 环境（如测试未登录状态的页面）

> **原则**：默认连已有 Chrome，不要主动新开浏览器。新开浏览器会丢失用户的登录态，除非用户明确需要隔离。

#### macOS / Windows 桌面环境

**默认行为**：直连用户已有的 Chrome（9222），天然携带登录态和 Cookie，Proxy 自动探测，无需任何配置：

```bash
# 什么都不用做，直接使用
webcli health
webcli new https://example.com
```

**需要隔离环境时**（如"开个新浏览器"、"隔离账号"等），手动启动第二个 Chrome 实例：

**macOS**（GUI 应用启动后自动后台，不会阻塞）：
```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9223 \
  --user-data-dir="/tmp/chrome-9223" \
  --no-first-run --no-default-browser-check
```

**Windows**（需用 `start` 后台启动，否则会阻塞）：
```cmd
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9223 ^
  --user-data-dir="%TEMP%\chrome-9223" ^
  --no-first-run --no-default-browser-check
```

> `--no-first-run` 是关键参数：如果已有 Chrome 在运行，不加此参数命令会被转发给已有实例而不会新开进程。Windows 上 `start ""` 是让 Chrome 在新进程中后台启动的标准方式。

#### Linux 无界面环境（headless 模式）

Linux 服务器没有"日常 Chrome"，无需区分登录态与隔离环境。直接用 **9223** 端口启动唯一的 Chrome，Proxy 自动探测到，`webcli` 无需任何额外端口配置：

```bash
# headless 模式会阻塞前台，必须加 & 后台运行
google-chrome --headless=new --remote-debugging-port=9223 \
  --user-data-dir="/tmp/chrome-9223" \
  --no-first-run &

# Docker 环境（需额外参数）
google-chrome --headless=new --remote-debugging-port=9223 \
  --no-sandbox --disable-dev-shm-usage \
  --user-data-dir="$HOME/.config/google-chrome" \
  --no-first-run &

# 启动后直接使用，无需任何端口配置
webcli health
```

#### 同时保留两个 Chrome 实例（默认 + 隔离并存，仅 macOS）

**适用场景**：需要同时操作两个账号、或同时保留登录态和隔离环境。

**设计说明**：Proxy 是持久后台进程，一个 Proxy 只能连接一个 Chrome。同时操作两个 Chrome 需要启动两个 Proxy 实例，各自监听不同端口：

| 实例        | Chrome 端口 | Proxy 端口 | 操作方式 |
|-----------|------------|-----------|---------|
| 默认 Chrome | 9222 | 3456（默认） | `webcli <cmd>` |
| 隔离 Chrome | 9223 | 3457 | `CDP_PROXY_PORT=3457 webcli <cmd>` |

**启动步骤：**
```bash
# 1. 启动隔离 Chrome（默认 Chrome 保持不动）
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9223 \
  --user-data-dir="/tmp/chrome-9223" \
  --no-first-run --no-default-browser-check

# 2. 启动第二个 Proxy（监听 3457，连接 9223）
# 推荐：直接传参启动（更明确，无需设置环境变量）
python ~/.claude/skills/webcli/browser_cdp/cdp_proxy.py --port 3457 --chrome-port 9223 &
# 或者通过环境变量触发 webcli 自动启动
export CDP_PROXY_PORT=3457
export CDP_CHROME_PORT=9223
webcli health
```

**使用时通过环境变量切换：**
```bash
# 操作默认 Chrome（无需任何前缀）
webcli new https://example.com

# 操作隔离 Chrome（加 CDP_PROXY_PORT=3457 前缀）
CDP_PROXY_PORT=3457 webcli new https://example.com

# 或者 export 后在当前 shell 内统一切换
export CDP_PROXY_PORT=3457
webcli targets
unset CDP_PROXY_PORT   # 恢复默认
```

> **注意**：两个 Proxy 的 targetId 空间是隔离的，不会互相干扰。关闭隔离 Chrome 后，对应 Proxy（3457）会自动断连，不影响默认 Proxy（3456）。

**未通过 check-deps 且用户未要求新开浏览器时**，引导用户在已有 Chrome 中开启 remote-debugging：
- 在 Chrome 地址栏打开 `chrome://inspect/#remote-debugging`，勾选 **"Allow remote debugging for this browser instance"**，可能需要重启浏览器。

检查通过后并必须在回复中向用户直接展示以下须知，再启动 CDP Proxy 执行操作：

```
温馨提示：部分站点对浏览器自动化操作检测严格，存在账号封禁风险。已内置防护措施但无法完全避免，Agent 继续操作即视为接受。
```

## 浏览哲学

**像人一样思考，兼顾高效与适应性的完成任务。**

执行任务时不会过度依赖固有印象所规划的步骤，而是带着目标进入，边看边判断，遇到阻碍就解决，发现内容不够就深入——全程围绕「我要达成什么」做决策。这个 skill 的所有行为都应遵循这个逻辑。

**① 拿到请求** — 先明确用户要做什么，定义成功标准：什么算完成了？需要获取什么信息、执行什么操作、达到什么结果？这是后续所有判断的锚点。

**② 选择起点** — 根据任务性质、平台特征、达成条件，选一个最可能直达的方式作为第一步去验证。一次成功当然最好；不成功则在③中调整。比如，需要操作页面、需要登录态、已知静态方式不可达的平台（小红书、微信公众号等）→ 直接 CDP

**③ 过程校验** — 每一步的结果都是证据，不只是成功或失败的二元信号。用结果对照①的成功标准，更新你对目标的判断：路径在推进吗？结果的整体面貌（质量、相关度、量级）是否指向目标可达？发现方向错了立即调整，不在同一个方式上反复重试——搜索没命中不等于"还没找对方法"，也可能是"目标不存在"；API 报错、页面缺少预期元素、重试无改善，都是在告诉你该重新评估方向。遇到弹窗、登录墙等障碍，判断它是否真的挡住了目标：挡住了就处理，没挡住就绕过——内容可能已在页面 DOM 中，交互只是展示手段。

**④ 完成判断** — 对照定义的任务成功标准，确认任务完成后才停止，但也不要过度操作，不为了"完整"而浪费代价。

## 联网工具选择

- **确保信息的真实性，一手信息优于二手信息**：搜索引擎和聚合平台是信息发现入口。当多次搜索尝试后没有质的改进时，升级到更根本的获取方式：定位一手来源（官网、官方平台、原始页面）。

| 场景 | 工具 |
|------|------|
| 搜索摘要或关键词结果，发现信息来源 | **WebSearch** |
| URL 已知，需要从页面定向提取特定信息 | **WebFetch**（拉取网页内容，由小模型根据 prompt 提取，返回处理后结果） |
| URL 已知，需要原始 HTML 源码（meta、JSON-LD 等结构化字段） | **curl** |
| 非公开内容，或已知静态层无效的平台（小红书、微信公众号等公开内容也被反爬限制） | **浏览器 CDP**（直接，跳过静态层） |
| 需要登录态、交互操作，或需要像人一样在浏览器内自由导航探索 | **浏览器 CDP** |

浏览器 CDP 不要求 URL 已知——可从任意入口出发，通过页面内搜索、点击、跳转等方式找到目标内容。WebSearch、WebFetch、curl 均不处理登录态。

**Jina**（可选预处理层，可与 WebFetch/curl 组合使用，由于其特性可节省 tokens 消耗，请积极在任务合适时组合使用）：第三方网络服务，可将网页转为 Markdown，大幅节省 token 但可能有信息损耗。调用方式为 `r.jina.ai/example.com`（URL 前加前缀，不保留原网址 http 前缀），限 20 RPM。适合文章、博客、文档、PDF 等以正文为核心的页面；对数据面板、商品页等非文章结构页面可能提取到错误区块。

进入浏览器层后，核心工具和策略：

- **了解页面结构**：优先用 `webcli snapshot` 获取无障碍树（含元素角色、文字、可交互性），比 `eval innerHTML` 更结构化，是面对陌生页面的第一步；`webcli eval` 可补充查询具体 DOM 细节。**注意**：SPA 应用（React/Vue 等）的 snapshot 可能大量元素只显示角色名（如 `emphasis`、`button`）而无文字内容，此时应直接用 `webcli eval` 提取数据，snapshot 仅用于了解页面布局框架
- **做**：用 `webcli click` / `webcli find text "xxx" click` 点击元素、`webcli scroll` 滚动加载、`webcli eval` 填表提交——像人一样在页面内自然导航
- **读数据**：优先用 `webcli network-start` + 触发操作 + `webcli network-requests` 直接拿 API 响应 JSON，比解析 DOM 更稳定；DOM 解析用 `webcli eval` 返回 JSON，Agent 直接写入本地文件。**注意：所有 network 命令用连字符 `-`，不是下划线 `_`**（`network-start`、`network-requests`、`network-request`、`network-stop`、`network-clear`）。**⚠️ 时序关键**：`network-start` 必须在页面导航**前**执行，否则无法捕获初始加载的 XHR 请求。正确流程：`new about:blank` → `network-start` → `navigate` → `wait` → `network-requests`
- **读图**：`webcli screenshot` 截图后，用 `read_file` 读取图片路径即可让 Agent 视觉分析，无需额外 OCR
- **批量翻页**：用 `webcli eval` 执行 JS 循环点击分页按钮 + 等待加载 + 提取数据，或直接分析 API 接口批量请求。翻页时优先用 `find role button click --name "页码"` 而非 `find text "页码" click`——后者在页面有多个相同文字时可能命中非预期元素（如 `<title>` 标签）

**SPA 应用数据提取的优先策略**：用 `open-monitored` 一步完成"创建 tab + 启动网络监控 + 导航"，再用 `network-requests --type xhr,fetch` 找到数据接口，直接读 API 响应——比 DOM 解析快且稳定，且不会因时序问题漏掉初始请求。详见 `references/network-analysis.md`。

浏览网页时，**先了解页面结构，再决定下一步动作**。不需要提前规划所有步骤。

### 程序化操作与 GUI 交互

浏览器内操作页面有两种方式：

- **程序化方式**（构造 URL 直接导航、eval 操作 DOM）：成功时速度快、精确，但对网站来说不是正常用户行为，可能触发反爬机制。
- **GUI 交互**（点击按钮、填写输入框、滚动浏览）：GUI 是为人设计的，网站不会限制正常的 UI 操作，确定性最高，但步骤多、速度慢。

根据对目标平台的了解来灵活选择方式。GUI 交互也是程序化方式的有效探测——通过一次真实交互观察站点的实际行为（URL 模式、必需参数、页面跳转逻辑），为后续程序化操作提供依据；同时当程序化方式受阻时，GUI 交互是可靠的兜底。

**站点内交互产生的链接是可靠的**：通过用户视角中的可交互单元（卡片、条目、按钮）进行的站点内交互，自然到达的 URL 天然携带平台所需的完整上下文。而手动构造的 URL 可能缺失隐式必要参数，导致被拦截、返回错误页面、甚至触发反爬。

## 浏览器 CDP 模式

通过 CDP Proxy 直连用户日常 Chrome，天然携带登录态，无需启动独立浏览器。
若无用户明确要求，不主动操作用户已有 tab，所有操作都在自己创建的后台 tab 中进行，保持对用户环境的最小侵入。不关闭用户 tab 的前提下，完成任务后关闭自己创建的 tab，保持环境整洁。

### 安装

skill 安装后，在 skill 目录下执行一次即可：

```bash
pip3 install -e "$CLAUDE_SKILL_DIR"
```

安装后 `webcli` 即可全局使用。

### 启动

```bash
check-deps
```

脚本会依次检查 Chrome 端口，并确保 Proxy 已连接（未运行则自动启动并等待）。Proxy 启动后持续运行。

### CLI 命令参考

所有操作通过 `webcli` 执行，自动管理 Proxy 生命周期。查看完整命令列表：

```bash
webcli --help        # 列出所有命令
webcli <command> --help  # 查看某个命令的详细用法
```

典型操作示例：

```bash
# 列出用户已打开的 tab，获取 targetId
webcli targets

# 新建后台 tab 并等待加载（--id-only 直接输出 targetId，方便 shell 赋值）
TARGET=$(webcli new https://example.com --id-only)

# 执行 JS 读取/操作页面（最常用，可提取数据、操控 DOM、提交表单）
webcli eval $TARGET "document.title"

# 截图（支持相对路径，基于当前目录）
webcli screenshot $TARGET ./shot.png

# 点击元素
webcli click $TARGET "button.submit"

# 关闭 tab
webcli close $TARGET
```

### 页面内导航

两种方式打开页面内的链接：

- **`webcli click`**：在当前 tab 内直接点击用户视角中的可交互单元，简单直接，串行处理。适合需要在同一页面内连续操作的场景，如点击展开、翻页、进入详情等。
- **`webcli new` + 完整 URL**：使用目标链接的完整地址（包含所有URL参数），在新 tab 中打开。适合需要同时访问多个页面的场景。

很多网站的链接包含会话相关的参数（如 token），这些参数是正常访问所必需的。提取 URL 时应保留完整地址，不要裁剪或省略参数。

### 媒体资源提取

判断内容在图片里时，用 `webcli eval` 从 DOM 直接拿图片 URL，再定向读取——比全页截图精准得多。

### 元素定位与点击

`webcli click` 使用标准 CSS 选择器，**不支持** jQuery 风格的 `:contains()` 等非标准伪类。按文字内容定位元素时，优先用语义化命令：

```bash
# 按文字内容点击（推荐，不受 CSS 选择器限制）
webcli find <targetId> text "下一页" click

# 按角色+名称点击
webcli find <targetId> role button click --name "提交"

# 实在需要按文字匹配时，用 eval 执行 JS
webcli eval <targetId> "Array.from(document.querySelectorAll('a')).find(el => el.textContent.includes('下一页'))?.click()"
```

### 等待操作

等待需要明确指定条件，四种方式任选其一：

```bash
webcli wait <targetId> "#submit-btn"          # 等待元素出现且可见
webcli wait <targetId> 2000                   # 等待固定毫秒数
webcli wait <targetId> --text "加载完成"       # 等待页面出现指定文字
webcli wait <targetId> --fn "window.loaded"   # 等待 JS 表达式为真
```

`--timeout` 是可选的超时参数（默认 15000ms），必须配合上述条件之一使用，不能单独使用。

### 技术事实
- 页面中存在大量已加载但未展示的内容——轮播中非当前帧的图片、折叠区块的文字、懒加载占位元素等，它们存在于 DOM 中但对用户不可见。以数据结构（容器、属性、节点关系）为单位思考，可以直接触达这些内容。
- DOM 中存在选择器不可跨越的边界（Shadow DOM 的 `shadowRoot`、iframe 的 `contentDocument`等）。`webcli eval` 递归遍历可一次穿透所有层级，返回带标签的结构化内容，适合快速了解未知页面的完整结构。
- `webcli scroll` 到底部会触发懒加载，使未进入视口的图片完成加载。提取图片 URL 前若未滚动，部分图片可能尚未加载。
- 拿到媒体资源 URL 后，公开资源可直接下载到本地后用读取；需要登录态才可获取的资源才需要在浏览器内 `webcli navigate` + `webcli screenshot`。
- 短时间内密集打开大量页面（如批量 `webcli new`）可能触发网站的反爬风控。
- 平台返回的"内容不存在""页面不见了"等提示不一定反映真实状态，也可能是访问方式的问题（如 URL 缺失必要参数、触发反爬）而非内容本身的问题。
- **SPA 应用（React/Vue 等）的翻页、筛选、Tab 切换等操作不能靠修改 URL 参数触发**——URL 变化不会引起重新渲染。必须点击页面上的分页按钮、筛选控件等 UI 元素，或分析页面发出的 XHR/Fetch 请求直接调用数据接口。

### 视频内容获取

用户 Chrome 真实渲染，截图可捕获当前视频帧。核心能力：通过 `webcli eval` 操控 `<video>` 元素（获取时长、seek 到任意时间点、播放/暂停/全屏），配合 `webcli screenshot` 采帧，可对视频内容进行离散采样分析。

### 登录判断

用户日常 Chrome 天然携带登录态，大多数常用网站已登录。

登录判断的核心问题只有一个：**目标内容拿到了吗？**

打开页面后先尝试获取目标内容。只有当确认**目标内容无法获取**且判断登录能解决时，才告知用户：
> "当前页面在未登录状态下无法获取[具体内容]，请在你的 Chrome 中登录 [网站名]，完成后告诉我继续。"

登录完成后无需重启任何东西，直接刷新页面继续。

### 弹窗与对话框处理

遇到弹窗时，先判断它是否真的挡住了目标内容——没挡住就绕过，挡住了才处理。

**原生对话框（alert / confirm / prompt）**

原生对话框会阻塞页面，必须在触发前通过 `eval` 覆盖，或触发后立即处理：

```bash
# 方案一：提前覆盖，阻止弹出（推荐）
webcli eval <id> "window.alert = () => {}; window.confirm = () => true; window.prompt = () => '';"

# 方案二：触发后通过 CDP 处理（适用于无法提前覆盖的场景）
webcli eval <id> "document.querySelector('#submit-btn').click()"
# 立即处理弹出的对话框
webcli eval <id> "__cdp_handle_dialog__"  # Proxy 内置的对话框处理
```

**自定义 Modal / 弹层**

自定义弹窗本质是 DOM 元素，直接操作：

```bash
# 查看弹窗内容
webcli snapshot <id>

# 点击关闭按钮
webcli find <id> --by text "关闭"  --action click
webcli find <id> --by text "我知道了" --action click

# 直接移除弹窗 DOM（适用于无法点击关闭的情况）
webcli eval <id> "document.querySelector('.modal-overlay')?.remove()"
```

**Cookie 授权 / 隐私弹窗**

常见于欧美网站，直接接受或移除：

```bash
webcli find <id> --by text "Accept" --action click
webcli find <id> --by text "Accept All" --action click
# 或直接移除
webcli eval <id> "document.querySelector('#cookie-banner')?.remove()"
```

**判断原则**：弹窗是否真的阻止了目标内容的获取？如果目标内容已在 DOM 中（只是被遮挡），优先用 `eval` 直接提取，而不是先关弹窗再操作。

### 文件下载场景

浏览器下载文件时，Agent 无法直接访问下载目录。正确做法是**拦截下载 URL**，而不是等待文件下载完成。

**方案一：监听 network 请求拿到下载 URL（推荐）**

```bash
# 1. 开启网络监控
webcli network-start <id>

# 2. 触发下载操作（点击下载按钮）
webcli find <id> --by text "下载" --action click

# 3. 查找下载请求（通常是 GET 请求，Content-Disposition: attachment）
webcli network-requests <id> --filter download
webcli network-requests <id> --filter .xlsx
webcli network-requests <id> --filter .csv

# 4. 拿到 URL 后，用 curl 下载（携带 Cookie）
webcli cookies <id> > /tmp/cookies.txt
curl -b /tmp/cookies.txt -o /tmp/output.xlsx "<download-url>"
```

**方案二：通过 eval 直接构造下载链接**

```bash
# 如果下载 URL 可以从页面 DOM 或 JS 变量中提取
webcli eval <id> "document.querySelector('a[download]')?.href"
webcli eval <id> "window.__downloadUrl__"
```

**注意**：需要登录态的下载资源，必须携带 Cookie 才能下载，不能直接 curl 裸 URL。

### 验证码场景

验证码是 Agent 能力的边界，需要明确区分**能处理**和**需要用户介入**的情况。

**能自动处理的**：
- **Cookie 授权弹窗**（非验证码，直接点击接受）
- **简单数字/字母验证码**：通过 `screenshot` 截图后用视觉能力识别，再 `fill` 填入
- **已有对抗经验的滑块验证码**：查询 `anti-crawl` 经验，按经验执行

```bash
# 截图识别验证码
webcli screenshot <id> /tmp/captcha.png
# 读取图片内容后填入
webcli fill <id> "#captcha-input" "<识别结果>"
```

**需要用户介入的**：
- **短信验证码**：Agent 无法收取短信，必须请用户提供
- **复杂图形验证码**（扭曲、干扰线严重）：截图后无法可靠识别时，请用户手动填写
- **人机验证（reCAPTCHA / hCaptcha）**：无法自动通过，告知用户手动完成

**处理流程**：
```
遇到验证码
  ↓
截图查看类型
  ↓
简单数字/字母 → 截图识别 → 填入
短信验证码    → 告知用户提供验证码 → 用户回复后填入
复杂验证码    → 截图展示给用户 → 请用户手动在 Chrome 中完成 → 用户完成后继续
```

**告知用户的标准话术**：
> "遇到了[验证码类型]，需要你在 Chrome 中手动完成验证，完成后告诉我继续。"

### 多 Tab 协作场景

某些任务需要在多个 Tab 之间切换，例如：Tab A 触发操作后 Tab B 弹出结果、在两个页面之间对比数据、一个 Tab 保持登录态另一个 Tab 执行操作。

**基本模式：多 Tab 并行持有**

```bash
# 创建多个 Tab，分别持有 targetId
TAB_A=$(webcli new https://site-a.com --id-only)
TAB_B=$(webcli new https://site-b.com --id-only)

# 在 Tab A 触发操作
webcli click $TAB_A "#trigger-btn"

# 等待 Tab B 出现预期内容（Tab A 的操作可能导致 Tab B 更新）
webcli wait $TAB_B --text "操作成功"

# 从 Tab B 提取结果
webcli eval $TAB_B "document.querySelector('.result')?.textContent"
```

**Tab 间数据传递**

Tab 之间无法直接通信，但可以通过以下方式间接传递：

```bash
# 方式一：从 Tab A 提取数据，再注入到 Tab B
DATA=$(webcli eval $TAB_A "JSON.stringify(window.__appData__)")
webcli eval $TAB_B "window.__injected__ = $DATA"

# 方式二：通过 URL 参数传递（适用于支持 URL 参数的页面）
webcli navigate $TAB_B "https://site-b.com?id=$(webcli eval $TAB_A 'window.__currentId__')"

# 方式三：通过 Cookie 共享（同域名下）
webcli cookies-set $TAB_B "shared_key" "shared_value" --domain ".site.com"
```

**新 Tab 弹出场景**

某些操作（如点击"在新窗口打开"）会自动创建新 Tab，需要捕获新 Tab 的 targetId：

```bash
# 操作前记录当前 Tab 列表
BEFORE=$(webcli targets --type page)

# 触发可能弹出新 Tab 的操作
webcli click $TAB_A "#open-new-tab-btn"
sleep 1

# 找到新出现的 Tab
webcli targets --type page  # 对比 BEFORE，找到新增的 targetId
```

**注意**：所有子 Agent 共享同一个 Chrome 实例，多 Tab 操作无竞态风险，但要注意 Tab 数量——同时打开过多 Tab 可能触发网站反爬风控。

### Session 失效检测与恢复

长时间任务或跨天任务中，登录态可能失效（Cookie 过期、Session 超时、被踢下线）。

**失效特征识别**：

| 特征 | 说明 |
|------|------|
| 页面跳转到登录页 | URL 变为 `/login`、`/signin` 等 |
| 出现"请重新登录"提示 | 通过 `snapshot` 或 `eval` 检测页面文字 |
| API 返回 401/403 | 通过 `network-requests` 查看响应状态码 |
| 数据接口返回空或错误 | 返回内容与预期不符，且与登录态相关 |

**检测方式**：

```bash
# 方式一：检测页面是否包含登录态标志
webcli eval <id> "!!document.querySelector('.user-avatar')"  # 有头像 = 已登录

# 方式二：检测 URL 是否跳转到登录页
webcli info <id>  # 查看当前 URL

# 方式三：检测特定文字
webcli eval <id> "document.body.innerText.includes('请重新登录')"
```

**恢复策略**：

```
检测到 Session 失效
  ↓
查询 login 经验：webcli exp login {site} main
  ↓
有经验 → 按经验自动重新登录（账号密码方式）
        → 短信/扫码方式 → 告知用户介入
  ↓
无经验 → 告知用户："登录态已失效，请在 Chrome 中重新登录 [网站名]，完成后告诉我继续。"
  ↓
登录完成后 → reload 当前页面 → 继续任务
```

**主动预防**：长时间任务开始前，先验证登录态是否有效，而不是等到任务中途失败再处理。

### 任务结束

用 `webcli close` 关闭自己创建的 tab，必须保留用户原有的 tab 不受影响。

Proxy 持续运行，不建议主动停止——重启后需要在 Chrome 中重新授权 CDP 连接。

## 并行调研：子 Agent 分治策略

任务包含多个**独立**调研目标时（如同时调研 N 个项目、N 个来源），鼓励合理分治给子 Agent 并行执行，而非主 Agent 串行处理。

**好处：**
- **速度**：多子 Agent 并行，总耗时约等于单个子任务时长
- **上下文保护**：抓取内容不进入主 Agent 上下文，主 Agent 只接收摘要，节省 token

**并行 CDP 操作**：每个子 Agent 在当前用户浏览器实例中，自行创建所需的后台 tab（`webcli new`），自行操作，任务结束自行关闭（`webcli close`）。所有子 Agent 共享一个 Chrome、一个 Proxy，通过不同 targetId 操作不同 tab，无竞态风险。

**子 Agent Prompt 写法：目标导向，而非步骤指令**
- 必须在子 Agent prompt 中写 `必须加载 webcli skill 并遵循指引` ，子 Agent 会自动加载 skill，无需在 prompt 中复制 skill 内容或指定路径。
- 子 Agent 有自主判断能力。主 Agent 的职责是说清楚**要什么**，仅在必要与确信时限定**怎么做**。过度指定步骤会剥夺子 Agent 的判断空间，反而引入主 Agent 的假设错误。**避免 prompt 用词对子 Agent 行为的暗示**：「搜索xx」会把子 Agent 锚定到 WebSearch，而实际上有些反爬站点需要 CDP 直接访问主站才能有效获取内容。主 Agent 写 prompt 时应描述目标（「获取」「调研」「了解」），避免用暗示具体手段的动词（「搜索」「抓取」「爬取」）。

**分治判断标准：**

| 适合分治 | 不适合分治 |
|----------|-----------|
| 目标相互独立，结果互不依赖 | 目标有依赖关系，下一个需要上一个的结果 |
| 每个子任务量足够大（多页抓取、多轮搜索） | 简单单页查询，分治开销大于收益 |
| 需要 CDP 浏览器或长时间运行的任务 | 几次 WebSearch / Jina 就能完成的轻量查询 |

## 信息核实类任务

核实的目标是**一手来源**，而非更多的二手报道。多个媒体引用同一个错误会造成循环印证假象。

搜索引擎和聚合平台是信息发现入口，是**定位**信息的工具，不可用于直接**证明**真伪。找到来源后，直接访问读取原文。同一原则适用于工具能力/用法的调研——官方文档是一手来源，不确定时先查文档或源码，不猜测。

| 信息类型 | 一手来源 |
|----------|---------|
| 政策/法规 | 发布机构官网 |
| 企业公告 | 公司官方新闻页 |
| 学术声明 | 原始论文/机构官网 |
| 工具能力/用法 | 官方文档、源码 |

**找不到官网时**：权威媒体的原创报道（非转载）可作为次级依据，但需向用户说明："未找到官方原文，以下核实来自[媒体名]报道，存在转述误差可能。"单一来源时同样向用户声明。

## 站点经验

操作中积累的特定网站经验，按域名存储在 `references/site-patterns/` 下。

已有经验的站点：!`ls "${CLAUDE_SKILL_DIR:-\.}/references/site-patterns/" 2>/dev/null | grep '\.md$' | sed 's/\.md$//' | tr '\n' ',' | sed 's/,$//' || echo '暂无'`

确定目标网站后，执行 `match-site <domain或网站名>` 自动匹配并输出对应经验内容，无需手动查找文件路径。如果上方列表中有匹配的站点，必须读取对应文件获取先验知识（平台特征、有效模式、已知陷阱）。经验内容标注了发现日期，当作可能有效的提示而非保证——如果按经验操作失败，回退通用模式并更新经验文件。

CDP 操作成功完成后，如果发现了有必要记录经验的新站点或新模式（URL 结构、平台特征、操作策略），主动写入对应的站点经验文件。只写经过验证的事实，不写未确认的猜测。

文件格式：
```markdown
---
domain: example.com
aliases: [示例, Example]
updated: 2026-03-19
---
## 平台特征
架构、反爬行为、登录需求、内容加载方式等事实

## 有效模式
已验证的 URL 模式、操作策略、选择器

## 已知陷阱
什么会失败以及为什么

## 数据来源说明
- **渲染方式**: SSR 直出 / JS 异步 / SSR + JS 混合 / 必须浏览器
- **验证结论**: 验证了什么、如何验证的、验证结果
```
经验/陷阱内容标注发现日期。对于标注 `status: verified` 的经验，**作为默认可信的事实直接执行，不做额外验证**。仅当执行结果与经验明确不符时，才回退通用模式并更新经验文件。对于未标注 verified 或标注 `unstable` 的经验，当作"可能有效的提示"使用。

## References 索引

| 文件 | 何时加载 |
|------|---------|
| `references/cdp-api.md` | 需要 CDP API 详细参考、JS 提取模式、错误处理时 |
| `references/network-analysis.md` | 需要分析页面接口、抓包、查看请求参数/响应数据、研究加密参数时 |
| `references/site-patterns/{domain}.md` | 确定目标网站后，读取对应站点经验 |
| `references/experience.md` | 需要了解经验沉淀规范、格式要求、CLI 使用方式时 |

## 经验自主沉淀（webcli exp）

> `webcli exp` 是**纯本地文件操作**，不依赖 CDP Proxy，随时可用，无需启动浏览器。

### 经验存储位置

所有经验统一存储在用户目录下，**与 agent 平台无关**，Claude、Cursor、Windsurf 等任何 agent 都共享同一份经验库：

```
~/.agents/skills/webcli/experience/
├── sites/
│   └── {domain}/
│       ├── api/        # 接口数据获取经验
│       ├── login/      # 自动化登录经验
│       └── action/     # 自动化操作经验
└── anti-crawl/         # 反爬对抗经验（跨站点）
```

> 如需自定义路径，设置环境变量 `WEB_CLI_EXPERIENCE_DIR=/your/path`。

### 任务开始前：查询已有经验

确定目标站点后，**必须先查询**是否有已有经验可复用：

```bash
# 查看该站点是否有经验
webcli exp list yiche.com

# 如果有，先读取经验再开始任务
webcli exp api yiche.com rank
```

### 任务完成后：自动沉淀经验

以下场景**必须自动沉淀**，无需用户指令：

| 触发场景 | 分类 | 命令 |
|----------|------|------|
| 通过抓包发现并验证了数据接口 | `api` | `webcli exp save api {site} {name}` |
| 完成了自动化登录流程 | `login` | `webcli exp save login {site} main` |
| 完成了复杂页面操作流程 | `action` | `webcli exp save action {site} {name}` |
| 遭遇并突破了反爬机制 | `anti-crawl` | `webcli exp save anti-crawl - {type}` |
| 完成了跨站点/多步骤的任务流程 | `workflow` | `webcli exp save workflow - {task-name}` |

#### action vs workflow 如何选择？

- **"在某个站点上做一件事"** → `action`（绑定单一站点，作为 workflow 的组成步骤）
- **"为完成某个目标，跨多个系统做多件事"** → `workflow`（不绑定站点，作为完整任务直接执行）

> **边界情况**：操作只涉及单一站点时，即使步骤较多，也优先存 `action`。只有任务**必须跨站点**，或任务目标本身就是用户说的"那件事"时，才存 `workflow`。

### 沉淀方式

```bash
# 从 stdin 写入经验（Agent 自动沉淀时使用）
cat << 'EOF' | webcli exp save api yiche.com rank
# 易车销量榜接口

## 接口信息
- **URL**: `https://...`
...
EOF

# 追加内容到已有经验
echo "## 补充说明..." | webcli exp save api yiche.com rank --append
```

### 完整命令参考

```bash
# ── 列出经验 ──────────────────────────────────────────────
webcli exp list                          # 列出所有经验
webcli exp list yiche.com                # 列出某站点经验

# ── 站点级经验（api / login / action）────────────────────
webcli exp api yiche.com rank            # 查看接口经验（快捷方式）
webcli exp login taobao.com main         # 查看登录经验（快捷方式）
webcli exp action xiaohongshu.com post   # 查看操作经验（快捷方式）
webcli exp show api yiche.com rank       # 查看经验（完整格式）
webcli exp save api yiche.com rank       # 从 stdin 保存站点级经验
webcli exp edit api yiche.com rank       # 用编辑器打开经验文件

# ── 全局经验（anti-crawl / workflow）─────────────────────
webcli exp anti-crawl cloudflare         # 查看反爬经验（快捷方式）
webcli exp workflow query-sls-log        # 查看流程经验（快捷方式）
webcli exp show workflow - deploy-ude    # 查看流程经验（完整格式，site 用 - 占位）
webcli exp save workflow - deploy-ude    # 从 stdin 保存流程经验
webcli exp edit workflow - query-sls-log # 用编辑器打开流程经验文件
```

> 详细格式规范见 `references/experience.md` 的「webcli 场景经验分类」章节。