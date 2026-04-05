# webcli 经验沉淀规范

在任务执行过程中和完成后，自动识别、提取并持久化有价值的经验知识，形成可复用的站点级经验库，为后续同站点/同类型任务提供决策加速。

## 核心理念

> **经验不是事后总结，而是伴随任务自然生长的副产物。**
>
> 每一次接口破解、每一次反爬对抗、每一次登录流程、每一次操作自动化，都是值得沉淀的经验。
> 智能体应当在任务执行的关键节点**自动判断**是否需要沉淀，而非等待人工指令。

## 沉淀触发机制（何时应该沉淀）

### 自动触发（智能体必须主动执行）

以下场景发生时，智能体**必须自动触发**经验沉淀，无需等待用户指令：

| 触发场景 | 沉淀内容 | 优先级 |
|----------|----------|--------|
| **成功破解 API 接口** | 接口完整信息、加密方式、破解方法；**有签名的接口必须额外包含：精确拼接公式、完整可运行实现代码、验证方法、易错点** | 🔴 最高 |
| **遭遇并突破反爬** | 反爬类型、识别特征、突破方案、关键代码片段 | 🔴 最高 |
| **完成自动化登录流程** | 登录步骤、关键选择器、Cookie 字段、有效期 | 🔴 最高 |
| **完成复杂页面操作** | 操作流程、关键选择器、等待时机、注意事项 | 🟡 高 |
| **发现站点结构变化** | 变化前后对比、影响范围、适配方案 | 🟢 中 |

### 手动触发

用户可通过以下方式主动触发经验沉淀：
- 直接说"沉淀经验"、"记录这次的经验"、"保存这次的发现"
- 在任务结束后说"总结一下"、"有什么值得记录的"

## 沉淀判断标准（什么样的应该沉淀）

### ✅ 应该沉淀的经验

1. **可复用性**：该经验能帮助后续同站点或同类型任务节省时间
2. **非显而易见**：不是通用常识，而是通过实际探索才能获得的知识
3. **有具体细节**：包含可直接使用的 URL、参数、代码片段等
4. **有时效标记**：记录发现时间，便于后续判断是否过期

### 签名类接口的额外质量门槛

> 签名类接口的经验最容易"看起来完整，实际用不了"。沉淀前必须自检以下清单，**任意一项为"否"则经验不合格，不得写入**：

| 自检项 | 合格标准 |
|--------|----------|
| 拼接公式是否精确到字符级 | 能从公式直接写出代码，不需要猜测任何细节 |
| 是否有完整可运行的实现代码 | 复制代码后只需填入参数即可运行，无需修改逻辑 |
| 是否记录了所有固定常量及来源 | 密钥、cid、platform_key 等均有值，并注明从哪里提取 |
| 是否记录了验证方法 | 说明如何用已知请求验证签名实现的正确性 |
| 是否记录了易错点 | 至少列出调试过程中遇到的一个坑（无坑则写"已验证无歧义"）|

### 反爬类经验的额外质量门槛

> 反爬经验必须达到"按步骤执行即可复现"的完整度，不能只写原理描述。

| 自检项 | 合格标准 |
|--------|----------|
| 识别特征是否可观测 | 能通过具体的 HTTP 状态码、响应内容、页面特征判断是否触发 |
| 对抗方案是否有完整实现代码 | 每个方案都有可直接运行的代码，不能只写"修改 Headers" |
| 是否记录了成功率和适用条件 | 明确说明方案在什么情况下有效、成功率如何 |
| 是否有实战案例 | 至少一个真实站点的验证记录 |

### ❌ 不应该沉淀的经验

1. **通用编程知识**：如 Python 语法、HTTP 协议基础等
2. **一次性配置**：如某次任务的特定参数组合，不具备复用价值
3. **敏感信息**：如用户的登录凭证、私有 API Key 等
4. **未经验证的猜测**：所有沉淀的经验必须是经过实际验证的

## 沉淀门槛

不是所有经验都值得沉淀，需满足以下门槛：

| 条件 | 是否沉淀 | 理由 |
|------|----------|------|
| 大站 / 优质站点的接口 | ✅ 沉淀 | 复用价值高 |
| 有反爬保护的接口 | ✅ 沉淀 | 破解成本高，必须保留 |
| 有参数加密的接口 | ✅ 沉淀 | 逆向分析成本高 |
| 小站 / 无反爬的简单接口 | ❌ 不沉淀 | 重新探索成本低 |
| 临时性 / 一次性数据接口 | ❌ 不沉淀 | 无复用场景 |

