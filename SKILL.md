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


**启动隔离 Chrome（仅 macOS，需用户明确要求）**：用户说"开个新浏览器"/"隔离环境"/"不要用我的账号"，或需要多账号并行/无 Cookie 环境。

> 默认连已有 Chrome，不要主动新开浏览器——新开会丢失登录态。

#### macOS / Windows 桌面环境

**默认行为**：直连用户已有的 Chrome（9222），天然携带登录态和 Cookie，Proxy 自动探测，无需任何配置：

```bash
# 什么都不用做，直接使用
webcli health
webcli new https://example.com
```

**需要隔离环境时**，手动启动第二个 Chrome 实例：

```bash
# macOS（GUI 自动后台，不阻塞）
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9223 --user-data-dir="/tmp/chrome-9223" \
  --no-first-run --no-default-browser-check

# Windows（需用 start 后台启动，否则阻塞）
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9223 --user-data-dir="%TEMP%\chrome-9223" ^
  --no-first-run --no-default-browser-check
```

> `--no-first-run`：已有 Chrome 运行时不加此参数会被转发给已有实例而不新开进程。

#### Linux 无界面环境（headless 模式）

直接用 **9223** 端口启动 Chrome，Proxy 自动探测，无需额外配置：

```bash
# 普通 headless（必须加 & 后台运行）
google-chrome --headless=new --remote-debugging-port=9223 \
  --user-data-dir="/tmp/chrome-9223" --no-first-run &

# Docker 环境（需额外参数）
google-chrome --headless=new --remote-debugging-port=9223 \
  --no-sandbox --disable-dev-shm-usage \
  --user-data-dir="$HOME/.config/google-chrome" --no-first-run &
```

#### 同时保留两个 Chrome 实例（默认 + 隔离并存，仅 macOS）

一个 Proxy 只能连接一个 Chrome，同时操作两个 Chrome 需启动两个 Proxy 实例：

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
python ~/.claude/skills/webcli/browser_cdp/cdp_proxy.py --port 3457 --chrome-port 9223 &
```

**使用时通过环境变量切换：**
```bash
webcli new https://example.com                        # 操作默认 Chrome
CDP_PROXY_PORT=3457 webcli new https://example.com    # 操作隔离 Chrome
```

> 两个 Proxy 的 targetId 空间隔离，不会互相干扰。

**未通过 check-deps 且用户未要求新开浏览器时**，引导用户在已有 Chrome 中开启 remote-debugging：
- 在 Chrome 地址栏打开 `chrome://inspect/#remote-debugging`，勾选 **"Allow remote debugging for this browser instance"**，可能需要重启浏览器。

检查通过后并必须在回复中向用户直接展示以下须知，再启动 CDP Proxy 执行操作：

```
温馨提示：部分站点对浏览器自动化操作检测严格，存在账号封禁风险。已内置防护措施但无法完全避免，Agent 继续操作即视为接受。
```

## 工作流执行协议（⛔ 强制）

> **核心原则：联网操作是多阶段任务，check-deps、用户警告披露、执行、tab清理、经验沉淀每一步都不可跳过。**

### 第一步：初始化 TodoList（加载 Skill 后立即执行）

场景类型确定后，**必须立即调用 TodoWrite 工具**，将对应场景的阶段映射为待办清单。

**通用联网操作 TodoList 模板：**
```
1. [ ] 前置检查 — check-deps 确认 CDP 环境可用
2. [ ] 用户告知 — 展示账号封禁风险提示
3. [ ] 任务执行 — 按目标操作（导航/抓包/交互/数据提取）
4. [ ] 清理收尾 — 关闭自己创建的 tab，不影响用户原有 tab
5. [ ] 经验沉淀 — 如有新发现（API/反爬/登录/操作），写入经验库
```

