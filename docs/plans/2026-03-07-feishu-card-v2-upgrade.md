# 飞书卡片消息 V2 格式升级计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将飞书频道消息格式从 Post 类型升级到 Card v2 Schema 2.0，提供更丰富的卡片消息体验。

**Architecture:** 在 `channel.py` 中添加 Card V2 构建方法，修改现有发送方法以使用新的卡片格式。文本和图片将整合到单个卡片中发送，文件仍单独发送。

**Tech Stack:** Python 3.x, Lark (Feishu) Open API, Card V2 Schema 2.0

---

## 前置检查

**Step 1: 验证当前代码结构**

文件: `src/copaw/app/channels/feishu/channel.py`

确认以下方法存在：
- `_build_post_content` 在 1030 行
- `_send_text` 在 1230 行
- `send_content_parts` 在 1511 行
- `send` 在 1601 行
- `normalize_feishu_md` 导入自 `.utils`

**Step 2: 运行现有测试**

```bash
pytest tests/ -k feishu -v --tb=short 2>/dev/null || echo "No feishu tests found"
```

---

## Task 1: 添加 Card V2 内容构建方法

**Files:**
- Modify: `src/copaw/app/channels/feishu/channel.py:1048-1049`（在 `_build_post_content` 之后添加新方法）

**Step 1: 添加 `_build_card_v2_content` 方法**

在 `_build_post_content` 方法结束后的 1048-1049 行之间插入新方法：

```python
    def _build_card_v2_content(
        self,
        text: str,
        image_keys: List[str],
        header_title: Optional[str] = None,
        template: str = "blue",
    ) -> Dict[str, Any]:
        """构建飞书 Card V2 消息内容 (Schema 2.0).

        Args:
            text: Markdown 文本内容
            image_keys: 图片 key 列表（通过 _upload_image_sync 上传获得）
            header_title: 卡片标题（可选）
            template: 头部颜色模板，可选: green, red, blue, orange, indigo, grey
        """
        # 构建 body elements
        elements: List[Dict[str, Any]] = []

        # 添加文本内容
        if text:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": normalize_feishu_md(text)
                }
            })

        # 添加图片元素
        for image_key in image_keys:
            elements.append({
                "tag": "img",
                "img_key": image_key,
                "alt": {
                    "tag": "plain_text",
                    "content": "图片"
                }
            })

        # 如果没有内容，显示占位符
        if not elements:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "[empty]"
                }
            })

        # 构建基础卡片结构
        card: Dict[str, Any] = {
            "schema": "2.0",
            "config": {"update_multi": True},
            "body": {"elements": elements}
        }

        # 添加 header（如果提供了标题）
        if header_title:
            card["header"] = {
                "template": template,
                "title": {
                    "tag": "plain_text",
                    "content": header_title
                }
            }

        return card
```

**Step 2: 语法检查**

```bash
python -m py_compile src/copaw/app/channels/feishu/channel.py
```

Expected: 无错误

**Step 3: Commit**

```bash
git add src/copaw/app/channels/feishu/channel.py
git commit -m "feat(feishu): add Card V2 content builder method"
```

---

## Task 2: 添加 `_send_card_v2` 方法

**Files:**
- Modify: `src/copaw/app/channels/feishu/channel.py:1248-1249`（在 `_send_text` 之后）

**Step 1: 添加 `_send_card_v2` 方法**

在 `_send_text` 方法（1230-1248 行）之后插入：

```python
    async def _send_card_v2(
        self,
        receive_id_type: str,
        receive_id: str,
        text: str,
        image_keys: List[str],
        header_title: Optional[str] = None,
        template: str = "blue",
    ) -> bool:
        """发送 Card V2 消息."""
        card = self._build_card_v2_content(
            text, image_keys, header_title, template
        )
        content = json.dumps(card, ensure_ascii=False)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._send_message_sync(
                receive_id_type,
                receive_id,
                "interactive",
                content,
            ),
        )
```

**Step 2: 语法检查**

```bash
python -m py_compile src/copaw/app/channels/feishu/channel.py
```

Expected: 无错误

**Step 3: Commit**

```bash
git add src/copaw/app/channels/feishu/channel.py
git commit -m "feat(feishu): add Card V2 sender method"
```

---

## Task 3: 修改 `_send_text` 方法使用 Card V2

**Files:**
- Modify: `src/copaw/app/channels/feishu/channel.py:1230-1248`

**Step 1: 更新 `_send_text` 方法**

替换第 1230-1248 行的 `_send_text` 方法为：

