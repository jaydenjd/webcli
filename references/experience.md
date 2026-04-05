---
name: spider-experience
description: Spider experience auto-accumulation agent. Automatically identifies, captures, and persists valuable crawling experiences during or after spider tasks. Use when the agent completes a crawling task, encounters anti-crawling challenges, discovers API endpoints, explores new paths, or experiences failures. Triggers on phrases like "沉淀经验", "记录经验", "保存经验", "经验总结", "accumulate experience", "save learnings", or automatically after SpiderClaw/TaskCollector task completion.
---

# SpiderExperience — 爬虫经验自主沉淀智能体

在爬虫任务执行过程中和完成后，自动识别、提取并持久化有价值的经验知识，形成可复用的站点级经验库，为后续同站点/同类型任务提供决策加速。

## 核心理念

> **经验不是事后总结，而是伴随任务自然生长的副产物。**
>
> 每一次路径探索、每一次反爬对抗、每一次接口破解、每一次失败重试，都是值得沉淀的经验。
> 智能体应当在任务执行的关键节点**自动判断**是否需要沉淀，而非等待人工指令。

## 经验库结构

所有经验统一沉淀到项目根目录下的 `experience/` 目录中：

```
experience/
├── sites/                          # 按站点组织的经验
│   ├── {site-domain}/              # 站点域名（如 taobao.com）
│   │   ├── site-profile.md         # 站点画像（反爬特征、整体评估）
│   │   ├── apis/                   # 该站点的 API 接口经验
│   │   │   ├── {api-name}.md       # 单个接口的完整记录
│   │   │   └── ...
│   │   ├── paths/                  # 路径探索经验
│   │   │   └── exploration-log.md  # 路径探索记录
│   │   └── failures/               # 失败经验
│   │       └── failure-log.md      # 失败记录
│   └── ...
├── anti-crawl/                     # 通用反爬手段经验（跨站点）
│   ├── cloudflare.md               # Cloudflare 对抗经验
│   ├── waf-patterns.md             # WAF 模式识别与对抗
│   └── ...
├── task-patterns/                  # 任务收集模式经验（跨站点）
│   └── collection-patterns.md      # 收集模式与策略
└── README.md                       # 经验库索引与使用说明
```

## 沉淀触发机制（何时应该沉淀）

### 自动触发（智能体必须主动执行）

以下场景发生时，智能体**必须自动触发**经验沉淀，无需等待用户指令：

| 触发场景 | 沉淀内容 | 优先级 |
|----------|----------|--------|
| **成功破解 API 接口** | 接口完整信息、加密方式、破解方法 | 🔴 最高 |
| **完成路径探索（SpiderClaw 阶段二）** | 数据加载方式、页面结构、分页逻辑、URL 规律 | 🔴 最高 |
| **遭遇并突破反爬** | 反爬类型、识别特征、突破方案、关键代码片段 | 🔴 最高 |
| **任务失败且原因明确** | 失败原因、尝试过的方案、建议的替代路径 | 🟡 高 |
| **发现新的数据源** | 站点信息、数据覆盖范围、接入方式 | 🟡 高 |
| **完成并发任务收集（TaskCollector）** | 任务拆解策略、并发效果、数据源质量评估 | 🟢 中 |
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

### ❌ 不应该沉淀的经验

1. **通用编程知识**：如 Python 语法、HTTP 协议基础等
2. **一次性配置**：如某次任务的特定参数组合，不具备复用价值
3. **敏感信息**：如用户的登录凭证、私有 API Key 等
4. **未经验证的猜测**：所有沉淀的经验必须是经过实际验证的

## 经验沉淀格式规范（应该沉淀的形式）

### 一、API 接口经验

文件位置：`experience/sites/{domain}/apis/{api-name}.md`

