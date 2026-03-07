---
name: lark-webhook-guide
description: |
  通用 Lark（飞书）机器人 Webhook 接入指南。适用于任何需要推送消息到 Lark 的系统：
  CI/CD 流水线、监控系统、业务告警、自动化脚本、数据报表等。

  当用户需要：
  - 接入 Lark/飞书机器人通知
  - 配置 Webhook 发送卡片消息
  - 使用 Card v2 Schema 2.0 格式
  - 在消息中显示 Markdown 内容
  - 排查 Lark 消息发送问题
  时使用此 Skill。
---

# Lark 机器人 Webhook 通用接入指南

## 概述

本指南帮助你将 **任何系统** 接入 Lark（飞书）机器人通知，支持丰富的卡片消息格式。

**适用场景**：
- CI/CD 流水线通知（Jenkins、GitLab CI、GitHub Actions）
- 监控告警（Prometheus、Zabbix、Datadog）
- 业务系统通知（订单、审批、异常告警）
- 数据报表推送（日报、周报、统计报表）
- 自动化脚本通知（定时任务、数据同步）

## 1. Webhook 地址配置

### 1.1 获取 Webhook URL

1. 在 Lark 群聊中，点击「设置」→「群机器人」→「添加机器人」
2. 选择「自定义机器人」（Custom Bot）
3. 复制 Webhook URL：
   ```
   https://open.larksuite.com/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```

### 1.2 安全设置（可选）

若启用签名验证，需计算签名：

**Python 示例**：
```python
import base64
import hashlib
import hmac
import time

def generate_sign(secret: str) -> tuple[str, str]:
    """生成飞书签名和时间戳."""
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()
    sign = base64.b64encode(hmac_code).decode("utf-8")
    return timestamp, sign

# 使用
timestamp, sign = generate_sign("your-secret-key")
```

### 1.3 HTTP 请求基础

```http
POST https://open.larksuite.com/open-apis/bot/v2/hook/xxxxx
Content-Type: application/json

{...payload...}
```

**响应格式**：
```json
{
  "code": 0,
  "data": {},
  "msg": "success"
}
```

## 2. 卡片消息格式

### 2.1 Card v2 Schema 2.0 结构

```json
{
  "msg_type": "interactive",
  "card": {
    "schema": "2.0",
    "config": {
      "update_multi": true
    },
    "header": {
      "template": "green",
      "title": {
        "tag": "plain_text",
        "content": "✅ 部署成功"
      }
    },
    "body": {
      "elements": [
        {
          "tag": "div",
          "text": {
            "tag": "lark_md",
            "content": "**项目**: my-app\n**版本**: v1.2.3"
          }
        }
      ]
    }
  }
}
```

### 2.2 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `msg_type` | string | 是 | 固定值 `"interactive"` |
| `card.schema` | string | 是 | 固定值 `"2.0"` |
| `card.config.update_multi` | boolean | 是 | 固定值 `true` |
| `card.header.template` | string | 否 | 头部颜色（见下表） |
| `card.header.title` | object | 否 | 卡片标题 |
| `card.body.elements` | array | 是 | 内容元素列表 |

### 2.3 头部颜色模板

| 模板值 | 颜色 | 适用场景 |
|--------|------|----------|
| `green` | 🟢 绿色 | 成功、完成 |
| `red` | 🔴 红色 | 错误、告警 |
| `blue` | 🔵 蓝色 | 普通通知 |
| `orange` | 🟠 橙色 | 警告、进行中 |
| `indigo` | 🟣 靛蓝 | 信息、处理中 |
| `grey` | ⚪ 灰色 | 禁用、已取消 |

## 3. Schema 2.0 完整规范

### 3.1 基础元素类型

#### 文本元素（div + lark_md）

```json
{
  "tag": "div",
  "text": {
    "tag": "lark_md",
    "content": "**粗体** *斜体* ~~删除线~~"
  }
}
```

#### 纯文本（plain_text）

```json
{
  "tag": "div",
  "text": {
    "tag": "plain_text",
    "content": "不支持 Markdown 的纯文本"
  }
}
```

#### 图片（img）

```json
{
  "tag": "img",
  "img_key": "img_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "alt": {
    "tag": "plain_text",
    "content": "图片描述"
  }
}
```

