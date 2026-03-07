# Feishu Notification API

## 接口概述

提供简单的 HTTP 端点用于向飞书发送文本消息。支持群聊和私聊两种模式，通过环境变量配置目标接收者。

**特点：**
- 双模式发送：直接消息 + Agent 处理队列
- 支持 Query 参数、JSON Body、纯文本 Body 三种传参方式
- 基于环境变量配置，无需动态指定接收者

---

## 基本信息

| 属性 | 值 |
|------|-----|
| **接口路径** | `POST /api/v1/notify/feishu` |
| **Content-Type** | `application/json` (推荐) 或 `text/plain` |
| **认证方式** | 无需认证（内部服务调用） |
| **超时时间** | 30 秒 |

---

## 环境变量配置

在调用接口前，必须配置以下环境变量之一：

| 环境变量 | 说明 | 示例 |
|----------|------|------|
| `FEISHU_NOTIFY_CHAT_ID` | 目标群聊 ID（优先级高） | `oc_xxxxxxxxxxxxxxxx` |
| `FEISHU_NOTIFY_OPEN_ID` | 目标用户 Open ID（私聊） | `ou_xxxxxxxxxxxxxxxx` |

**配置规则：**
- 如果同时设置 `CHAT_ID` 和 `OPEN_ID`，优先使用 `CHAT_ID`（群聊）
- 至少配置其中一个，否则接口返回 400 错误

---

## 请求参数

### Query 参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `message` | string | 条件必填 | 消息内容（可与 Body 二选一） |
| `source` | string | 可选 | 消息来源标识，默认 `System` |

### Body 参数（JSON）

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `message` | string | 条件必填 | 消息内容 |
| `source` | string | 可选 | 消息来源标识 |

### Body 参数（纯文本）

直接发送纯文本，接口会将整个 Body 作为 `message` 处理。

---

## 请求示例

### 示例 1：Query 参数（最简单）

```bash
curl -X POST "http://localhost:8000/api/v1/notify/feishu?message=服务器CPU使用率超过90%&source=Zabbix"
```

### 示例 2：JSON Body（推荐）

```bash
curl -X POST http://localhost:8000/api/v1/notify/feishu \
  -H "Content-Type: application/json" \
  -d '{
    "message": "构建失败：单元测试未通过",
    "source": "GitLab-CI"
  }'
```

### 示例 3：管道输入（适合脚本）

```bash
echo "磁盘空间不足" | curl -X POST -d @- http://localhost:8000/api/v1/notify/feishu
```

### 示例 4：Python 调用

```python
import requests
import os

# 设置环境变量（实际应在系统级别配置）
os.environ["FEISHU_NOTIFY_CHAT_ID"] = "oc_xxxxxxxxxxxxxxxx"

response = requests.post(
    "http://localhost:8000/api/v1/notify/feishu",
    json={
        "message": "生产环境出现错误",
        "source": "Sentry"
    }
)

result = response.json()
print(f"Code: {result['code']}, Message: {result['message']}")
```

---

## 响应格式

### 成功响应（200 OK）

```json
{
  "code": 0,
  "message": "Direct message sent and queued for agent processing"
}
```

**说明：**
- 消息已成功发送到飞书
- 消息已加入 Agent 处理队列（可通过 webhook 事件追踪）

### 错误响应

#### 400 Bad Request - 未配置环境变量

```json
{
  "code": 400,
  "message": "FEISHU_NOTIFY_CHAT_ID or FEISHU_NOTIFY_OPEN_ID not set"
}
```

#### 400 Bad Request - 消息为空

```json
{
  "code": 400,
  "message": "Message is required"
}
```

#### 503 Service Unavailable - 飞书频道未启动

```json
{
  "code": 503,
  "message": "Feishu channel not available"
}
```

#### 500 Internal Server Error - 发送失败

```json
{
  "code": 500,
  "message": "Failed to send direct message"
}
```

或

```json
{
  "code": 500,
  "message": "Internal error: <具体错误信息>"
}
```

---

## 状态码对照表

| HTTP 状态码 | Code | 含义 | 处理建议 |
|-------------|------|------|----------|
| 200 | 0 | 成功 | 无需处理 |
| 400 | 400 | 配置缺失或参数错误 | 检查环境变量和请求参数 |
| 500 | 500 | 发送失败或内部错误 | 查看服务端日志，重试 |
| 503 | 503 | 飞书频道不可用 | 检查飞书频道配置和连接状态 |

---

## 内部实现细节

### 消息发送流程

```
┌─────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  接收请求    │ → │  验证环境变量    │ → │  构建消息内容    │
└─────────────┘    └─────────────────┘    └─────────────────┘
                                                   ↓
┌─────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  返回响应    │ ← │  Agent 处理队列  │ ← │  发送直接消息    │
└─────────────┘    └─────────────────┘    └─────────────────┘
```

### 消息格式

最终发送到飞书的消息格式：

```
[<source>] <message>
```

例如：
```
[Zabbix] 服务器CPU使用率超过90%
```

### 双模式发送机制

1. **直接消息发送**：调用 `FeishuChannel._send_text()` 立即发送
2. **Agent 处理**：构造模拟 webhook 事件，调用 `handle_webhook_event()` 让 Agent 处理

### 模拟 Webhook 事件结构

