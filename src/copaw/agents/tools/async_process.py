# -*- coding: utf-8 -*-
"""异步进程启动工具 - 用于启动和管理后台异步进程。

与 shell.py 的区别：
- 不等待进程完成，立即返回
- 返回进程 ID 和启动状态
- 进程在后台继续运行
"""
import logging
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from copaw.utils.notification import get_notification_service
from .process_manager import AsyncProcessInfo, get_manager

logger = logging.getLogger(__name__)


def _format_process_table(processes: list[AsyncProcessInfo]) -> str:
    """格式化进程列表为表格。

    Args:
        processes: 进程信息列表

    Returns:
        格式化的表格字符串
    """
    if not processes:
        return "当前没有运行的异步进程。"

    # 计算列宽
    name_width = max(len("名称"), max(len(p.name) for p in processes))
    pid_width = max(len("PID"), max(len(str(p.pid)) for p in processes))
    cmd_width = max(len("命令"), max(len(p.command) for p in processes))

    # 限制命令列宽度
    cmd_width = min(cmd_width, 50)

    lines = []
    lines.append(f"当前运行的异步进程 ({len(processes)}):")
    lines.append(
        "┌"
        + "─" * name_width
        + "┬"
        + "─" * pid_width
        + "┬"
        + "─" * cmd_width
        + "┐",
    )
    header_name = "名称".ljust(name_width)
    header_pid = "PID".ljust(pid_width)
    header_cmd = "命令".ljust(cmd_width)
    lines.append(f"│ {header_name} │ {header_pid} │ {header_cmd} │")
    lines.append(
        "├"
        + "─" * name_width
        + "┼"
        + "─" * pid_width
        + "┼"
        + "─" * cmd_width
        + "┤",
    )

    for proc in processes:
        name = proc.name.ljust(name_width)
        pid = str(proc.pid).ljust(pid_width)
        cmd = (
            proc.command[:cmd_width].ljust(cmd_width)
            if len(proc.command) > cmd_width
            else proc.command.ljust(cmd_width)
        )
        lines.append(f"│ {name} │ {pid} │ {cmd} │")

    lines.append(
        "└"
        + "─" * (name_width + 2)
        + "┴"
        + "─" * (pid_width + 2)
        + "┴"
        + "─" * (cmd_width + 2)
        + "┘",
    )

    return "\n".join(lines)