## 经验生命周期管理

经验不是静态文档，而是有完整生命周期的知识资产：

```
生成 → 合并 → 使用 → 更新 → 过期判断 → 剔除/归档
```

### 生成

- **触发时机**：见上方「沉淀触发机制」
- **生成方式**：智能体在任务执行过程中自动提取关键信息，按模板格式化后写入经验库
- **质量门槛**：必须经过实际验证，禁止记录未验证的猜测

### 合并

当新经验与已有经验存在重叠时，执行合并而非重复添加：

| 合并场景 | 合并策略 |
|----------|----------|
| 同站点同接口，新增字段信息 | 合并字段列表，保留两者的并集 |
| 同站点同接口，破解方式更新 | 替换旧的破解方式，旧方式移入「历史方案」 |
| 同类型反爬，新增对抗方案 | 追加为新的方案选项，调整优先级排序 |
| 同站点页面结构变化 | 更新当前结构，旧结构标记为「已过期」 |

**合并规则**：
- 以**站点 + 接口/路径**为唯一键进行去重
- 合并时保留所有历史版本的关键信息（如旧的破解方式可能在站点回滚时有用）
- 合并后更新 `updated_at` 标签

### 更新

- **主动更新**：新任务执行时发现已有经验与实际不符，自动更新
- **验证更新**：使用已有经验时验证成功，更新 `last_used_at` 和 `last_used_status`

### 过期判断与剔除

**过期判断规则**：

| 经验类型 | 过期阈值 | 判断依据 |
|----------|----------|----------|
| API 接口 | 90 天未使用且未更新 | 接口可能已变更 |
| 反爬经验 | 180 天未使用且未更新 | 反爬策略相对稳定 |
| 登录流程 | 90 天未使用且未更新 | 登录页面可能已改版 |
| 页面操作 | 60 天未使用且未更新 | 页面结构可能已改版 |

**剔除流程**：

```
经验超过过期阈值
 ↓
├── 下次使用时自动验证
│    ├── 验证通过 → 更新时间标签，继续保留
│    └── 验证失败 → 标记为 deprecated
│
└── 定期清理（可手动触发）
     → 将 deprecated 经验移入 experience/archive/
     → 不直接删除，保留可追溯性
```

## 经验标签体系

每条经验记录必须携带以下标签（在 frontmatter 中定义）：

```yaml
---
# 基础标签
site: example.com                    # 站点域名
category: api | login | action | anti-crawl | workflow  # 经验分类
tags: [search, user-info, video]     # 模型自动打的语义标签

# 时间标签
created_at: 2026-04-02               # 创建时间
updated_at: 2026-04-02               # 最后更新时间
last_used_at: 2026-04-02             # 上次使用时间
last_used_status: success | failed   # 上次使用状态

# 质量标签
status: verified | deprecated | unstable  # 当前状态
difficulty: easy | medium | hard          # 难度评级
confidence: high | medium | low           # 可信度
---
```

**标签自动维护规则**：
- `created_at`：经验首次生成时自动设置，不可修改
- `updated_at`：每次内容变更时自动更新
- `last_used_at`：每次被读取并应用于任务时自动更新
- `last_used_status`：根据应用结果自动设置
- `tags`：由模型根据经验内容自动打标，支持多标签
- `confidence`：根据 `last_used_status` 的历史记录自动计算
  - 连续 3 次 success → high
  - 最近一次 failed → low
  - 其他 → medium

---

## webcli 场景经验分类

### 目录结构

```
~/.agents/skills/webcli/experience/
├── sites/
│   └── {site-domain}/
│       ├── api/          # 接口数据获取经验（webcli 抓包发现的接口）
│       ├── login/        # 自动化登录经验
│       └── action/       # 自动化操作经验（页面交互流程）
├── anti-crawl/           # 反爬对抗经验（跨站点通用）
└── workflow/             # 多步骤任务流程经验（跨站点，按任务目标命名）
```

> 经验统一存储在 `~/.agents/skills/webcli/experience/`，与 agent 平台无关，Claude、Cursor、Windsurf 等共享同一份经验库。如需自定义路径，设置环境变量 `WEB_CLI_EXPERIENCE_DIR=/your/path`。

### 分类说明