```python
    async def _send_text(
        self,
        receive_id_type: str,
        receive_id: str,
        body: str,
    ) -> bool:
        """发送文本消息（使用 Card V2 格式）."""
        card = self._build_card_v2_content(body, [], header_title=None)
        content = json.dumps(card, ensure_ascii=False)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._send_message_sync(
                receive_id_type,
                receive_id,
                "interactive",
                content,
            ),
        )
```

**Step 2: 语法检查**

```bash
python -m py_compile src/copaw/app/channels/feishu/channel.py
```

Expected: 无错误

**Step 3: Commit**

```bash
git add src/copaw/app/channels/feishu/channel.py
git commit -m "feat(feishu): update _send_text to use Card V2 format"
```

---

## Task 4: 修改 `send_content_parts` 方法整合文本和图片

**Files:**
- Modify: `src/copaw/app/channels/feishu/channel.py:1511-1599`

**Step 1: 更新 `send_content_parts` 方法**

替换第 1511-1599 行的 `send_content_parts` 方法为：

```python
    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """发送内容片段（使用 Card V2 格式，文本和图片整合在一个卡片中）."""
        if not self.enabled:
            return
        recv = await self._get_receive_for_send(to_handle, meta)
        if not recv:
            logger.warning(
                "feishu send_content_parts: no receive_id for to_handle=%s "
                "(cron will not send; ensure user chatted once or set "
                "dispatch.meta.feishu_receive_id)",
                to_handle[:50] if to_handle else "",
            )
            return

        receive_id_type, receive_id = recv
        logger.info(
            "feishu send_content_parts: resolved receive_id_type=%s "
            "receive_id=%s...",
            receive_id_type,
            (receive_id or "")[:20],
        )
        prefix = (meta or {}).get("bot_prefix", "") or self.bot_prefix or ""

        # 收集文本和图片
        text_parts: List[str] = []
        image_parts: List[OutgoingContentPart] = []
        file_parts: List[OutgoingContentPart] = []

        for p in parts:
            t = getattr(p, "type", None) or (
                p.get("type") if isinstance(p, dict) else None
            )
            text_val = getattr(p, "text", None) or (
                p.get("text") if isinstance(p, dict) else None
            )
            refusal_val = getattr(p, "refusal", None) or (
                p.get("refusal") if isinstance(p, dict) else None
            )

            if t == ContentType.TEXT and text_val:
                text_parts.append(text_val or "")
            elif t == ContentType.REFUSAL and refusal_val:
                text_parts.append(refusal_val or "")
            elif t == ContentType.IMAGE:
                image_parts.append(p)
            elif t in (
                ContentType.FILE,
                ContentType.VIDEO,
                ContentType.AUDIO,
            ):
                file_parts.append(p)

        logger.info(
            "feishu send_content_parts: to_handle=%s text_parts=%s "
            "image_count=%s file_count=%s",
            to_handle[:40] if to_handle else "",
            len(text_parts),
            len(image_parts),
            len(file_parts),
        )

        # 上传所有图片获取 image_keys
        image_keys: List[str] = []
        for part in image_parts:
            data, filename = await self._part_to_image_bytes(part)
            if data:
                loop = asyncio.get_running_loop()
                image_key = await loop.run_in_executor(
                    None,
                    lambda: self._upload_image_sync(data, filename),
                )
                if image_key:
                    image_keys.append(image_key)

        # 发送 Card V2 消息（包含文本和图片）
        body = "\n".join(text_parts).strip()
        if prefix and body:
            body = prefix + body

        if body or image_keys:
            await self._send_card_v2(
                receive_id_type,
                receive_id,
                body,
                image_keys,
            )

        # 文件仍然单独发送
        for part in file_parts:
            ok = await self._send_file(
                receive_id_type,
                receive_id,
                part,
            )
            logger.info(
                "feishu send_content_parts: file sent ok=%s type=%s",
                ok,
                getattr(part, "type", None),
            )
```

**Step 2: 语法检查**

```bash
python -m py_compile src/copaw/app/channels/feishu/channel.py
```

Expected: 无错误

**Step 3: Commit**

```bash
git add src/copaw/app/channels/feishu/channel.py
git commit -m "feat(feishu): update send_content_parts to use unified Card V2"
```

---

## Task 5: 更新 `send` 方法使用 Card V2

**Files:**
- Modify: `src/copaw/app/channels/feishu/channel.py:1601-1621`

**Step 1: 更新 `send` 方法**

替换第 1601-1621 行的 `send` 方法为：