async def launch_async_process(
    command: str,
    name: Optional[str] = None,
    cwd: Optional[Path] = None,
    notify_on_complete: bool = False,
    notify_message: Optional[str] = None,
) -> ToolResponse:
    """启动异步进程并立即返回。

    与 shell 工具的区别：
    - 不等待进程完成，立即返回
    - 返回进程 ID 和启动状态
    - 进程在后台继续运行

    Args:
        command (`str`):
            要执行的 shell 命令。
        name (`Optional[str]`, defaults to `None`):
            进程名称，用于标识和管理。如果未提供，将使用命令的前 30 个字符作为名称。
        cwd (`Optional[Path]`, defaults to `None`):
            进程工作目录，默认为工作目录。
        notify_on_complete (`bool`, defaults to `False`):
            是否在进程完成时发送通知。需要设置 API_USER 和 API_PASS 环境变量。
        notify_message (`Optional[str]`, defaults to `None`):
            自定义通知消息。如果不设置，将使用默认消息。

    Returns:
        `ToolResponse`:
            包含进程启动状态的工具响应。

    Examples:
        启动 Claude Code:
        ```
        launch_async_process(
            command="claude --dangerously-skip-permissions",
            name="claude-code"
        )
        ```

        启动开发服务器:
        ```
        launch_async_process(
            command="npm run dev",
            name="my-server",
            cwd=Path("/path/to/project")
        )
        ```

        启动带通知的异步任务:
        ```
        launch_async_process(
            command="sleep 60 && ./long-running-task.sh",
            name="bg-task",
            notify_on_complete=True,
            notify_message="后台任务已完成"
        )
        ```
    """
    # 生成进程名称
    if name is None:
        # 使用命令的前 30 个字符作为名称
        name = command[:30].strip().replace(" ", "-")
        if not name:
            name = "unnamed-process"

    # 确保名称唯一且合法
    name = name.replace(" ", "-").replace("/", "-")

    # 处理通知命令包装
    wrapped_command = command
    if notify_on_complete:
        notification_service = get_notification_service()
        if notification_service.is_configured():
            # 构建通知消息
            process_name = name or "异步进程"
            default_msg = f"进程 '{process_name}' 已完成执行"
            message = notify_message or default_msg

            try:
                notify_cmd = notification_service.build_feishu_command(
                    message=message,
                    source="CoPaw",
                )
                # 使用 && 包装命令，确保只有命令成功时才发送通知
                wrapped_command = f"({command}) && {notify_cmd}"
            except RuntimeError as e:
                logger.warning("构建通知命令失败：%s", e)
        else:
            logger.warning(
                "notify_on_complete=True 但通知服务未配置。"
                "请设置 API_USER 和 API_PASS 环境变量。",
            )

    try:
        # 获取管理器
        manager = get_manager()

        # 确保监控任务已启动
        await manager.start_monitor()

        # 启动进程
        proc_info = await manager.launch(
            command=wrapped_command,
            name=name,
            cwd=cwd,
        )

        # 构建响应
        response_lines = [
            "✅ 进程已启动",
            f"- 名称：{proc_info.name}",
            f"- PID: {proc_info.pid}",
            f"- 命令：{command}",
            f"- 工作目录：{proc_info.cwd}",
        ]

        # 添加通知状态
        if notify_on_complete:
            notification_service = get_notification_service()
            if notification_service.is_configured():
                response_lines.extend(
                    [
                        "",
                        "📬 通知：已启用",
                        f"  消息：{notify_message or '默认'}",
                    ],
                )
            else:
                response_lines.extend(
                    [
                        "",
                        "⚠️ 通知：未配置（请设置 API_USER 和 API_PASS）",
                    ],
                )

        response_lines.extend(
            [
                "",
                "提示：使用 view_async_processes 查看进程列表，"
                "使用 stop_async_process 停止进程。",
            ],
        )

        response_text = "\n".join(response_lines)

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=response_text,
                ),
            ],
        )

    except ValueError as e:
        # 进程已存在
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"❌ 启动失败：{e}",
                ),
            ],
        )
    except Exception as e:
        logger.error(f"[AsyncProcess] 启动进程失败：{e}")
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"❌ 启动失败：{e}",
                ),
            ],
        )


async def view_async_processes() -> ToolResponse:
    """查看当前所有异步进程。

    Returns:
        `ToolResponse`:
            包含进程列表的工具响应。
    """
    try:
        manager = get_manager()
        processes = manager.list_running_processes()

        if not processes:
            response_text = "当前没有运行的异步进程。"
        else:
            response_text = _format_process_table(processes)

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=response_text,
                ),
            ],
        )

    except Exception as e:
        logger.error(f"[AsyncProcess] 查看进程失败：{e}")
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"❌ 查看失败：{e}",
                ),
            ],
        )


async def stop_async_process(
    name: str,
    force: bool = False,
) -> ToolResponse:
    """停止指定的异步进程。

    Args:
        name (`str`):
            进程名称。
        force (`bool`, defaults to `False`):
            是否强制 kill（发送 SIGKILL 而非 SIGTERM）。

    Returns:
        `ToolResponse`:
            包含停止结果的工具响应。
    """
    try:
        manager = get_manager()
        success = await manager.stop(name=name, force=force)

        if success:
            response_text = f"✅ 进程 '{name}' 已停止。"
        else:
            response_text = f"❌ 停止失败：未找到进程 '{name}' 或无法停止。"

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=response_text,
                ),
            ],
        )

    except Exception as e:
        logger.error(f"[AsyncProcess] 停止进程失败：{e}")
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"❌ 停止失败：{e}",
                ),
            ],
        )


async def cleanup_async_process(
    name: str,
) -> ToolResponse:
    """清理已退出的异步进程记录。

    Args:
        name (`str`):
            进程名称。

    Returns:
        `ToolResponse`:
            包含清理结果的工具响应。
    """
    try:
        manager = get_manager()
        success = await manager.cleanup(name=name)

        if success:
            response_text = f"✅ 进程 '{name}' 的记录已清理。"
        else:
            response_text = f"❌ 清理失败：未找到进程 '{name}' 或进程仍在运行。"

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=response_text,
                ),
            ],
        )

    except Exception as e:
        logger.error(f"[AsyncProcess] 清理进程失败：{e}")
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"❌ 清理失败：{e}",
                ),
            ],
        )