**数据抓取场景 TodoList 模板：**
```
1. [ ] 前置检查 — check-deps 确认 CDP 环境可用
2. [ ] 用户告知 — 展示账号封禁风险提示
3. [ ] 检查站点经验 — webcli exp list {domain}，有则直接复用
4. [ ] 页面分析 — open-monitored / network-start 监控接口
5. [ ] 数据提取 — 优先 API 直接调用，其次 DOM 提取
6. [ ] 清理收尾 — 关闭 tab
7. [ ] 经验沉淀 — 发现新接口或突破反爬，必须写入经验库
```

> 每完成一个阶段必须更新状态，不得跳过任何步骤。

### 第二步：门禁规则

| 门禁点 | 前置条件 | 放行标准 | 典型违规 |
|--------|----------|----------|----------|
| **检查→执行** | check-deps 通过 或 已引导用户开启 | CDP Proxy 可用 | 未检查 check-deps 就执行 webcli 命令 |
| **检查→用户告知** | 检查通过 | ⛔ 风险提示已展示给用户 | 直接开始操作，不告知封禁风险 |
| **执行→清理** | 任务目标达成 | 自己创建的 tab 已关闭 | 任务完成但不关 tab |
| **清理→完成** | tab 已关闭 | ⛔ 经验沉淀检查已执行 | 发现了新接口但不沉淀经验 |

### 第三步：经验沉淀（任务结束的必经步骤）

任务完成后**不得直接结束**。必须执行经验沉淀检查：

```
任务目标达成
 ↓
判断是否需要沉淀：
 ├── 通过 network 发现并验证了新的数据 API → ⛔ 必须沉淀 api 经验
 ├── 遭遇并突破了反爬机制 → ⛔ 必须沉淀 anti-crawl 经验
 ├── 完成了自动化登录流程 → ⛔ 必须沉淀 login 经验
 ├── 完成了复杂的页面交互操作 → 建议沉淀 action 经验
 └── 纯复用已有经验，无新发现 → 可跳过
 ↓
加载 webcli 完整经验规范（references/experience.md）
 ↓
按对应模板撰写经验（API 经验必须含可运行代码）
 ↓
写入经验库（webcli exp save 或文件写入）
 ↓
TodoList 标记「经验沉淀」为 completed
 ↓
关闭自己创建的 tab（如果还没关）
 ↓
任务正式结束
```

## 浏览哲学

**像人一样思考，带着目标进入，边看边判断，遇到阻碍就解决——全程围绕「我要达成什么」做决策。**

**① 拿到请求** — 定义成功标准：什么算完成了？这是后续所有判断的锚点。

**② 选择起点** — 选最可能直达的方式验证。需要登录态/操作页面/已知静态层无效的平台（小红书、微信公众号等）→ 直接 CDP。

**③ 过程校验** — 每步结果都是证据。发现方向错了立即调整，不在同一方式上反复重试。遇到弹窗/登录墙，判断是否真的挡住目标——挡住才处理，没挡住就绕过。

**④ 完成判断** — 对照成功标准确认完成后停止，不为"完整"而过度操作。

## 联网工具选择

一手信息优于二手信息。搜索引擎是信息发现入口，多次搜索无质的改进时，直接定位一手来源（官网、原始页面）。

| 场景 | 工具 |
|------|------|
| 搜索摘要/关键词，发现信息来源 | **WebSearch** |
| URL 已知，定向提取特定信息 | **WebFetch** |
| URL 已知，需要原始 HTML 源码 | **curl** |
| 非公开内容/静态层无效的平台（小红书、微信公众号等） | **浏览器 CDP** |
| 需要登录态、交互操作、自由导航探索 | **浏览器 CDP** |

浏览器 CDP 不要求 URL 已知，可从任意入口出发。WebSearch/WebFetch/curl 均不处理登录态。

**Jina**（可选，节省 token）：`r.jina.ai/example.com`，将网页转为 Markdown，限 20 RPM。适合文章/博客/文档；对数据面板、商品页等非文章结构页面可能提取错误区块。

进入浏览器层后，核心策略：

