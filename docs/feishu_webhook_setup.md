# Feishu (Lark) Webhook 设置指南

本文档介绍如何配置 CoPaw 使用 HTTP Webhook 接收飞书消息，作为 WebSocket 长连接的替代方案。

## 功能概述

CoPaw 现在支持两种方式接收飞书消息：

1. **WebSocket 长连接**（默认）：适合本地开发或没有公网 IP 的环境
2. **HTTP Webhook**（新增）：适合部署在有公网 IP 的服务器上

两种模式可以同时启用，但请注意可能会收到重复消息（建议使用 message_id 去重）。

## 配置步骤

### 1. 修改配置文件

编辑 `~/.copaw/config.json`，在 `channels.feishu` 部分添加 webhook 配置：

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "app_id": "cli_xxxxx",
      "app_secret": "xxxxxxxx",
      "encrypt_key": "",
      "verification_token": "",
      "media_dir": "~/.copaw/media",
      "webhook_enabled": true,
      "webhook_path": "/webhook/feishu",
      "webhook_encrypt_key": "",
      "webhook_verification_token": ""
    }
  }
}
```

### 2. 飞书开发者后台配置

1. 登录 [飞书开发者平台](https://open.feishu.cn/)
2. 进入你的应用管理页面
3. 点击「事件与回调」
4. 在「订阅方式」中选择「HTTP 推送」
5. 填写请求网址：`https://your-domain.com/webhook/feishu`
6. 点击「保存」后，飞书会发送 challenge 验证请求
7. 验证成功后即可正常接收消息

### 3. 安全设置（推荐）

#### 签名验证

为了防止伪造请求，建议启用签名验证：

1. 在飞书开发者后台「事件与回调」页面获取 **Verification Token**
2. 将 token 填入配置文件的 `webhook_verification_token` 字段
3. 重启 CoPaw 使配置生效

#### 加密传输

如果需要加密传输：

1. 在飞书开发者后台启用「加密密钥」
2. 将加密密钥填入配置文件的 `webhook_encrypt_key` 字段
3. CoPaw 会自动解密请求体

### 4. 健康检查

启动 CoPaw 后，可以访问健康检查端点验证 webhook 是否正常工作：

```bash
curl https://your-domain.com/webhook/feishu/health
```

预期返回：
```json
{
  "status": "ok",
  "webhook_enabled": true
}
```

## 配置选项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `webhook_enabled` | bool | false | 是否启用 webhook 接收方式 |
| `webhook_path` | string | "/webhook/feishu" | webhook 端点路径 |
| `webhook_encrypt_key` | string | "" | 用于解密请求体的密钥（可选） |
| `webhook_verification_token` | string | "" | 用于验证请求签名的 token（可选） |

## 注意事项

1. **消息重复**：如果同时启用 WebSocket 和 Webhook，可能收到重复消息。CoPaw 已内置 message_id 去重机制。

2. **网络要求**：Webhook 需要 CoPaw 部署在有公网 IP 的服务器上，且能被飞书服务器访问。

3. **路径冲突**：如果修改了 `webhook_path`，请确保与飞书开发者后台配置的 URL 一致。

4. **向后兼容**：不启用 webhook 时，CoPaw 仍使用原有的 WebSocket 方式接收消息，完全向后兼容。

## 故障排查

### Webhook 验证失败

- 检查 `webhook_enabled` 是否设置为 `true`
- 检查 CoPaw 是否已重启以加载新配置
- 查看日志确认 webhook 路由是否注册成功

### 签名验证失败

- 确认 `webhook_verification_token` 与飞书后台一致
- 检查是否有额外的空格或换行符

### 收不到消息

- 检查防火墙是否放行了 webhook 端口
- 确认配置的 URL 可被公网访问
- 查看 CoPaw 日志中的错误信息

## 技术参考

- 飞书事件订阅文档：https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-guide
- 请求签名算法：HMAC-SHA256
- 支持的加密方式：AES-256-CBC（如需完整支持请联系开发者）