```markdown
---
site: {站点域名}
api_name: {接口名称}
status: verified | deprecated | unstable
discovered_at: {发现日期 YYYY-MM-DD}
last_verified_at: {最后验证日期 YYYY-MM-DD}
difficulty: easy | medium | hard
---

# {接口名称}

## 基本信息

- **接口地址**: `{完整 URL，参数用占位符}`
- **请求方法**: GET / POST
- **数据格式**: JSON / XML / HTML
- **用途说明**: {一句话描述该接口提供什么数据}

## 请求参数

| 参数名 | 类型 | 必填 | 说明 | 示例值 |
|--------|------|------|------|--------|
| {name} | {type} | 是/否 | {说明} | {示例} |

## 响应字段

| 字段路径 | 类型 | 说明 | 示例值 |
|----------|------|------|--------|
| {json.path} | {type} | {说明} | {示例} |

## 加密/签名破解

> 如果接口无加密，此节可省略

- **加密类型**: {如：URL 参数签名 / 请求体加密 / Token 动态生成}
- **加密算法**: {如：HMAC-SHA256 / AES / 自定义 JS 混淆}
- **破解方式**: {详细描述破解过程}
- **关键代码片段**:
  ```python
  # {破解核心逻辑}
  ```
- **依赖工具**: {如：js-reverse-analyzer MCP 工具}
- **注意事项**: {如：Token 有效期 30 分钟，需定时刷新}

## 请求示例

```python
# 完整可运行的请求示例
```

## 分页/翻页逻辑

- **分页方式**: {页码分页 / 游标分页 / 滚动加载}
- **分页参数**: {具体参数名和取值规则}
- **总量获取**: {如何获取数据总量或判断是否到达末页}

## 频率限制

- **已知限制**: {如：每分钟 60 次}
- **建议间隔**: {如：≥1.5 秒}
- **超限表现**: {如：返回 429 状态码}
```

### 二、路径探索经验

文件位置：`experience/sites/{domain}/paths/exploration-log.md`

```markdown
---
site: {站点域名}
last_updated: {最后更新日期 YYYY-MM-DD}
---

# {站点域名} 路径探索记录

## 站点概况

- **主要业务**: {站点提供什么服务/数据}
- **技术栈**: {前端框架、渲染方式等}
- **数据加载方式**: 静态 HTML / JS 渲染 / XHR API / SSR + Hydration

## 探索记录

### [{日期}] {探索目标}

**目标**: {要获取什么数据}

**探索过程**:
1. {步骤一：做了什么，发现了什么}
2. {步骤二：...}

**数据加载分析**:
- **页面 URL 规律**: `{URL 模式，用占位符表示变量}`
- **实际数据来源**: {API 接口 / 内嵌 JSON / HTML 渲染}
- **分页机制**: {分页方式及参数}
- **关键选择器/路径**: {CSS 选择器或 JSON 路径}

**最终方案**: {选择了什么技术方案，为什么}

**产出物**: {是否产出了 API 接口记录，链接到对应文件}
```

### 三、任务收集经验

文件位置：`experience/task-patterns/collection-patterns.md`

```markdown
---
last_updated: {最后更新日期 YYYY-MM-DD}
---

# 任务收集模式经验

## 收集模式库

### [{日期}] {收集任务名称}

**需求描述**: {原始需求}

**任务拆解策略**:
- **拆解维度**: {按数据源 / 按分片 / 按字段}
- **子任务数量**: {N 个}
- **并发策略**: {分几批，每批几个}

**数据源评估**:

| 数据源 | 数据质量 | 覆盖范围 | 反爬难度 | 推荐度 |
|--------|----------|----------|----------|--------|
| {源1} | ⭐⭐⭐ | {范围} | {难度} | ✅/⚠️/❌ |

**执行效果**:
- **总耗时**: {时间}
- **成功率**: {成功子任务数/总数}
- **数据量**: {采集到的数据条数}
- **数据质量**: {完整性、准确性评估}

**经验总结**: {关键发现和建议}
```

### 四、通用反爬手段经验