- **了解页面结构**：优先 `webcli snapshot` 获取无障碍树；SPA 应用 snapshot 元素可能无文字内容，此时直接用 `webcli eval` 提取数据
- **交互操作**：`webcli click` / `webcli find text "xxx" click` 点击、`webcli scroll` 滚动、`webcli eval` 填表提交
- **读数据**：优先 `network-start` + 触发操作 + `network-requests` 拿 API 响应 JSON，比解析 DOM 更稳定。**注意：network 命令用连字符 `-` 不是下划线 `_`**。**⚠️ 时序关键**：`network-start` 必须在页面导航**前**执行。正确流程：`new about:blank` → `network-start` → `navigate` → `wait` → `network-requests`
- **读图**：`webcli screenshot` 截图后，`read_file` 读取图片路径即可视觉分析
- **批量翻页**：翻页优先用 `find role button click --name "页码"` 而非 `find text "页码" click`——后者可能命中非预期元素

**SPA 数据提取**：用 `open-monitored` 一步完成"创建 tab + 启动网络监控 + 导航"，再用 `network-requests --type xhr,fetch` 找数据接口。详见 `references/network-analysis.md`。

### 程序化操作与 GUI 交互

- **程序化方式**（构造 URL、eval 操作 DOM）：速度快，但可能触发反爬
- **GUI 交互**（点击按钮、填写输入框）：确定性最高，是程序化受阻时的兜底，也是观察站点实际行为的有效探测手段

**站点内交互产生的链接天然携带完整上下文**，手动构造的 URL 可能缺失隐式参数导致被拦截。

## 浏览器 CDP 模式

通过 CDP Proxy 直连用户日常 Chrome，天然携带登录态。所有操作在自己创建的后台 tab 中进行，完成后关闭，不影响用户已有 tab。

### 安装与启动

```bash
pip3 install -e "$CLAUDE_SKILL_DIR"  # 安装一次即可
check-deps                            # 检查 Chrome 端口，自动启动 Proxy
```

### CLI 命令参考

```bash
webcli --help / webcli <command> --help   # 查看命令列表/详细用法

webcli targets                            # 列出已打开的 tab
TARGET=$(webcli new https://example.com --id-only)  # 新建 tab
webcli eval $TARGET "document.title"      # 执行 JS（最常用）
webcli screenshot $TARGET ./shot.png      # 截图
webcli click $TARGET "button.submit"      # 点击元素
webcli close $TARGET                      # 关闭 tab
```

### 动态 JS 源码获取

用于破解加密接口、分析混淆代码——获取浏览器运行时已加载的所有 JS 脚本源码（包括动态 `import()` 加载的模块）。

```bash
# 第一步：开启脚本捕获（必须在页面加载前或加载时执行）
webcli scripts-enable $TARGET

# 第二步：导航到目标页面（触发脚本加载）
webcli navigate $TARGET https://example.com

# 第三步：列出所有已加载的脚本
webcli scripts-list $TARGET

# 按 URL 关键词过滤（找加密相关的 chunk）
webcli scripts-list $TARGET --filter encrypt
webcli scripts-list $TARGET --filter chunk

# 第四步：获取指定脚本的完整源码
webcli scripts-source $TARGET <scriptId>

# 保存到文件（推荐，源码通常很大）
webcli scripts-source $TARGET <scriptId> -o decrypt.js
```

**典型破解流程**：
```bash
TARGET=$(webcli new about:blank --id-only)
webcli scripts-enable $TARGET          # 先开启捕获
webcli navigate $TARGET https://target.com  # 再导航
webcli scripts-list $TARGET --filter sign   # 找签名/加密相关脚本
webcli scripts-source $TARGET <scriptId> -o sign.js  # 导出源码分析
webcli close $TARGET
```

### 页面内导航

- **`webcli click`**：当前 tab 内点击，适合连续操作（展开、翻页、进入详情）
- **`webcli new` + 完整 URL**：新 tab 打开，适合同时访问多个页面

提取 URL 时保留完整地址，不要裁剪参数（很多网站链接含会话 token）。

### 媒体资源提取

用 `webcli eval` 从 DOM 直接拿图片 URL，比全页截图精准得多。