| 分类 | 目录 | 适用场景 | 典型文件名 |
|------|------|----------|-----------|
| **api** | `sites/{domain}/api/` | 通过 network 抓包发现的数据接口 | `rank.md`、`search.md`、`user-info.md` |
| **login** | `sites/{domain}/login/` | 自动化登录流程、Cookie 获取、验证码处理 | `main.md`、`sms.md`、`qrcode.md` |
| **action** | `sites/{domain}/action/` | 页面交互自动化流程（发帖、搜索、上传等） | `post.md`、`comment.md`、`upload.md` |
| **anti-crawl** | `anti-crawl/` | 跨站点通用的反爬对抗经验 | `cloudflare.md`、`slider-captcha.md` |
| **workflow** | `workflow/` | 多步骤任务流程（可跨站点，按任务目标命名） | `query-sls-log.md`、`deploy-ude.md` |

### action vs workflow 判断规则

两者容易混淆，用以下规则判断：

| 判断维度 | `action` | `workflow` |
|----------|----------|------------|
| **站点归属** | 绑定单一站点 | 可跨多个站点/系统 |
| **任务粒度** | 单一操作（"在这个页面做一件事"） | 完整任务目标（"完成某件事"） |
| **复用方式** | 作为 workflow 的**组成步骤** | 作为**完整任务**直接执行 |

**决策口诀**：
- "在 **某个站点** 上做 **一件事**" → `action`（如：在 SLS 页面执行查询、在 Aone 点击发布）
- "为了 **完成某个目标**，要跨多个系统做多件事" → `workflow`（如：查询 SLS 日志的完整流程、部署 UDE 服务）

**边界情况**：如果操作只涉及单一站点，即使步骤较多，也优先存 `action`。只有当任务**必须跨站点**，或任务目标本身就是用户说的"那件事"（而非某个更大任务的一个步骤）时，才存 `workflow`。

---

## 格式规范

### api 类经验

```markdown
---
site: {域名}
category: api
status: verified
created_at: {YYYY-MM-DD}
updated_at: {YYYY-MM-DD}
---

# {接口名称}

## 接口信息
- **URL**: `{完整 URL，参数用占位符}`
- **方法**: GET / POST
- **用途**: {一句话描述}

## 数据来源（必填）
- **渲染方式**: SSR 直出 / JS 异步请求 / SSR + JS 混合 / 必须浏览器交互
- **验证方式**: {如何验证的，例如：curl + 选择器解析 / 浏览器 eval / network 抓包}
- **验证结论**: {验证了什么、覆盖了多少数据量、结论是否完整}

## 请求参数
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| {name} | {type} | 是/否 | {说明} |

## 响应字段
| 字段路径 | 类型 | 说明 |
|----------|------|------|
| {json.path} | {type} | {说明} |

## 加密/签名破解

> 接口无任何加密/签名时此节可省略。**有签名的接口必须填写，且必须达到"复制代码直接可用"的完整度——模糊描述等于没有记录。**

### 签名概览

- **加密类型**: {URL 参数签名 / 请求头签名 / 请求体加密 / Token 动态生成 / 多层混合}
- **签名算法**: {MD5 / HMAC-SHA256 / AES / 自定义 JS 混淆 / ...}
- **签名位置**: {请求头字段名 / 请求参数名，如：`x-sign` header / `sign` query param}
- **动态参数来源**: {时间戳 / 随机串 / 固定密钥，列出所有参与签名的动态值及其生成方式}

### 拼接字符串（精确格式，逐字节）

> ⚠️ 这是最容易出错的地方，必须精确到每个字符，不能有任何歧义。

```
{完整拼接公式，用实际字符串示例说明，例如：}
"cid=508&param=" + url_encode(json_str) + "19DDD1FBDFF065D3A4DA777D2D7A81EC" + str(timestamp_ms)
```

**关键细节（必须逐条确认）**：
- [ ] 参数顺序：{列出所有参与拼接的字段及其顺序}
- [ ] JSON 序列化：{是否需要 URL 编码？key 是否排序？是否有空格？}
- [ ] 时间戳精度：{秒级 / 毫秒级}
- [ ] 大小写：{MD5 结果是大写还是小写？密钥是否区分大小写？}
- [ ] 编码方式：{UTF-8 / GBK？URL 编码用哪种规范？}
- [ ] 固定常量：{列出所有硬编码的密钥、cid、platform 等常量及其值}

### 完整实现代码

> 必须是可直接运行的代码，不能是伪代码或省略关键步骤。

```python
import hashlib
import json
import time
import urllib.parse