```json
{
  "event": {
    "message": {
      "message_id": "simulated_<uuid>_<timestamp>",
      "chat_id": "<chat_id or open_id>",
      "chat_type": "group" | "p2p",
      "message_type": "text",
      "content": "{\"text\": \"[Source] Message\"}"
    },
    "sender": {
      "sender_type": "user",
      "sender_id": {"open_id": "<open_id or chat_id>"},
      "name": "<source>",
      "nickname": "<source>"
    }
  }
}
```

---

## Hook 开发指南

### 1. 请求前验证 Hook (PreToolUse)

用于验证请求参数和环境变量：

```yaml
---
name: feishu-notify-validator
description: |
  验证飞书通知接口的请求参数和环境变量配置。
  在请求处理前拦截，检查必要配置是否存在。
trigger:
  event: PreToolUse
  filter: |
    tool.name == "notify_feishu" or
    (tool.name == "fastapi_route" and tool.args.path == "/api/v1/notify/feishu")
---

请检查以下内容：

1. 环境变量检查：
   - FEISHU_NOTIFY_CHAT_ID 或 FEISHU_NOTIFY_OPEN_ID 是否已设置
   - 如果都未设置，返回明确的错误信息

2. 请求参数检查：
   - message 参数是否为空或仅包含空白字符
   - source 参数是否超长（建议限制 50 字符）

3. 安全检查：
   - message 是否包含潜在危险内容（如 HTML 脚本）
   - 消息长度是否超过飞书限制（建议 4000 字符）
```

### 2. 响应后处理 Hook (PostToolUse)

用于记录日志或触发后续操作：

```yaml
---
name: feishu-notify-logger
description: |
  记录飞书通知接口的调用日志，用于审计和监控。
  在请求完成后触发，记录请求和响应信息。
trigger:
  event: PostToolUse
  filter: |
    tool.name == "notify_feishu" or
    (tool.name == "fastapi_route" and tool.args.path == "/api/v1/notify/feishu")
---

请记录以下信息：

1. 请求信息：
   - 请求时间
   - source 标识
   - 消息长度
   - 目标类型（chat_id / open_id）

2. 响应信息：
   - HTTP 状态码
   - 业务 code
   - 处理结果

3. 告警条件：
   - 如果 code != 0，记录为错误日志
   - 如果连续失败超过阈值，触发告警通知
```

### 3. 消息内容过滤 Hook

用于过滤或修改消息内容：

```yaml
---
name: feishu-notify-filter
description: |
  过滤和清理飞书通知消息内容。
  移除敏感信息，格式化消息，确保符合安全规范。
trigger:
  event: PreToolUse
  filter: |
    tool.name == "notify_feishu"
---

处理规则：

1. 敏感信息过滤：
   - 检测并脱敏：手机号、身份证号、银行卡号、Token/Key
   - 替换规则：保留前 3 位和后 4 位，中间用 *** 替代

2. 内容格式化：
   - 移除 HTML 标签
   - 转义特殊字符
   - 限制消息长度（超过截断并添加...）

3. 关键词过滤：
   - 检查禁止发送的关键词列表
   - 如发现，阻断请求并记录安全日志
```

---

## 最佳实践

### 1. 环境变量管理

推荐使用 `.env` 文件或系统级环境变量：

```bash
# .env 文件
FEISHU_NOTIFY_CHAT_ID=oc_xxxxxxxxxxxxxxxx
```

启动时加载：
```bash
export $(cat .env | xargs) && copaw app
```

### 2. 监控告警集成

Prometheus Alertmanager 配置示例：

```yaml
receivers:
  - name: 'feishu-notify'
    webhook_configs:
      - url: 'http://localhost:8000/api/v1/notify/feishu'
        send_resolved: true
        http_config:
          headers:
            Content-Type: application/json
        title: '{{ template "default.title" . }}'
        message: '{{ template "default.message" . }}'
```

### 3. 重试机制

客户端重试建议：

```python
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=lambda e: isinstance(e, requests.exceptions.RequestException)
)
def notify_feishu(message, source):
    response = requests.post(
        "http://localhost:8000/api/v1/notify/feishu",
        json={"message": message, "source": source},
        timeout=30
    )
    response.raise_for_status()
    return response.json()
```

### 4. 日志追踪

每个消息都有唯一标识：

- **直接消息**：通过飞书 API 返回的 `message_id` 追踪
- **Agent 处理**：模拟事件的 `message_id` 格式为 `simulated_<uuid>_<timestamp>`

---

## 常见问题

### Q: 如何获取 chat_id 或 open_id？

A:
- **chat_id**: 在飞书群设置中查看，或通过飞书开放平台 API 获取
- **open_id**: 通过飞书开放平台用户管理 API 获取

### Q: 消息发送成功但 Agent 没有处理？

A: 检查：
1. FeishuChannel 是否正确配置并启动
2. `handle_webhook_event` 方法是否可用
3. 查看服务端日志确认 Agent 处理状态

### Q: 如何发送富文本或卡片消息？

A: 当前接口仅支持纯文本。如需富文本，建议：
1. 使用飞书机器人直接调用 Open API
2. 扩展此接口，添加 `msg_type` 参数支持 `interactive` 卡片

### Q: 消息长度有限制吗？

A:
- 接口层：无硬性限制
- 飞书 API：文本消息建议不超过 4000 字符
- 超长消息会被截断或分片发送

---

## 相关接口

| 接口 | 说明 |
|------|------|
| `POST /api/v1/feishu/webhook` | 飞书 Webhook 回调（事件订阅） |
| `WS /ws/feishu` | 飞书 WebSocket 长连接 |

---

## 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2024-XX-XX | 初始版本，支持基础文本通知 |
