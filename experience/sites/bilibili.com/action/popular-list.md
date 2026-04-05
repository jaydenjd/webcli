---
site: bilibili.com
category: action
status: verified
created_at: 2026-04-05
updated_at: 2026-04-05
---

## 更新（2026-04-05）
- 当前 URL `https://www.bilibili.com/v/popular/all` 页面只加载 **20 条** 内容，无懒加载机制
- 无分页按钮，单页 20 条为固定数量
- 选择器 `.video-card` 稳定可用，`webcli eval` 提取方式仍然有效
- API `https://api.bilibili.com/x/web-interface/popular?ps=20&pn=1` 可用但含 WBI 签名，DOM 提取更简单