# --- 固定常量（从 JS 源码/抓包中提取，勿修改）---
# {常量名}: {常量值}  # {来源说明，如：JS 文件 xxx.js 第 N 行}

def build_sign({参数列表}) -> str:
    """
    签名生成。
    拼接公式：{用一行文字精确描述公式}
    """
    # 步骤一：{说明}
    # 步骤二：{说明}
    # ...
    raw = {拼接表达式}
    return hashlib.md5(raw.encode("utf-8")).hexdigest()  # 注意大小写

def build_headers({参数列表}) -> dict:
    """构造完整请求头，包含所有签名相关字段。"""
    timestamp = int(time.time() * 1000)
    sign = build_sign(...)
    return {
        # {列出所有必需 header 及其值}
    }
```

### 验证方法

> 说明如何确认签名实现是正确的，避免"可能需要调整"的模糊状态。

- **验证步骤**: {如：用已知的请求参数手动计算签名，与抓包结果对比}
- **成功标志**: {如：接口返回 `status: "1"` 而非 403 / 签名错误提示}
- **失败特征**: {接口返回什么内容表示签名错误，如：`{"status":"0","message":"sign error"}`}

### 易错点

> 记录调试过程中踩过的坑，防止下次重蹈覆辙。

- {如：param 必须先 JSON 序列化再 URL 编码，顺序不能反}
- {如：时间戳必须是毫秒级，秒级会导致签名失败}
- {如：MD5 结果必须小写，大写会被拒绝}
- {如：JSON key 顺序影响签名，必须按固定顺序序列化}

## 抓包方式
通过 `webcli network-requests` 或 `webcli network-response` 抓包获取。

## 请求示例
```python
# 完整可运行的请求示例
import requests

def fetch_data(page: int = 1) -> dict:
    # {调用 build_headers 构造请求头}
    headers = build_headers(...)
    params = {
        # {列出所有请求参数}
    }
    response = requests.get("{URL}", headers=headers, params=params)
    response.raise_for_status()
    return response.json()
```

## 注意事项
- {频率限制、Token 有效期、分页逻辑等}
```

### login 类经验

```markdown
---
site: {域名}
category: login
status: verified
created_at: {YYYY-MM-DD}
updated_at: {YYYY-MM-DD}
---

# {登录方式名称}

## 登录流程
1. {步骤一}
2. {步骤二}
3. {步骤三}

## 关键操作
```bash
webcli fill {target_id} "#username" "your_username"
webcli fill {target_id} "#password" "your_password"
webcli click {target_id} "#login-btn"
```

## Cookie 获取
- 登录成功后通过 `webcli cookies {target_id}` 获取
- 关键 Cookie 字段：{列出关键字段名}
- Cookie 有效期：{有效期说明}

## 注意事项
- {验证码处理方式、二次验证、风控规避等}
```

> **login 子类型说明**：不同登录方式的经验格式差异较大，按以下子类型分别沉淀：
> - `main.md` — 账号密码登录（上方模板）
> - `sms.md` — 短信验证码登录
> - `qrcode.md` — 扫码登录

### action 类经验

```markdown
---
site: {域名}
category: action
status: verified
created_at: {YYYY-MM-DD}
updated_at: {YYYY-MM-DD}
---

# {操作名称}

## 操作流程
1. {步骤一}
2. {步骤二}

## 关键选择器
| 元素 | 选择器 | 备注 |
|------|--------|------|
| {元素名} | `{CSS/XPath}` | {备注} |

## 注意事项
- {等待时机、动态加载、弹窗处理等}
```

### anti-crawl 类经验

```markdown
---
category: anti-crawl
status: verified
created_at: {YYYY-MM-DD}
updated_at: {YYYY-MM-DD}
---

# {反爬类型名称}

## 识别特征
- **HTTP 状态码**: {如 403、503}
- **响应特征**: {如包含特定 HTML 标记、JS Challenge}
- **典型表现**: {用户可感知的现象描述}

## 对抗方案（按优先级排序）

### 方案一：{方案名称}（首选）

- **适用条件**: {什么情况下用这个方案}
- **核心思路**: {一句话说明原理}
- **完整实现代码**:
  ```python
  # 必须是可直接运行的代码，不能只写原理描述
  # {具体实现}
  ```
- **成功率**: {实测成功率，如：验证过 N 个站点，成功率约 X%}
- **优缺点**: {优势和局限}

### 方案二：{方案名称}（备选）

{同上结构}

## 实战案例

### [{日期}] {站点域名}

- **遭遇的反爬**: {具体描述}
- **采用的方案**: {方案几}
- **关键步骤**: {执行了什么操作}
- **最终结果**: 成功 / 失败
```