```python
    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """主动发送文本消息（使用 Card V2 格式）."""
        if not self.enabled:
            return
        recv = await self._get_receive_for_send(to_handle, meta)
        if not recv:
            logger.warning(
                "feishu send: no receive_id for to_handle=%s",
                to_handle[:50] if to_handle else "",
            )
            return
        receive_id_type, receive_id = recv
        prefix = (meta or {}).get("bot_prefix", "") or self.bot_prefix or ""
        body = (prefix + text) if text else prefix
        if body:
            await self._send_card_v2(receive_id_type, receive_id, body, [])
```

**Step 2: 语法检查**

```bash
python -m py_compile src/copaw/app/channels/feishu/channel.py
```

Expected: 无错误

**Step 3: Commit**

```bash
git add src/copaw/app/channels/feishu/channel.py
git commit -m "feat(feishu): update send method to use Card V2 format"
```

---

## Task 6: 代码清理和 lint 检查

**Files:**
- Modify: `src/copaw/app/channels/feishu/channel.py`

**Step 1: 运行 lint 检查**

```bash
black --line-length=79 src/copaw/app/channels/feishu/channel.py
flake8 --extend-ignore=E203 src/copaw/app/channels/feishu/channel.py
```

Expected: 无错误

**Step 2: 检查未使用的导入**

如果 `_build_post_content` 方法不再被其他地方使用，可以考虑添加 deprecation 标记，但暂时保留以防外部依赖。

**Step 3: Commit（如有格式变更）**

```bash
git diff --quiet || git commit -am "style(feishu): format code with black"
```

---

## Task 7: 验证测试

**Files:**
- Check: `tests/` 目录下的飞书相关测试

**Step 1: 查找并运行相关测试**

```bash
# 查找飞书相关测试
find tests -name "*feishu*" -o -name "*lark*" 2>/dev/null

# 运行所有测试
pytest tests/ -v --tb=short 2>/dev/null || echo "pytest not available or no tests"
```

**Step 2: 手动验证 Card V2 结构**

创建临时验证脚本：

```python
import json
import sys
sys.path.insert(0, 'src')

# 验证 Card V2 结构
card = {
    "schema": "2.0",
    "config": {"update_multi": True},
    "body": {
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "测试消息"
                }
            },
            {
                "tag": "img",
                "img_key": "img_xxx",
                "alt": {"tag": "plain_text", "content": "图片"}
            }
        ]
    },
    "header": {
        "template": "blue",
        "title": {"tag": "plain_text", "content": "标题"}
    }
}

print("Card V2 JSON structure valid:")
print(json.dumps(card, ensure_ascii=False, indent=2))
```

**Step 3: Commit（如果测试通过）**

---

## Task 8: 最终审查和总结

**Step 1: 查看所有变更**

```bash
git diff --stat HEAD~5
```

Expected 输出应显示只修改了 `src/copaw/app/channels/feishu/channel.py`

**Step 2: 确认变更内容**

```bash
git log --oneline HEAD~5..HEAD
```

Expected commits:
1. `feat(feishu): add Card V2 content builder method`
2. `feat(feishu): add Card V2 sender method`
3. `feat(feishu): update _send_text to use Card V2 format`
4. `feat(feishu): update send_content_parts to use unified Card V2`
5. `feat(feishu): update send method to use Card V2 format`

**Step 3: 最终提交信息**

如果一切正常，创建总结 commit：

```bash
git log --oneline HEAD~5..HEAD > /tmp/commits.txt
cat /tmp/commits.txt
```

---

## 头部颜色模板参考

根据消息类型可以使用不同的颜色模板：

| 模板值 | 颜色 | 适用场景 |
|--------|------|----------|
| `blue` | 蓝色 | 普通消息（默认） |
| `green` | 绿色 | 成功状态 |
| `red` | 红色 | 错误/告警 |
| `orange` | 橙色 | 警告 |
| `indigo` | 靛蓝 | 信息/处理中 |
| `grey` | 灰色 | 禁用/取消 |

---

## 回滚方案

如果需要回滚到 Post 格式：

1. 恢复 `_send_text` 方法使用 `self._build_post_content` 和 `"post"` msg_type
2. 恢复 `send_content_parts` 方法的分开发送逻辑
3. 恢复 `send` 方法调用 `_send_text`
4. 可选：保留 `_build_card_v2_content` 和 `_send_card_v2` 供将来使用

---

## 验证清单

- [ ] `_build_card_v2_content` 方法已添加
- [ ] `_send_card_v2` 方法已添加
- [ ] `_send_text` 方法已更新为使用 Card V2
- [ ] `send_content_parts` 方法已更新（文本+图片整合）
- [ ] `send` 方法已更新为使用 Card V2
- [ ] 代码通过语法检查 (`python -m py_compile`)
- [ ] 代码通过 black 和 flake8 检查
- [ ] 所有提交遵循 conventional commits 格式