文件位置：`experience/anti-crawl/{type}.md`

```markdown
---
type: {反爬类型，如 cloudflare / waf / ip-ban / captcha}
last_updated: {最后更新日期 YYYY-MM-DD}
---

# {反爬类型} 对抗经验

## 识别特征

- **HTTP 状态码**: {如 403、503}
- **响应特征**: {如包含特定 HTML 标记、JS Challenge}
- **Headers 特征**: {如特定的 Server 头}
- **典型表现**: {用户可感知的现象描述}

## 对抗方案（按优先级排序）

### 方案一：{方案名称}（首选）

- **适用条件**: {什么情况下用这个方案}
- **核心思路**: {一句话说明原理}
- **实现方式**:
  ```python
  # 关键代码片段
  ```
- **成功率**: {实测成功率}
- **优缺点**: {优势和局限}

### 方案二：{方案名称}（备选）

{同上结构}

## 实战案例

### [{日期}] {站点域名}

- **遭遇的反爬**: {具体描述}
- **采用的方案**: {方案几}
- **处理过程**: {关键步骤}
- **最终结果**: 成功 / 失败
```

### 五、失败经验

文件位置：`experience/sites/{domain}/failures/failure-log.md`

```markdown
---
site: {站点域名}
last_updated: {最后更新日期 YYYY-MM-DD}
---

# {站点域名} 失败记录

## 失败记录

### [{日期}] {失败任务简述}

**任务目标**: {原本要做什么}

**失败现象**:
- **错误类型**: {如：反爬拦截 / 接口变更 / 数据格式异常 / 登录态失效}
- **错误信息**: `{具体错误信息或 HTTP 状态码}`
- **发生阶段**: {在哪个阶段失败的}

**已尝试的方案**:

| 方案 | 结果 | 耗时 | 备注 |
|------|------|------|------|
| {方案1} | ❌ 失败 | {时间} | {为什么失败} |
| {方案2} | ❌ 失败 | {时间} | {为什么失败} |

**根因分析**: {最终确认的失败原因}

**建议的替代路径**: {如果未来再遇到类似情况，建议怎么做}

**是否可恢复**: 是（{条件}）/ 否（{原因}）
```

## 沉淀工作流

### 在 SpiderClaw 任务中的沉淀时机

```
阶段二（路径探索）完成后
  → 自动沉淀：路径探索经验、站点画像
  → 若发现 API 接口 → 自动沉淀：API 接口经验

阶段三（样例数据）完成后
  → 若遭遇反爬并突破 → 自动沉淀：反爬对抗经验

阶段四（代码生成）完成后
  → 若涉及接口加密破解 → 自动沉淀/更新：API 接口的加密破解信息

任务失败时
  → 自动沉淀：失败经验
```

### 在 TaskCollector 任务中的沉淀时机

```
步骤一（任务拆解）完成后
  → 自动沉淀：任务收集模式（拆解策略）

步骤二（并发抓取）各子任务完成后
  → 成功的子任务 → 沉淀对应站点的路径探索、API 接口经验
  → 失败的子任务 → 沉淀失败经验

步骤三（结果汇总）完成后
  → 自动沉淀/更新：任务收集模式（执行效果、数据源评估）
```

## 沉淀执行规范

### 写入规则

1. **增量追加，不覆盖**：同一文件中的新经验以新章节追加，不删除已有内容
2. **去重检查**：写入前检查是否已存在相同站点+相同接口/路径的记录，若存在则**更新**而非重复添加
3. **覆盖差异提醒**：当新经验与已有经验的关键结论（如渲染方式、工具选择、核心选择器）存在冲突时，必须显式对比新旧结论的差异，确认是页面改版还是旧经验本身有误，再决定覆盖。**禁止不经对比直接覆盖**
4. **时间标记**：每条经验必须标注发现日期，便于判断时效性
5. **交叉引用**：相关经验之间通过相对路径互相引用（如 API 经验引用对应的路径探索记录）

