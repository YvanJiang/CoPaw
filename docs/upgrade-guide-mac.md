# CoPaw macOS 升级指南

本文档指导 macOS 用户如何安全地升级 CoPaw 到最新版本。

## 环境准备

### 1. 检查 Python 版本

CoPaw 需要 Python 3.10-3.14:

```bash
python3 --version
```

如果版本低于 3.10，请使用 Homebrew 升级:

```bash
brew install python@3.12
```

### 2. 安装/更新依赖工具

```bash
# 确保 Homebrew 是最新的
brew update

# 安装必要工具（如尚未安装）
brew install git
```

## 备份步骤

在升级前，请备份以下数据：

### 1. 配置文件

```bash
# 备份整个配置目录
cp -R ~/.copaw ~/.copaw.backup.$(date +%Y%m%d)

# 或使用 tar 打包
tar czvf ~/copaw-backup-$(date +%Y%m%d).tar.gz ~/.copaw
```

### 2. 重要配置文件清单

- `~/.copaw/config.json` - 主配置文件
- `~/.copaw/providers.json` - 模型提供商配置
- `~/.copaw/channels.json` - 频道配置
- `~/.copaw/customized_skills/` - 自定义技能
- `~/.copaw/active_skills/` - 启用的技能

### 3. 导出关键配置（可选）

```bash
# 查看当前配置
copaw config show > ~/copaw-config-export-$(date +%Y%m%d).txt
```

## 升级步骤

### 方法一：使用 pip 升级（推荐）

```bash
# 1. 激活虚拟环境（如果使用）
source ~/copaw-venv/bin/activate

# 2. 升级 CoPaw
pip install --upgrade copaw

# 3. 验证安装
copaw --version
```

### 方法二：从源码升级

```bash
# 1. 进入 CoPaw 源码目录
cd /path/to/CoPaw

# 2. 拉取最新代码
git pull origin main

# 3. 重新安装依赖
pip install -e ".[dev]"

# 4. 验证安装
copaw --version
```

### 方法三：全新安装

如果升级遇到问题，可以全新安装：

```bash
# 1. 卸载旧版本
pip uninstall copaw

# 2. 清理缓存
pip cache purge

# 3. 安装新版本
pip install copaw

# 4. 初始化配置（保留现有配置则跳过）
copaw init --defaults
```

## 配置迁移

### v0.0.6 重要变更

#### 1. 新增 ToolsConfig 配置

`config.json` 新增 `tools` 字段用于管理内置工具：

```json
{
  "tools": {
    "builtin_tools": {
      "execute_shell_command": {
        "name": "execute_shell_command",
        "enabled": true,
        "description": "Execute shell commands"
      },
      "read_file": {
        "name": "read_file",
        "enabled": true,
        "description": "Read file contents"
      },
      "write_file": {
        "name": "write_file",
        "enabled": true,
        "description": "Write content to file"
      },
      "edit_file": {
        "name": "edit_file",
        "enabled": true,
        "description": "Edit file using find-and-replace"
      },
      "browser_use": {
        "name": "browser_use",
        "enabled": true,
        "description": "Browser automation and web interaction"
      },
      "desktop_screenshot": {
        "name": "desktop_screenshot",
        "enabled": true,
        "description": "Capture desktop screenshots"
      },
      "send_file_to_user": {
        "name": "send_file_to_user",
        "enabled": true,
        "description": "Send files to user"
      },
      "get_current_time": {
        "name": "get_current_time",
        "enabled": true,
        "description": "Get current date and time"
      }
    }
  }
}
```

#### 2. 依赖变更

新增依赖：
- `aiofiles>=24.1.0` - 异步文件操作
- `paho-mqtt>=2.0.0` - MQTT 协议支持
- `matrix-nio>=0.24.0` - Matrix 频道支持

移除依赖：
- `Pillow>=10.0.0` - 已移除
- `cryptography>=3.0` - 已移除

#### 3. 新增 Matrix 和 Mattermost 频道

配置示例：

```json
{
  "channels": {
    "matrix": {
      "enabled": false,
      "homeserver": "https://matrix.org",
      "user_id": "@username:matrix.org",
      "access_token": ""
    },
    "mattermost": {
      "enabled": false,
      "url": "https://mattermost.example.com",
      "bot_token": "",
      "media_dir": "~/.copaw/media/mattermost"
    }
  }
}
```

#### 4. 飞书频道新增 `require_mention` 选项

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "app_id": "",
      "app_secret": "",
      "require_mention": false
    }
  }
}
```

## 验证步骤

### 1. 检查版本

```bash
copaw --version
```

### 2. 验证配置

```bash
# 检查配置文件语法
copaw config validate

# 查看当前配置
copaw config show
```

### 3. 启动应用测试

```bash
# 前台启动（便于查看日志）
copaw app

# 或使用调试模式
copaw app --debug
```

### 4. 测试基本功能

- 发送一条测试消息到任意频道
- 验证 Agent 是否能正常回复
- 测试一个简单工具（如获取当前时间）

### 5. 检查日志

```bash
# 查看日志
tail -f ~/.copaw/logs/copaw.log
```

## 常见问题

### Q: 升级后配置文件不兼容

A: 删除旧配置文件，重新初始化：

```bash
mv ~/.copaw/config.json ~/.copaw/config.json.bak
copaw init --defaults
```

### Q: 依赖冲突

A: 创建新的虚拟环境：

```bash
python3 -m venv ~/copaw-venv-new
source ~/copaw-venv-new/bin/activate
pip install copaw
```

### Q: macOS 权限问题

A: 如果遇到权限错误，尝试：

```bash
# 修复权限
sudo chown -R $(whoami) ~/.copaw

# 如使用系统 Python，可能需要：
pip install --user copaw
```

### Q: NumPy 版本警告

A: 如果遇到 NumPy 版本警告：

```bash
pip install "numpy<2"
```

### Q: 飞书频道升级后无法使用

A: 检查 `config.json` 中是否包含 `require_mention` 字段，如缺失请手动添加：

```json
"feishu": {
  "require_mention": false
}
```

## 回滚步骤

如果升级后遇到问题，可以回滚：

```bash
# 1. 停止 CoPaw
pkill -f copaw

# 2. 恢复配置
cp -R ~/.copaw.backup.YYYYMMDD ~/.copaw

# 3. 降级到旧版本
pip install copaw==0.0.5  # 或其他旧版本

# 4. 重新启动
copaw app
```

## 获取帮助

如遇到问题：

1. 查看日志: `~/.copaw/logs/copaw.log`
2. 检查配置: `copaw config validate`
3. 提交 Issue: https://github.com/YvanJiang/CoPaw/issues

## 参考链接

- [CoPaw 文档](https://copaw.dev)
- [GitHub 仓库](https://github.com/YvanJiang/CoPaw)
- [Release Notes](https://copaw.dev/release-notes)