### 元素定位与点击

`webcli click` 使用标准 CSS 选择器，**不支持** `:contains()` 等 jQuery 非标准伪类。按文字定位时优先用语义化命令：

```bash
webcli find <targetId> text "下一页" click          # 按文字点击（推荐）
webcli find <targetId> role button click --name "提交"  # 按角色+名称
webcli eval <targetId> "Array.from(document.querySelectorAll('a')).find(el => el.textContent.includes('下一页'))?.click()"  # JS 兜底
```

### 等待操作

```bash
webcli wait <targetId> "#submit-btn"        # 等待元素出现且可见
webcli wait <targetId> 2000                 # 等待固定毫秒数
webcli wait <targetId> --text "加载完成"    # 等待指定文字
webcli wait <targetId> --fn "window.loaded" # 等待 JS 表达式为真
```

`--timeout`（默认 15000ms）必须配合上述条件之一使用，不能单独使用。

### 技术事实

- 轮播非当前帧、折叠区块、懒加载占位元素等已加载但不可见的内容存在于 DOM 中，以数据结构为单位思考可直接触达
- Shadow DOM / iframe 是选择器边界，`webcli eval` 递归遍历可一次穿透所有层级
- `webcli scroll` 到底部触发懒加载，提取图片 URL 前若未滚动，部分图片可能尚未加载
- 公开媒体资源可直接下载；需要登录态的资源才需要在浏览器内 `navigate` + `screenshot`
- 密集批量 `webcli new` 可能触发反爬风控
- 平台返回"内容不存在"不一定是真实状态，也可能是 URL 缺参数或触发了反爬
- **SPA（React/Vue 等）翻页/筛选/Tab 切换不能靠修改 URL 参数触发**，必须点击 UI 元素或直接调用数据接口

### 视频内容获取

`webcli eval` 操控 `<video>` 元素（获取时长、seek、播放/暂停），配合 `webcli screenshot` 采帧，可对视频内容进行离散采样分析。

### 登录判断

Chrome 天然携带登录态，大多数常用网站已登录。核心问题只有一个：**目标内容拿到了吗？**

只有确认目标内容无法获取且登录能解决时，才告知用户：
> "当前页面在未登录状态下无法获取[具体内容]，请在你的 Chrome 中登录 [网站名]，完成后告诉我继续。"

登录完成后直接刷新页面继续，无需重启任何东西。

### 弹窗与对话框处理

先判断弹窗是否真的挡住了目标内容——没挡住就绕过（目标内容可能已在 DOM 中），挡住了才处理。

**原生对话框（alert / confirm / prompt）**

```bash
# 提前覆盖（推荐）
webcli eval <id> "window.alert = () => {}; window.confirm = () => true; window.prompt = () => '';"
# 触发后处理
webcli eval <id> "__cdp_handle_dialog__"
```

**自定义 Modal / Cookie 弹窗**

```bash
webcli find <id> --by text "关闭" --action click
webcli find <id> --by text "Accept All" --action click
webcli eval <id> "document.querySelector('.modal-overlay')?.remove()"  # 直接移除
```

### 文件下载场景

Agent 无法直接访问下载目录，正确做法是**拦截下载 URL**。

**方案一：监听 network 请求（推荐）**

```bash
webcli network-start <id>
webcli find <id> --by text "下载" --action click          # 触发下载
webcli network-requests <id> --filter .xlsx               # 找到下载请求
webcli cookies <id> > /tmp/cookies.txt
curl -b /tmp/cookies.txt -o /tmp/output.xlsx "<download-url>"
```

**方案二：eval 直接提取链接**

```bash
webcli eval <id> "document.querySelector('a[download]')?.href"
webcli eval <id> "window.__downloadUrl__"
```

需要登录态的资源必须携带 Cookie，不能直接 curl 裸 URL。

### 验证码场景

**能自动处理**：简单数字/字母验证码（截图识别后 `fill` 填入）、已有对抗经验的滑块验证码（查询 `anti-crawl` 经验执行）。

