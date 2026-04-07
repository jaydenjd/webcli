# webcli — 给 AI Agent 的浏览器操作 Skill

让 AI Agent 直连你的 Chrome，完成搜索、抓数据、自动化操作等一切联网任务。

---

## 这是什么

Agent 原生有 WebSearch、WebFetch，但面对需要登录态、动态渲染、页面交互的场景就无能为力了。这个 skill 补上的是：**联网决策 + CDP 浏览器操作 + 站点经验积累**。

- **联网决策**：什么场景用 WebSearch、WebFetch、curl、还是浏览器 CDP，有明确决策规则，Agent 自动选择最优路径
- **CDP 浏览器操作**：直连你日常用的 Chrome，天然携带登录态和 Cookie，支持点击、填表、抓包、截图等完整交互
- **站点经验积累**：每次完成任务后自动沉淀经验，下次同类任务直接复用，越用越快

> 本项目借鉴了 [eze-is/web-access](https://github.com/eze-is/web-access) 的核心思路，在此基础上做了以下改进：
>
> - **Python 实现，专用 CLI**：原项目用 Node.js + HTTP API（`curl localhost:3456/new?url=...`），本项目改为 Python 实现，提供 `webcli` 命令行工具，命令更自然、可读性更强
> - **结构化经验管理**：原项目经验以 Markdown 文件存储，本项目新增 `webcli exp` 专用命令，支持按类型（api/login/action/anti-crawl）分类存储和查询，经验复用更精准
> - **更丰富的命令集**：新增 `open-monitored`（一步开启网络监控）、`find`（按文字/角色定位元素）、`wait`（等待条件）、`scripts-*`（JS 源码捕获）等命令，覆盖更多自动化场景
> - **无环境变量依赖**：原项目依赖 `$CLAUDE_SKILL_DIR` 环境变量，本项目通过 `pip install -e .` 安装后直接使用，环境更简单

---

## 安装

```bash
# 安装skill 
npx skills add https://github.com/jaydenjd/webcli.git -g -y

# 克隆项目；如果只是开发，可以 clone 到其他目录也可
git clone https://github.com/jaydenjd/webcli ~/.claude/skills/webcli
cd ~/.claude/skills/webcli
pip3 install -e .
```

> **注意**：`pip3 install -e .` 是必须执行的步骤，否则 `webcli` 命令不可用。

**更新**：拉取最新代码后重新安装即可；如果修改了 `cdp_proxy.py`，需要重启 Proxy：

```bash
pkill -f "cdp_proxy"   # kill 后执行任意 webcli 命令会自动重新拉起
```

**让 Agent 加载这个 skill**：安装完成后，在对话里告诉 Agent：

```
请加载 ~/.claude/skills/webcli/SKILL.md 并按照其中的指引完成任务
```

## Chrome 配置

> macOS / Windows 用户直连日常 Chrome（携带登录态和 Cookie），一次性配置即可；Linux 服务器需手动启动 headless Chrome，流程更简单。

### macOS / Windows 桌面环境

Chrome 需要开启远程调试（一次性配置）：

1. Chrome 地址栏打开 `chrome://inspect/#remote-debugging`
2. 勾选 **Allow remote debugging for this browser instance**（可能需要重启浏览器）

配置完成后，Proxy 自动探测到已有 Chrome（9222），直接使用：

```bash
webcli health
```

**需要隔离环境时**（操作不同账号、不带登录态），手动启动第二个 Chrome：

```bash
# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9223 \
  --user-data-dir="/tmp/chrome" \
  --no-first-run --no-default-browser-check
  
# Windows
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
--remote-debugging-port=9223 ^
--user-data-dir="%TEMP%\chrome" ^
--no-first-run --no-default-browser-check 

# Linux
google-chrome --headless=new --remote-debugging-port=9223 \
  --user-data-dir=/tmp/chrome-9223 --no-first-run &
```


```bash
# 启动第二个 Proxy 连接隔离 Chrome
python browser_cdp/cdp_proxy.py --port 3457 --chrome-port 9223 &

# 操作隔离 Chrome 时加端口前缀
CDP_PROXY_PORT=3457 webcli new https://example.com
```


| | macOS 默认 | macOS 隔离实例 | Linux |
|--|-----------|--------------|-------|
| Chrome 端口 | 9222（已有） | 9223（手动启动） | 9223（手动启动） |
| Proxy 端口 | 3456（默认） | 3457（手动启动） | 3456（默认） |
| `webcli` 使用 | 直接用 | `CDP_PROXY_PORT=3457 webcli` | 直接用 |

环境检查（Agent 运行时会自动完成前置检查，无需手动执行）：

```bash
check-deps
```

## webcli 常用命令

Proxy 通过 WebSocket 直连 Chrome，Agent 会自动管理生命周期，无需手动启动。所有操作通过 `webcli` 执行：

```bash
# 查看所有命令
webcli --help

# Tab 管理
webcli tabs                                    # 列出所有 tab
webcli new https://example.com                    # 新建 tab
TARGET=$(webcli new https://example.com --id-only) # 新建并获取 targetId
webcli open-monitored https://example.com         # 新建 tab 并同时开启网络监控
webcli close $TARGET                              # 关闭 tab

# 页面操作
webcli snapshot $TARGET                           # 获取无障碍树（推荐用于 AI 导航）
webcli eval $TARGET "document.title"              # 执行 JS
webcli screenshot $TARGET ./shot.png              # 截图
webcli scroll $TARGET bottom                      # 滚动到底部

# 点击与交互
webcli click $TARGET "button.submit"              # JS 点击
webcli click-at $TARGET ".upload-btn"             # 真实鼠标点击
webcli find $TARGET text "下一页" click           # 按文字内容点击
webcli fill $TARGET "input[name=q]" "搜索词"      # 填写输入框

# 网络请求捕获
webcli network-start $TARGET                      # 开始捕获
webcli network-requests $TARGET --type xhr,fetch  # 查看请求列表
webcli network-request $TARGET <requestId>        # 查看单个请求详情

# 经验管理（跨 session 积累，越用越快）
webcli exp list bilibili.com                      # 查看某站点的所有经验
webcli exp api bilibili.com popular-list          # 读取接口类经验
webcli exp action xiaohongshu.com post            # 读取操作类经验
webcli exp action sls query-log                   # 读取跨站点流程经验
webcli exp edit api yiche.com salesrank           # 读取并编辑经验
webcli exp save api yiche.com rank                # 保存新经验（Agent 自动调用）
```



## 开始使用

安装并配置好 Chrome 后，在对话里加载 skill，然后直接说你想做什么：

```
请加载 ~/.claude/skills/webcli/SKILL.md 并按照其中的指引完成任务：
帮我抓取 B站今天的热门视频榜单
```

Agent 会自动判断用哪种方式完成任务（搜索、直接请求、还是打开浏览器操作），不需要你指定。

## 场景全景图

### 浏览器操作 → 命令对照

| 操作 | 命令 | 样例 |
|------|------|------|
| 打开链接 | `webcli new <url>` | `webcli new https://www.bilibili.com/v/popular/all` |
| 点击元素 | `webcli click <id> <selector>` | `webcli click $T "#login-btn"` |
| 真实鼠标点击 | `webcli click-at <id> <selector>` | 滑块验证码、Canvas 元素 |
| 按文字点击 | `webcli find <id> --by text "下一页" --action click` | 不需要知道选择器 |
| 填写表单 | `webcli fill <id> <selector> <value>` | `webcli fill $T "#search" "iPhone 16"` |
| 截图 | `webcli screenshot <id> /tmp/out.png` | 截图展示二维码、采集视频帧 |
| 抓包 | `webcli open-monitored <url>` + `network-requests` | 找到页面背后的数据接口 |
| 执行 JS | `webcli eval <id> "<js>"` | 提取 DOM 数据、操控 video 元素 |
| 滚动 | `webcli scroll <id> bottom` | 触发懒加载，加载更多内容 |
| 等待 | `webcli wait <id> --text "加载完成"` | 等待异步内容渲染完毕 |
| 获取 Cookie | `webcli cookies <id>` | 登录后导出 Cookie 供后续使用 |

---

### 使用场景 → 完整流程样例

#### 📊 数据抓取（B站热门榜）

**用户说**：「帮我抓取 B站今天的热门视频榜单」

```
1. 查询经验：webcli exp action bilibili.com popular-list
   → 有经验！直接按经验执行，跳过探索步骤

2. 打开页面，滚动到底部触发懒加载
   webcli new https://www.bilibili.com/v/popular/all
   webcli scroll $T bottom && sleep 1.5

3. 用 eval 提取数据（经验提供了选择器）
   webcli eval $T "Array.from(document.querySelectorAll('.video-card')).map(c => ({
     rank: ..., title: ..., up: ..., link: ...
   }))"
```

**结果**：60 条热门视频数据，含排名、标题、UP主、链接

---

#### 🔍 数据收集（发现并复用接口）

**用户说**：「帮我查一下易车最新的汽车销量排行」

```
1. 查询经验：webcli exp api yiche.com rank → 无经验，开始探索

2. 打开页面并开启网络监控
   webcli open-monitored https://www.yiche.com/rank/

3. 查找数据接口
   webcli network-requests $T --type xhr,fetch
   → 发现：GET https://api.yiche.com/rank/sales?ps=20&pn=1

4. 验证接口直接可用，curl 直接拿数据 ✅

5. 自动沉淀经验（无需用户指令）
   webcli exp save api yiche.com rank << EOF
   # 易车销量榜接口
   ## 接口信息
   - URL: https://api.yiche.com/rank/sales?ps={size}&pn={page}
   ...
   EOF
```

**下次**：直接读经验，秒级完成，无需重新探索

---

#### 🤖 自动化操作（自动发帖）

**用户说**：「帮我在小红书发一篇笔记，标题是 xxx，内容是 yyy」

```
1. 查询经验：webcli exp action xiaohongshu.com post → 有经验，含关键选择器

2. 打开发布页
   webcli new https://creator.xiaohongshu.com/publish/publish

3. 按经验填写内容并发布
   webcli fill $T ".title-input" "xxx"
   webcli fill $T ".content-editor" "yyy"
   webcli click $T ".publish-btn"
   webcli wait $T --text "发布成功"
```

---

#### 🔄 流程操作（查询 SLS 日志）

**用户说**：「帮我查一下今天 order-service 的 ERROR 日志」

```
1. 查询经验：webcli exp action sls query-log → 有经验，含完整操作步骤

2. 打开 SLS 控制台，选择 Logstore，填写查询条件
   webcli new https://sls.console.aliyun.com/...
   webcli find $T --by text "order-service" --action click
   webcli fill $T ".query-input" "level: ERROR"
   webcli click $T ".search-btn"

3. 等待结果，提取并分析日志
   webcli wait $T --text "查询完成"
   webcli eval $T "提取日志列表..."
```

---

#### 🔐 登录态操作（内部系统）

**用户说**：「帮我在 Aone 上查一下我今天的 CR 列表」

```
直连用户日常 Chrome（天然携带登录态，无需任何登录步骤）
webcli new https://aone.alibaba-inc.com/...
webcli eval $T "提取 CR 列表..."
```

---

### 经验场景 → 沉淀什么、怎么用

| 经验类型 | 沉淀时机 | 存储内容 | 下次使用效果 |
|----------|----------|----------|-------------|
| **api** | 发现并验证了数据接口 | URL 模板、参数说明、响应字段 | 直接 curl 调接口，跳过页面操作 |
| **login** | 完成了自动化登录 | 选择器、操作步骤、Cookie 字段 | 自动重新登录，无需用户介入 |
| **action** | 完成了复杂页面操作或跨站点流程 | 选择器、操作序列、步骤流程、已知陷阱 | 直接执行，跳过探索和试错 |
| **anti-crawl** | 突破了反爬机制 | 识别特征、对抗方案、成功率 | 遇到同类反爬直接套用方案 |

**经验带来的核心价值**：

```
第一次执行某任务：探索 → 试错 → 成功 → 自动沉淀经验   耗时：5-15 分钟
第二次执行同类任务：查询经验 → 直接执行               耗时：30 秒 - 2 分钟

积累效应：经验越多 → 执行越快 → 覆盖场景越广
```

## 附录

### 手动启动 CDP Proxy

通常无需手动启动，`webcli` 会自动管理 Proxy 生命周期。仅在需要精确控制端口（如双实例并存）时使用：

```bash
# 基本启动（默认端口 3456，自动探测 Chrome）
python browser_cdp/cdp_proxy.py &

# 指定 Proxy 端口和 Chrome 端口
python browser_cdp/cdp_proxy.py --port 3456 --chrome-port 9222 &

# 启动第二个 Proxy 连接另一个 Chrome 实例（后台运行）
python browser_cdp/cdp_proxy.py --port 3457 --chrome-port 9223 &
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--port` | Proxy HTTP 监听端口 | `CDP_PROXY_PORT` 环境变量，或 `3456` |
| `--chrome-port` | Chrome 远程调试端口 | `CDP_CHROME_PORT` 环境变量，或自动探测 |

> 命令行参数优先级高于环境变量。



### webcli 命令大全
```bash
webcli    
Usage: webcli [OPTIONS] COMMAND [ARGS]...

  webcli - Browser automation via Chrome DevTools Protocol

Options:
  --help  Show this message and exit.

Commands:
  back              后退到上一页。
  check             勾选复选框。
  click             点击元素（JS el.click() 方式）。
  click-at          点击元素（CDP 真实鼠标事件，适用于滑块、Canvas 等）。
  close             关闭标签页。
  console           获取页面拦截到的 console 日志。
  cookies           获取当前页面的 Cookie。
  cookies-clear     清除浏览器中所有 Cookie。
  cookies-set       设置 Cookie。
  dialog-accept     确认（接受）JavaScript 对话框。prompt 对话框可传入文本。
  dialog-dismiss    取消（关闭）JavaScript 对话框。
  dialog-status     检查当前是否有 JavaScript 对话框（alert/confirm/prompt）弹出。
  eval              执行 JavaScript。可直接传表达式、用 -f 指定文件，或通过 stdin 管道输入。
  exp               经验库管理（纯本地文件操作，不依赖 Proxy）。
  fill              清空并填写输入框（直接设置 value，触发 input/change 事件）。
  find              按语义定位器查找元素并执行操作（无需知道 CSS 选择器）。
  focus             聚焦到指定元素。
  forward           前进到下一页。
  get               获取页面或元素属性。
  health            健康检查 — 显示 Proxy 状态和 Chrome 连接情况。
  hover             悬停到指定元素上。
  info              获取页面基本信息（标题、URL、尺寸）。
  is                检查元素状态：visible（可见）、enabled（可用）、checked（已勾选）。
  navigate          在当前标签页导航到指定 URL。
  network-clear     清空已捕获的请求记录（保持捕获继续运行）。
  network-request   获取单个请求的完整详情（含响应体）。
  network-requests  列出捕获的网络请求，支持多种过滤条件。
  network-start     开始捕获标签页的网络请求。
  network-stop      停止捕获网络请求。
  new               新建标签页并等待加载完成。
  open-monitored    新建标签页并从第一个请求起开启网络监控。
  press             按下按键或组合键（如 Enter、Tab、Control+a、Shift+ArrowDown）。
  reload            刷新标签页并等待加载完成。
  screenshot        截图。指定路径则保存到文件，否则输出二进制到 stdout。
  scripts-enable    启用 Debugger 域，开始捕获标签页加载的所有脚本。
  scripts-list      列出标签页已捕获的脚本（默认排除 chrome-extension 脚本）。
  scripts-source    获取指定脚本的源码。
  scroll            滚动页面。参数：top | bottom | up | down | <像素数>。
  select            按值或可见文本选择下拉框选项。
  set-files         为文件输入框设置文件（绕过系统文件选择对话框）。
  show-help         Show all available commands with usage summary.
  snapshot          获取无障碍树（含元素引用），AI 导航首选。
  storage           获取 localStorage 或 sessionStorage 的值。
  storage-clear     清空 localStorage 或 sessionStorage。
  storage-set       设置 localStorage 或 sessionStorage 的值。
  tabs              列出所有浏览器标签页（targets 的别名）。
  targets           列出所有浏览器标签页。
  type              逐字符输入文本（模拟真实键盘事件）。
  uncheck           取消勾选复选框。
  wait              等待元素、毫秒数、文本出现或 JS 条件成立。
```
### webcli exp 命令
```bash
webcli exp      
Usage: webcli exp [OPTIONS] COMMAND [ARGS]...

  经验库管理（纯本地文件操作，不依赖 Proxy）。

  分类说明（站点级）：
    api        接口数据获取经验（URL、参数、响应字段、加密破解）
    login      自动化登录经验（登录流程、Cookie 获取、验证码处理）
    action     自动化操作经验（页面交互流程、表单提交、上传、跨站点流程等）

  分类说明（全局级，不绑定站点）：
    anti-crawl 反爬对抗经验（跨站点通用，按反爬类型组织）

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
    webcli exp del api yiche.com rank         # 删除经验（有确认提示）
    webcli exp del api yiche.com rank --yes   # 跳过确认直接删除

Options:
  --help  Show this message and exit.

Commands:
  action      快捷方式：查看操作类经验（省略 show 子命令）。
  anti-crawl  快捷方式：查看全局分类经验（不绑定站点，省略 show 子命令）。
  api         快捷方式：查看接口类经验（省略 show 子命令）。
  del         删除一条经验记录（默认有确认提示）。
  edit        用系统编辑器打开经验文件（文件不存在时自动创建模板）。
  list        列出所有经验，或指定站点的经验。
  login       快捷方式：查看登录类经验（省略 show 子命令）。
  save        从 stdin 保存经验（Agent 写入时使用）。
  show        查看某条经验的完整内容。
  update      更新经验的使用记录（last_used_at 和 last_used_status）或追加内容。
```

使用样例
```bash
> webcli exp list       
分类           站点                        名称
------------------------------------------------------------
api          ithome.com                rank

> webcli exp show api ithome.com rank
---
site: ithome.com
category: api
status: verified
created_at: 2026-04-06
updated_at: 2026-04-06
tags: [rank, news, daily, weekly, monthly, hot-comment]
---

# IT之家排行榜数据（DOM 提取）

## 接口信息
- **页面 URL**: `https://m.ithome.com/rankm/`
- **数据源**: SSR 直出
- **渲染方式**: 服务端渲染，数据直接在 HTML 中
- **数据结构**: 页面包含四个榜单（日榜、周榜、热评、月榜），每个榜单 12 条新闻

```