> **注意**：`img_key` 需要先上传图片到 Lark 获取。

#### 分割线（hr）

```json
{
  "tag": "hr"
}
```

### 3.2 布局组件

#### 多列布局（column_set）

```json
{
  "tag": "column_set",
  "flex_mode": "none",
  "background_style": "default",
  "columns": [
    {
      "tag": "column",
      "width": "weighted",
      "weight": 1,
      "elements": [
        {
          "tag": "div",
          "text": {
            "tag": "lark_md",
            "content": "**左栏内容**"
          }
        }
      ]
    },
    {
      "tag": "column",
      "width": "weighted",
      "weight": 1,
      "elements": [
        {
          "tag": "div",
          "text": {
            "tag": "lark_md",
            "content": "**右栏内容**"
          }
        }
      ]
    }
  ]
}
```

#### 字段列表（fields）

```json
{
  "tag": "div",
  "fields": [
    {
      "is_short": true,
      "text": {
        "tag": "lark_md",
        "content": "**字段1**: 值1"
      }
    },
    {
      "is_short": true,
      "text": {
        "tag": "lark_md",
        "content": "**字段2**: 值2"
      }
    }
  ]
}
```

### 3.3 交互组件

#### 按钮（button）

```json
{
  "tag": "action",
  "actions": [
    {
      "tag": "button",
      "text": {
        "tag": "plain_text",
        "content": "查看详情"
      },
      "type": "primary",
      "url": "https://example.com/detail"
    },
    {
      "tag": "button",
      "text": {
        "tag": "plain_text",
        "content": "忽略"
      },
      "type": "default"
    }
  ]
}
```

**按钮类型**：`primary`（主按钮）、`default`（默认）、`danger`（危险）

## 4. Markdown 支持

### 4.1 支持的语法

| 语法 | 示例 | 说明 |
|------|------|------|
| 标题 | `# H1` `## H2` | 1-6级标题 |
| 粗体 | `**text**` | 加粗 |
| 斜体 | `*text*` | 倾斜 |
| 删除线 | `~~text~~` | 删除线 |
| 代码行 | `` `code` `` | 行内代码 |
| 代码块 | ```` ```python ```` | 多行代码 |
| 链接 | `[text](url)` | 超链接 |
| 图片 | `![alt](img_key)` | 图片（需上传） |
| 引用 | `> text` | 引用块 |
| 无序列表 | `- item` | 列表 |
| 有序列表 | `1. item` | 编号列表 |
| 表格 | `\|a\|b\|` | 表格 |
| 分割线 | `---` | 分隔线 |
| 提及 | `<at id=xxx>` | @用户 |
| 全体 | `<at id=all>` | @所有人 |

### 4.2 Markdown 示例

```json
{
  "tag": "div",
  "text": {
    "tag": "lark_md",
    "content": "# 部署通知\n\n**项目**: `my-service`\n**环境**: **生产环境**\n**版本**: v2.1.0\n\n## 变更内容\n\n- ✨ 新增用户认证功能\n- 🐛 修复数据同步问题\n- ⚡️ 优化查询性能\n\n## 部署结果\n\n| 服务 | 状态 | 耗时 |\n|------|------|------|\n| api-gateway | ✅ 成功 | 45s |\n| user-service | ✅ 成功 | 32s |\n| order-service | ✅ 成功 | 28s |\n\n> 部署时间: 2024-01-15 14:30:00\n\n[查看详细日志](https://jenkins.example.com/job/123)"
  }
}
```

## 5. 完整示例

### 5.1 CI/CD 部署通知

```python
import requests
import json

def send_deploy_notification(
    webhook_url: str,
    project: str,
    version: str,
    status: str,  # "success" | "failed"
    duration: str,
    changes: list,
    logs_url: str = None
):
    """发送部署通知到 Lark."""

    emoji = "✅" if status == "success" else "❌"
    template = "green" if status == "success" else "red"
    title = "部署成功" if status == "success" else "部署失败"

    changes_md = "\n".join([f"- {c}" for c in changes]) if changes else "- 无变更"

    content = f"""**项目**: {project}
**版本**: `{version}`
**状态**: {emoji} {title}
**耗时**: {duration}

**变更内容**:
{changes_md}"""

    if logs_url:
        content += f"\n\n[查看日志]({logs_url})"

    payload = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "template": template,
                "title": {
                    "tag": "plain_text",
                    "content": f"{emoji} {project} {title}"
                }
            },
            "body": {
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": content
                        }
                    }
                ]
            }
        }
    }

    response = requests.post(
        webhook_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=10
    )
    response.raise_for_status()
    return response.json()