> **anti-crawl 经验的失效判断与更新规则**
>
> 反爬机制会随时间变化，经验可能过期。遵循以下规则：
>
> | 情况 | 处理方式 |
> |------|----------|
> | 按经验执行，**成功** | 更新 `updated_at` 和 `last_used_at`，status 保持 `verified` |
> | 按经验执行，**失败一次** | 回退通用探索模式，重新分析反爬机制 |
> | 重新分析后找到新方案 | 将新方案追加为优先方案，旧方案降级，更新 `updated_at`，status 改为 `verified` |
> | 重新分析后无法突破 | 将 status 改为 `unstable`，注明失效日期和失效现象 |
> | 超过 180 天未使用且未更新 | 将 status 改为 `deprecated`，下次使用前需重新验证 |
>
> **关键原则**：经验失败时，不要反复重试同一方案——一次失败即视为经验可能过期，立即切换到重新探索模式。

### workflow 类经验

多步骤任务流程经验，**不绑定特定站点**，按任务目标命名。适用于：
- 跨多个系统/页面的完整操作流程（如：查询日志、发布部署、数据导出）
- 有明确步骤顺序依赖的任务
- 需要条件判断或错误处理的自动化流程

```markdown
---
category: workflow
status: verified
created_at: {YYYY-MM-DD}
updated_at: {YYYY-MM-DD}
---

# {任务目标名称}（如：查询 SLS 日志、部署 UDE 服务）

## 适用场景
- {什么情况下使用这个流程}
- {前置条件：需要登录哪些系统、需要哪些权限等}

## 涉及站点/系统
- `{domain-1}` — {用途}
- `{domain-2}` — {用途}

## 操作步骤

### 第一步：{步骤名称}
```bash
# 具体命令
webcli new https://...
```
- **等待条件**: {等待什么加载完成}
- **成功标志**: {如何判断这步成功}

### 第二步：{步骤名称}
...

## 条件分支
- **如果 {条件}**：{处理方式}
- **如果失败**：{回退方案}

## 注意事项
- {耗时估计、幂等性、副作用等}
```

---

## CLI 使用方式（webcli exp）

> `exp` 命令是**纯本地文件操作**，不依赖 CDP Proxy，随时可用，无需启动浏览器。

### 基本命令

```bash
# 列出所有经验
webcli exp list

# 列出某站点的所有经验
webcli exp list yiche.com

# 查看某条经验（完整格式）
webcli exp show api yiche.com rank
webcli exp show login taobao.com main
webcli exp show action xiaohongshu.com post
webcli exp show anti-crawl cloudflare

# 快捷方式（省略 show 子命令）
webcli exp api yiche.com rank
webcli exp login taobao.com main
webcli exp action xiaohongshu.com post
webcli exp anti-crawl cloudflare
```

### Agent 写入经验

```bash
# 从 stdin 保存经验（Agent 自动沉淀时使用）
cat << 'EOF' | webcli exp save api yiche.com rank
# 易车销量榜接口

## 接口信息
- **URL**: `https://api.yiche.com/rank/sales?page={page}&size={size}`
...
EOF

# 追加内容到已有经验
echo "## 补充说明\n..." | webcli exp save api yiche.com rank --append

# 用编辑器手动编辑（会自动创建模板）
webcli exp edit api yiche.com rank
```

### Agent 自动沉淀规则

Agent 在以下场景**必须自动调用 `webcli exp save`** 沉淀经验，无需用户指令：

| 触发场景 | 沉淀分类 | 示例命令 |
|----------|----------|---------|
| 通过抓包发现并验证了数据接口 | `api` | `webcli exp save api {site} {name}` |
| 完成了自动化登录流程 | `login` | `webcli exp save login {site} main` |
| 完成了复杂的页面操作流程 | `action` | `webcli exp save action {site} {name}` |
| 遭遇并突破了反爬机制 | `anti-crawl` | `webcli exp save anti-crawl - {type}` |
| 完成了跨站点/多步骤的任务流程 | `workflow` | `webcli exp save workflow - {task-name}` |

### Agent 使用已有经验

在开始任务前，Agent 应**主动查询**是否有已有经验可复用：

```bash
# 检查是否有该站点的经验
webcli exp list yiche.com

# 如果有，先读取经验再开始任务
webcli exp api yiche.com rank
```
