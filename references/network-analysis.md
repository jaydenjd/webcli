# 网络请求分析指南

何时加载：需要分析页面接口、抓包、查看请求参数/响应数据、研究加密参数时。

---

## 基本抓包流程

```bash
# 1. 打开目标页面（或使用已有 tab）
TARGET=$(webcli new https://example.com --id-only)

# 2. 开始抓包
webcli network-start $TARGET

# 3. 触发页面操作（点击、滚动、搜索等）
webcli click $TARGET "button.search"

# 4. 列出捕获的请求（过滤 XHR/Fetch，最近 20 条）
webcli network-requests $TARGET --type xhr,fetch --limit 20

# 5. 查看某个请求的完整详情（含响应体）
webcli network-request $TARGET <requestId>

# 6. 清空抓包记录（重新开始）
webcli network-clear $TARGET
```

---

## 过滤请求

```bash
# 按 URL 关键词过滤
webcli network-requests $TARGET --filter /api/

# 按方法过滤
webcli network-requests $TARGET --method POST

# 按状态码过滤
webcli network-requests $TARGET --status 2xx
webcli network-requests $TARGET --status 200

# 组合过滤 + 限制条数
webcli network-requests $TARGET --type xhr,fetch --filter /api/ --method POST --limit 50
```

---

## 单个请求详情字段说明

`webcli network-request` 返回：

| 字段 | 说明 |
|------|------|
| `url` | 完整请求 URL（含 query 参数） |
| `method` | HTTP 方法（GET/POST/PUT...） |
| `requestHeaders` | 请求头（含 Cookie、Authorization、签名头等） |
| `postData` | POST 请求体原始字符串（含加密参数的**加密后值**） |
| `status` | HTTP 状态码 |
| `responseHeaders` | 响应头 |
| `responseBody` | 完整响应体（JSON、HTML 等） |
| `responseBodyBase64` | 响应体是否为 base64 编码（二进制响应时为 true） |

---

## 加密参数分析

`network-request` 只能看到加密后的参数值。要分析加密逻辑，需在 JS 层面介入：

### 方式一：直接调用页面内的加密函数

```bash
# 先找到加密函数名（通过 Sources 面板或搜索）
webcli eval $TARGET "window.__sign('test_data')"
webcli eval $TARGET "window.encrypt({uid: 123})"
```

### 方式二：Hook XHR/Fetch，在发出前拦截明文参数

```bash
# Hook fetch，打印发出前的原始参数
webcli eval $TARGET "
const orig = window.fetch;
window.__intercepted = [];
window.fetch = function(url, opts) {
  window.__intercepted.push({url, body: opts?.body});
  return orig.call(this, url, opts);
};"

# 触发操作后，读取拦截到的数据
webcli eval $TARGET "JSON.stringify(window.__intercepted)"
```

### 方式三：通过 console 日志观察

```bash
# 初始化 console 拦截
webcli console $TARGET

# 在页面 JS 里打印加密前的数据（需要先找到注入点）
webcli eval $TARGET "console.log('params:', JSON.stringify(window.__lastParams))"

# 读取 console 输出
webcli console $TARGET
```

---

## 能力边界

| 场景 | 支持情况 |
|------|---------|
| 查看请求 URL、headers、body | ✅ 完整支持 |
| 查看响应 JSON 数据 | ✅ 完整支持 |
| 查看加密后的参数值 | ✅ 支持（postData 字段） |
| 分析加密参数的生成逻辑 | ⚠️ 需配合 eval hook JS |
| WebSocket 消息 | ❌ 不支持 |
| 实时流式响应（SSE） | ⚠️ 仅在请求完成后可读 body |
| 二进制响应（protobuf 等） | ⚠️ 返回 base64，需自行解码 |

---

## 注意事项

- `network-start` 必须在触发请求**之前**调用，否则捕获不到
- `network-request` 获取响应体需要等请求完成（`hasBody: true`）才有数据
- 抓包数据存在内存中，Proxy 重启后清空
- 对于需要登录态的接口，直连用户 Chrome 天然携带 Cookie，无需额外处理