# 使用示例
send_deploy_notification(
    webhook_url="https://open.larksuite.com/open-apis/bot/v2/hook/xxxxx",
    project="user-service",
    version="v2.1.0",
    status="success",
    duration="2m 34s",
    changes=["新增登录接口", "修复缓存问题"],
    logs_url="https://jenkins.example.com/job/123"
)
```

### 5.2 监控告警通知

```python
def send_alert_notification(
    webhook_url: str,
    alert_name: str,
    severity: str,  # "critical" | "warning" | "info"
    service: str,
    message: str,
    metrics: dict,
    action_url: str = None
):
    """发送监控告警到 Lark."""

    template_map = {
        "critical": "red",
        "warning": "orange",
        "info": "blue"
    }
    emoji_map = {
        "critical": "🚨",
        "warning": "⚠️",
        "info": "ℹ️"
    }

    template = template_map.get(severity, "grey")
    emoji = emoji_map.get(severity, "📢")

    metrics_md = "\n".join([f"**{k}**: {v}" for k, v in metrics.items()])

    content = f"""**告警名称**: {alert_name}
**服务**: {service}
**级别**: {emoji} {severity.upper()}

**告警信息**:
{message}

**指标数据**:
{metrics_md}"""

    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": content
            }
        }
    ]

    if action_url:
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "处理告警"},
                    "type": "primary",
                    "url": action_url
                }
            ]
        })

    payload = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "template": template,
                "title": {
                    "tag": "plain_text",
                    "content": f"{emoji} {alert_name}"
                }
            },
            "body": {"elements": elements}
        }
    }

    response = requests.post(
        webhook_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=10
    )
    return response.json()
```

### 5.3 数据报表推送

```python
def send_report_notification(
    webhook_url: str,
    report_name: str,
    report_date: str,
    summary_metrics: dict,
    top_items: list,
    detail_url: str = None
):
    """发送数据报表到 Lark."""

    summary_md = " | ".join([f"**{k}**: {v}" for k, v in summary_metrics.items()])

    items_md = "\n".join([
        f"| {i+1} | {item['name']} | {item['value']} |"
        for i, item in enumerate(top_items[:5])
    ])

    content = f"""{summary_md}

---

**TOP 5 排行**:

| 排名 | 名称 | 数值 |
|------|------|------|
{items_md}"""

    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": content
            }
        }
    ]

    if detail_url:
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "查看完整报表"},
                    "type": "primary",
                    "url": detail_url
                }
            ]
        })

    payload = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": f"📊 {report_name} - {report_date}"
                }
            },
            "body": {"elements": elements}
        }
    }

    response = requests.post(
        webhook_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=10
    )
    return response.json()
```

## 6. 多语言示例

### 6.1 cURL

```bash
#!/bin/bash

WEBHOOK_URL="https://open.larksuite.com/open-apis/bot/v2/hook/xxxxx"

payload=$(cat <<EOF
{
  "msg_type": "interactive",
  "card": {
    "schema": "2.0",
    "config": {"update_multi": true},
    "header": {
      "template": "green",
      "title": {"tag": "plain_text", "content": "✅ 构建成功"}
    },
    "body": {
      "elements": [
        {
          "tag": "div",
          "text": {
            "tag": "lark_md",
            "content": "**项目**: my-app\\n**版本**: v1.0.0"
          }
        }
      ]
    }
  }
}
EOF
)

curl -X POST "$WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -d "$payload"
```

### 6.2 JavaScript/Node.js

```javascript
const axios = require('axios');

async function sendLarkNotification(webhookUrl, payload) {
  try {
    const response = await axios.post(webhookUrl, payload, {
      headers: { 'Content-Type': 'application/json' },
      timeout: 10000
    });

    if (response.data.code !== 0) {
      throw new Error(`Lark API error: ${response.data.msg}`);
    }

    return response.data;
  } catch (error) {
    console.error('Failed to send notification:', error.message);
    throw error;
  }
}