### 读取规则（经验复用）

在开始新的爬虫任务时，智能体**必须先检查经验库**：

1. **检查站点经验**：`experience/sites/{domain}/` 是否存在
   - 存在 → 读取站点画像、已有 API 接口、历史失败记录
   - 对于 `status: verified` 的经验，**直接按经验执行，不做额外验证**
   - 仅当执行结果与经验明确不符时，才回退通用模式
2. **检查反爬经验**：若遭遇反爬，先查 `experience/anti-crawl/` 中是否有对应类型的对抗经验
3. **检查任务模式**：若为收集任务，查 `experience/task-patterns/` 中是否有类似模式可参考

### 质量要求

- **准确性**：所有沉淀的信息必须经过实际验证，禁止记录未验证的猜测
- **完整性**：API 接口必须包含完整的请求参数和响应字段，不能只记录部分
- **可执行性**：代码片段必须是可直接运行的，不能是伪代码
- **可读性**：使用清晰的中文描述，表格化呈现结构化信息
- **验证结论覆盖业务需求**：验证结论必须覆盖完整的业务需求，而非局部现象。例如目标是"抓取 12 条日榜数据"，验证标准就应该是"能拿到 12 条"，而非"某个选择器返回了 N 个元素"。局部验证结论不得作为全局结论写入经验

## 路由规则

> **经验沉淀是 SpiderClaw 和 TaskCollector 的伴生行为，不是独立任务。**
>
> 触发方式：
> - **自动触发**：在 SpiderClaw / TaskCollector 任务执行过程中，到达上述沉淀时机时自动执行
> - **手动触发**：用户明确要求"沉淀经验"、"记录经验"、"总结经验"时执行
> - **任务启动时**：新任务开始前，自动检索并加载相关经验，辅助决策
>
> **与其他 Skill 的协作**：
> - **SpiderClaw**：在阶段二、三、四完成后自动触发沉淀；新任务阶段二开始前自动加载站点经验
> - **TaskCollector**：在步骤一、二、三完成后自动触发沉淀；新任务开始前加载任务模式经验

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
| 同站点路径探索，页面结构变化 | 更新当前结构，旧结构标记为「已过期」 |

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
| 路径探索 | 60 天未使用且未更新 | 页面结构可能已改版 |
| 反爬经验 | 180 天未使用且未更新 | 反爬策略相对稳定 |
| 失败经验 | 120 天未使用 | 失败原因可能已修复 |
| 任务收集模式 | 不过期 | 方法论长期有效 |

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
category: api | path | anti-crawl | failure | task-pattern  # 经验分类
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

## 沉淀门槛

不是所有经验都值得沉淀，需满足以下门槛：

| 条件 | 是否沉淀 | 理由 |
|------|----------|------|
| 大站 / 优质站点的接口 | ✅ 沉淀 | 复用价值高 |
| 有反爬保护的接口 | ✅ 沉淀 | 破解成本高，必须保留 |
| 有参数加密的接口 | ✅ 沉淀 | 逆向分析成本高 |
| 小站 / 无反爬的简单接口 | ❌ 不沉淀 | 重新探索成本低 |
| 临时性 / 一次性数据接口 | ❌ 不沉淀 | 无复用场景 |

---

## webcli 场景经验分类

> 本节专门针对通过 `webcli` 进行浏览器自动化操作时产生的经验，与上方爬虫经验体系共用同一目录结构，但分类和格式有所不同。

### 目录结构（webcli 场景）

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

### 格式规范

#### api 类经验

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

## 抓包方式
通过 `webcli network-requests` 或 `webcli network-response` 抓包获取。

## 请求示例
```python
# 完整可运行的请求示例
```