**需要用户介入**：短信验证码、复杂图形验证码、reCAPTCHA / hCaptcha。

话术：> "遇到了[验证码类型]，需要你在 Chrome 中手动完成验证，完成后告诉我继续。"

### 多 Tab 协作场景

```bash
TAB_A=$(webcli new https://site-a.com --id-only)
TAB_B=$(webcli new https://site-b.com --id-only)
webcli click $TAB_A "#trigger-btn"
webcli wait $TAB_B --text "操作成功"
webcli eval $TAB_B "document.querySelector('.result')?.textContent"
```

**Tab 间数据传递**（无法直接通信，间接传递）：

```bash
DATA=$(webcli eval $TAB_A "JSON.stringify(window.__appData__)")
webcli eval $TAB_B "window.__injected__ = $DATA"                              # 注入数据
webcli navigate $TAB_B "https://site-b.com?id=$(webcli eval $TAB_A 'window.__currentId__')"  # URL 参数
webcli cookies-set $TAB_B "shared_key" "shared_value" --domain ".site.com"   # Cookie 共享（同域）
```

**新 Tab 弹出**：操作前 `BEFORE=$(webcli targets --type page)`，操作后对比找到新增的 targetId。

所有子 Agent 共享同一 Chrome 实例，多 Tab 无竞态风险，但过多 Tab 可能触发反爬。

### Session 失效检测与恢复

**失效特征**：URL 跳转到 `/login`、出现"请重新登录"提示、API 返回 401/403。

**检测**：
```bash
webcli eval <id> "!!document.querySelector('.user-avatar')"       # 有头像 = 已登录
webcli eval <id> "document.body.innerText.includes('请重新登录')"  # 检测文字
webcli info <id>                                                   # 查看当前 URL
```

**恢复**：查询 `webcli exp login {site} main` → 有经验则自动重登（短信/扫码方式需用户介入）→ 无经验则告知用户重新登录 → 登录完成后 reload 继续。

**主动预防**：长时间任务开始前先验证登录态，不要等到中途失败再处理。

### 任务结束

用 `webcli close` 关闭自己创建的 tab，必须保留用户原有的 tab 不受影响。

Proxy 持续运行，不建议主动停止——重启后需要在 Chrome 中重新授权 CDP 连接。

## 并行调研：子 Agent 分治策略

多个**独立**调研目标时，分治给子 Agent 并行执行（速度快、保护主 Agent 上下文）。每个子 Agent 自行 `webcli new` 创建 tab、操作、`webcli close` 关闭，共享同一 Chrome/Proxy，无竞态风险。

**子 Agent Prompt 写法**：
- 写 `必须加载 webcli skill 并遵循指引`，子 Agent 会自动加载
- 描述**目标**（「获取」「调研」「了解」），避免暗示手段的动词（「搜索」「抓取」「爬取」）——「搜索xx」会把子 Agent 锚定到 WebSearch，而反爬站点需要 CDP 直接访问

**分治判断**：

| 适合分治 | 不适合分治 |
|----------|-----------|
| 目标独立，结果互不依赖 | 目标有依赖关系 |
| 每个子任务量足够大（多页抓取） | 简单单页查询，分治开销大于收益 |
| 需要 CDP 或长时间运行 | 几次 WebSearch / Jina 就能完成 |

## 信息核实类任务

核实目标是**一手来源**。搜索引擎是定位工具，不能用于直接证明真伪，找到来源后直接访问原文。

| 信息类型 | 一手来源 |
|----------|---------|
| 政策/法规 | 发布机构官网 |
| 企业公告 | 公司官方新闻页 |
| 学术声明 | 原始论文/机构官网 |
| 工具能力/用法 | 官方文档、源码 |

找不到官网时，权威媒体原创报道可作次级依据，需向用户说明来源和转述误差可能。

## 站点经验

已有经验的站点：!`ls "${CLAUDE_SKILL_DIR:-\.}/references/site-patterns/" 2>/dev/null | grep '\.md$' | sed 's/\.md$//' | tr '\n' ',' | sed 's/,$//' || echo '暂无'`