// 使用
const payload = {
  msg_type: "interactive",
  card: {
    schema: "2.0",
    config: { update_multi: true },
    header: {
      template: "green",
      title: { tag: "plain_text", content: "✅ 部署成功" }
    },
    body: {
      elements: [{
        tag: "div",
        text: {
          tag: "lark_md",
          content: "**项目**: my-app\n**版本**: v1.0.0"
        }
      }]
    }
  }
};

sendLarkNotification('https://open.larksuite.com/...', payload);
```

### 6.3 Go

```go
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

type LarkCard struct {
	MsgType string `json:"msg_type"`
	Card    struct {
		Schema string `json:"schema"`
		Config struct {
			UpdateMulti bool `json:"update_multi"`
		} `json:"config"`
		Header struct {
			Template string `json:"template"`
			Title    struct {
				Tag     string `json:"tag"`
				Content string `json:"content"`
			} `json:"title"`
		} `json:"header"`
		Body struct {
			Elements []interface{} `json:"elements"`
		} `json:"body"`
	} `json:"card"`
}

func sendLarkNotification(webhookURL string, payload LarkCard) error {
	jsonData, err := json.Marshal(payload)
	if err != nil {
		return err
	}

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Post(webhookURL, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP error: %d", resp.StatusCode)
	}

	return nil
}
```

### 6.4 Java

```java
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.URI;
import java.time.Duration;

public class LarkWebhookClient {
    private static final ObjectMapper mapper = new ObjectMapper();
    private static final HttpClient client = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build();

    public static void sendNotification(String webhookUrl, Object payload) throws Exception {
        String jsonPayload = mapper.writeValueAsString(payload);

        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create(webhookUrl))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(jsonPayload))
            .build();

        HttpResponse<String> response = client.send(request,
            HttpResponse.BodyHandlers.ofString());

        if (response.statusCode() != 200) {
            throw new RuntimeException("HTTP error: " + response.statusCode());
        }
    }
}
```

## 7. 常见问题

### Q1: 消息发送成功但群里看不到？

检查响应中的 `code` 字段：
- `code: 0` - 发送成功
- `code: 10002` - 格式错误（检查 JSON 结构）
- `code: 19002` - 参数错误（检查字段值）

### Q2: Markdown 格式不生效？

确保：
1. 使用 `"tag": "lark_md"` 而不是 `plain_text`
2. Schema 设置为 `"2.0"`
3. Markdown 语法正确（注意转义特殊字符）

### Q3: 如何发送给特定人？

在内容中使用 `@`：
```json
{
  "tag": "lark_md",
  "content": "<at id=ou_xxxxxx>用户名</at> 请处理"
}
```

或使用 `@all` 通知所有人：
```json
{
  "tag": "lark_md",
  "content": "<at id=all>所有人</at> 重要通知"
}
```

### Q4: 消息太长被截断？

Lark 对消息大小有限制：
- 文本内容建议控制在 4096 字符以内
- 超长内容建议：
  1. 精简内容，只展示关键信息
  2. 添加「查看详情」按钮链接到完整内容
  3. 分段发送多条消息

### Q5: 如何更新已发送的消息？

需要：
1. 发送时保存返回的 `message_id`
2. 使用更新 API 传入 `message_id`

```python
# 发送时获取 message_id
response = requests.post(webhook_url, json=payload)
result = response.json()
message_id = result.get("data", {}).get("message_id")

# 更新消息
update_payload = {
    "msg_type": "interactive",
    "card": {...},  # 新内容
    "message_id": message_id  # 原消息 ID
}
```

## 8. 最佳实践

1. **错误处理**：始终检查 HTTP 状态码和响应中的 `code` 字段
2. **超时设置**：设置合理的超时时间（建议 10 秒）
3. **重试机制**：网络失败时实现指数退避重试
4. **敏感信息**：不要将 Webhook URL 硬编码在代码中，使用环境变量
5. **日志记录**：记录发送内容和响应，便于排查问题
6. **降级策略**：Lark 失败时考虑备用通知渠道（邮件、短信）