## 注意事项
- {频率限制、Token 有效期、加密参数等}
```

#### login 类经验

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
```python
# webcli 操作序列示例
target_id = ...
# 填写用户名
webcli fill {target_id} "#username" "your_username"
# 填写密码
webcli fill {target_id} "#password" "your_password"
# 点击登录
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
> - `sms.md` — 短信验证码登录（见下方模板）
> - `qrcode.md` — 扫码登录（见下方模板）

##### 短信验证码登录（sms.md）

```markdown
---
site: {域名}
category: login
status: verified
created_at: {YYYY-MM-DD}
updated_at: {YYYY-MM-DD}
---

# 短信验证码登录

## 登录流程
1. 打开登录页，选择"短信验证码"方式
2. 填写手机号，点击"获取验证码"
3. **等待用户提供验证码**（Agent 无法收取短信）
4. 填入验证码，点击登录

## 关键操作
\`\`\`bash
webcli fill <id> "#phone" "<手机号>"
webcli click <id> "#send-sms-btn"
# ⚠️ 此处必须暂停，告知用户提供验证码
# 用户提供后：
webcli fill <id> "#sms-code" "<用户提供的验证码>"
webcli click <id> "#login-btn"
\`\`\`

## 告知用户的话术
> "已发送短信验证码到你的手机，请提供收到的验证码，我来完成登录。"

## 关键选择器
| 元素 | 选择器 | 备注 |
|------|--------|------|
| 手机号输入框 | `{selector}` | |
| 发送验证码按钮 | `{selector}` | 有倒计时，60s 内不能重复点击 |
| 验证码输入框 | `{selector}` | |
| 登录按钮 | `{selector}` | |

## Cookie 获取
- 登录成功后通过 `webcli cookies <id>` 获取
- 关键 Cookie 字段：{列出关键字段名}
- Cookie 有效期：{有效期说明}

## 注意事项
- 验证码有效期通常为 5 分钟，超时需重新发送
- 短时间内多次发送可能触发风控
\`\`\`

##### 扫码登录（qrcode.md）

\`\`\`markdown
---
site: {域名}
category: login
status: verified
created_at: {YYYY-MM-DD}
updated_at: {YYYY-MM-DD}
---

# 扫码登录

## 登录流程
1. 打开登录页，选择"扫码登录"方式
2. 截图展示二维码给用户
3. **等待用户用手机扫码确认**
4. 轮询检测登录状态，成功后继续

## 关键操作
\`\`\`bash
# 1. 导航到登录页并截图展示二维码
webcli new <login-url>
webcli screenshot <id> /tmp/qrcode.png
# 将截图展示给用户，请求扫码

# 2. 等待登录成功（二维码通常有效期 3 分钟）
webcli wait <id> --text "<登录成功后页面出现的文字>" --timeout 180000

# 3. 登录成功后获取 Cookie
webcli cookies <id>
\`\`\`

## 告知用户的话术
> "已截图显示二维码，请用手机扫码并确认登录，完成后告诉我继续。"

## 二维码刷新
- 二维码有效期：{通常 3-5 分钟}
- 过期判断：{页面出现"二维码已过期"文字 / 二维码变灰}
- 刷新方式：`webcli reload <id>` 或点击刷新按钮

## Cookie 获取
- 登录成功后通过 `webcli cookies <id>` 获取
- 关键 Cookie 字段：{列出关键字段名}
- Cookie 有效期：{有效期说明，扫码登录通常较长}

## 注意事项
- 必须截图展示二维码，不能只告诉用户"请扫码"
- 等待超时后主动告知用户并提供刷新选项
\`\`\`

#### action 类经验

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

#### anti-crawl 类经验

```markdown
---
category: anti-crawl
status: verified
created_at: {YYYY-MM-DD}
updated_at: {YYYY-MM-DD}
---

# {反爬类型名称}

## 识别特征
- {如何判断遇到了这种反爬}

## 对抗方案
1. {方案一}
2. {方案二}

## 注意事项
- {成功率、副作用、适用范围等}
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

#### workflow 类经验

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