确定目标网站后，执行 `match-site <domain或网站名>` 自动匹配经验内容。列表中有匹配站点时**必须读取**，获取平台特征、有效模式、已知陷阱。CDP 操作完成后，如发现值得记录的新站点/新模式，主动写入经验文件（只写验证过的事实）。

文件格式：
```markdown
---
domain: example.com
aliases: [示例, Example]
updated: 2026-03-19
---
## 平台特征
## 有效模式
## 已知陷阱
## 数据来源说明
- **渲染方式**: SSR 直出 / JS 异步 / SSR + JS 混合 / 必须浏览器
- **验证结论**: 验证了什么、如何验证的、验证结果
```

`status: verified` 的经验直接执行，不做额外验证；未标注或 `unstable` 的当作"可能有效的提示"。

## References 索引

| 文件 | 何时加载 |
|------|---------|
| `references/cdp-api.md` | 需要 CDP API 详细参考、JS 提取模式、错误处理时 |
| `references/network-analysis.md` | 需要分析页面接口、抓包、查看请求参数/响应数据、研究加密参数时 |
| `references/site-patterns/{domain}.md` | 确定目标网站后，读取对应站点经验 |
| `references/experience.md` | 需要了解经验沉淀规范、格式要求、CLI 使用方式时 |

## 经验自主沉淀（webcli exp）

> 纯本地文件操作，不依赖 CDP Proxy，随时可用。所有 agent（Claude/Cursor/Windsurf）共享同一份经验库。

经验存储在 `~/.agents/skills/webcli/experience/`（可用 `WEB_CLI_EXPERIENCE_DIR` 自定义）：
- `sites/{domain}/api/` `login/` `action/`
- `anti-crawl/`（跨站点反爬经验）

### 任务开始前：查询已有经验

```bash
webcli exp list yiche.com      # 查看站点经验列表
webcli exp api yiche.com rank  # 读取具体经验
```

### 任务完成后：必须自动沉淀

| 触发场景 | 命令 |
|----------|------|
| 验证了数据接口 | `webcli exp save api {site} {name}` |
| 完成自动化登录 | `webcli exp save login {site} main` |
| 完成复杂页面操作 | `webcli exp save action {site} {name}` |
| 突破反爬机制 | `webcli exp save anti-crawl - {type}` |
| 跨站点/多步骤流程 | `webcli exp save workflow - {task-name}` |

**action vs workflow**：单一站点上的操作 → `action`；必须跨站点或任务本身就是用户说的"那件事" → `workflow`。

### 沉淀方式

```bash
cat << 'EOF' | webcli exp save api yiche.com rank
# 接口信息...
EOF
echo "## 补充..." | webcli exp save api yiche.com rank --append
```

**更新已有经验时**，必须在文件末尾追加一条变更记录，简要说明本次更新了什么：

```bash
echo "## 变更记录
- $(date +%Y-%m-%d)：补充了分页接口参数说明" | webcli exp save api yiche.com rank --append
```

### 命令参考

```bash
webcli exp list / webcli exp list yiche.com          # 列出经验
webcli exp api yiche.com rank                        # 查看接口经验
webcli exp login taobao.com main                     # 查看登录经验
webcli exp action xiaohongshu.com post               # 查看操作经验
webcli exp anti-crawl cloudflare                     # 查看反爬经验
webcli exp workflow query-sls-log                    # 查看流程经验
webcli exp show api yiche.com rank                   # 查看（完整格式）
webcli exp save api yiche.com rank                   # 从 stdin 保存
webcli exp edit api yiche.com rank                   # 用编辑器打开
webcli exp rm api yiche.com rank                     # 删除经验（有确认提示）
webcli exp rm api yiche.com rank --yes               # 跳过确认直接删除
webcli exp save workflow - deploy-ude                # 全局经验（site 用 - 占位）
```

> 详细格式规范见 `references/experience.md`。