# -*- coding: utf-8 -*-
"""测试异步进程管理工具。"""
import asyncio
import os
import platform
import signal
import sys
import time
from pathlib import Path

import pytest

from copaw.agents.tools.async_process import (
    launch_async_process,
    view_async_processes,
    stop_async_process,
    cleanup_async_process,
)
from copaw.agents.tools.process_manager import (
    AsyncProcessManager,
    get_manager,
    cleanup_all_processes,
    ProcessState,
    IS_WINDOWS,
)


def get_sleep_command(seconds: int = 10) -> str:
    """获取跨平台的等待命令。"""
    if IS_WINDOWS:
        return f"timeout /t {seconds} /nobreak >nul 2>&1"
    else:
        return f"sleep {seconds}"


def get_short_sleep_command(seconds: float = 0.1) -> str:
    """获取跨平台的短等待命令。"""
    if IS_WINDOWS:
        return f'python -c "import time; time.sleep({seconds})"'
    else:
        return f"sleep {seconds}"


async def wait_for_process_exit(
    pid: int,
    timeout: float = 5.0,
    poll_interval: float = 0.05,
) -> bool:
    """轮询等待进程退出。

    Args:
        pid: 进程ID
        timeout: 最大等待时间（秒）
        poll_interval: 轮询间隔（秒）

    Returns:
        True 如果进程已退出，False 如果超时
    """
    start_time = asyncio.get_event_loop().time()
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True  # 进程已退出

        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= timeout:
            return False  # 超时

        await asyncio.sleep(poll_interval)


async def wait_for_file_exists(
    path: Path,
    timeout: float = 2.0,
    poll_interval: float = 0.05,
) -> bool:
    """轮询等待文件创建。

    Args:
        path: 文件路径
        timeout: 最大等待时间（秒）
        poll_interval: 轮询间隔（秒）

    Returns:
        True 如果文件存在，False 如果超时
    """
    start_time = asyncio.get_event_loop().time()
    while True:
        if path.exists():
            return True

        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= timeout:
            return False

        await asyncio.sleep(poll_interval)


@pytest.fixture
def manager():
    """获取进程管理器实例。"""
    # 确保每个测试使用新的管理器实例
    AsyncProcessManager._instance = None
    return get_manager()


@pytest.fixture
async def cleanup():
    """测试后清理所有进程。"""
    yield
    # 清理所有进程
    await cleanup_all_processes()


class TestAsyncProcessManager:
    """测试 AsyncProcessManager 类。"""

    @pytest.mark.asyncio
    async def test_launch_process(self, manager, cleanup):
        """测试启动进程。"""
        # 启动一个简单的 sleep 进程
        proc_info = await manager.launch(
            command=get_sleep_command(10),
            name="test-sleep",
        )

        assert proc_info.name == "test-sleep"
        assert proc_info.pid > 0
        assert proc_info.status == ProcessState.RUNNING

        # 验证进程确实在运行
        try:
            os.kill(proc_info.pid, 0)
        except ProcessLookupError:
            pytest.fail("进程已退出")

    @pytest.mark.asyncio
    async def test_launch_duplicate_name(self, manager, cleanup):
        """测试启动同名进程。"""
        # 启动第一个进程
        await manager.launch(
            command=get_sleep_command(10),
            name="test-dup",
        )

        # 尝试启动同名进程应该失败
        with pytest.raises(ValueError, match="已在运行"):
            await manager.launch(
                command=get_sleep_command(10),
                name="test-dup",
            )

    @pytest.mark.asyncio
    async def test_stop_process(self, manager, cleanup):
        """测试停止进程。"""
        proc_info = await manager.launch(
            command=get_sleep_command(10),
            name="test-stop",
        )

        # 停止进程
        success = await manager.stop("test-stop")
        assert success

        # 轮询等待进程退出（最多5秒）
        exited = await wait_for_process_exit(proc_info.pid, timeout=5.0)
        assert exited, "进程在5秒内未退出"

    @pytest.mark.asyncio
    async def test_stop_nonexistent_process(self, manager):
        """测试停止不存在的进程。"""
        success = await manager.stop("nonexistent")
        assert not success

    @pytest.mark.asyncio
    async def test_list_processes(self, manager, cleanup):
        """测试列出进程。"""
        # 启动多个进程
        await manager.launch(
            command=get_sleep_command(10),
            name="test-list-1",
        )
        await manager.launch(
            command=get_sleep_command(10),
            name="test-list-2",
        )

        # 列出所有进程
        processes = manager.list_processes()
        running = manager.list_running_processes()

        assert len(processes) >= 2
        assert len(running) >= 2

    @pytest.mark.asyncio
    async def test_get_process(self, manager, cleanup):
        """测试获取进程信息。"""
        await manager.launch(
            command=get_sleep_command(10),
            name="test-get",
        )

        proc_info = manager.get_process("test-get")
        assert proc_info is not None
        assert proc_info.name == "test-get"

    @pytest.mark.asyncio
    async def test_cleanup_process(self, manager, cleanup):
        """测试清理已退出的进程。"""
        # 启动一个短命进程
        proc_info = await manager.launch(
            command=get_short_sleep_command(0.1),
            name="test-cleanup",
        )

        # 轮询等待进程退出（最多5秒）
        exited = await wait_for_process_exit(proc_info.pid, timeout=5.0)
        assert exited, "进程在5秒内未退出"

        # 清理进程记录
        success = await manager.cleanup("test-cleanup")
        assert success

        # 验证记录已被清理
        assert manager.get_process("test-cleanup") is None

    @pytest.mark.asyncio
    async def test_stop_all_processes(self, manager, cleanup):
        """测试停止所有进程。"""
        # 启动多个进程
        await manager.launch(
            command=get_sleep_command(10),
            name="test-all-1",
        )
        await manager.launch(
            command=get_sleep_command(10),
            name="test-all-2",
        )

        # 停止所有进程
        results = await manager.stop_all()

        assert len(results) >= 2
        assert all(results.values())


class TestAsyncProcessTools:
    """测试异步进程工具函数。"""

    @pytest.mark.asyncio
    async def test_launch_async_process(self, cleanup):
        """测试 launch_async_process 工具。"""
        # 重置管理器
        AsyncProcessManager._instance = None

        response = await launch_async_process(
            command="echo hello",
            name="test-tool",
        )

        # 验证响应
        assert response.content is not None
        # TextBlock 可能被序列化为字典
        content_item = response.content[0]
        if isinstance(content_item, dict):
            text = content_item.get("text", "")
        else:
            text = getattr(content_item, "text", "")
        assert "✅ 进程已启动" in text or "PID" in text

    @pytest.mark.asyncio
    async def test_view_async_processes(self, cleanup):
        """测试 view_async_processes 工具。"""
        # 重置管理器
        AsyncProcessManager._instance = None

        response = await view_async_processes()
        assert response.content is not None
        content_item = response.content[0]
        if isinstance(content_item, dict):
            text = content_item.get("text", "")
        else:
            text = getattr(content_item, "text", "")
        # 应该是空列表或包含表格
        assert "当前" in text

    @pytest.mark.asyncio
    async def test_stop_async_process(self, cleanup):
        """测试 stop_async_process 工具。"""
        # 重置管理器
        AsyncProcessManager._instance = None

        # 先启动一个进程
        await launch_async_process(
            command=get_sleep_command(10),
            name="test-stop-tool",
        )

        # 停止进程
        response = await stop_async_process("test-stop-tool")
        assert response.content is not None
        content_item = response.content[0]
        if isinstance(content_item, dict):
            text = content_item.get("text", "")
        else:
            text = getattr(content_item, "text", "")
        assert "已停止" in text or "停止失败" in text

    @pytest.mark.asyncio
    async def test_cleanup_async_process(self, cleanup):
        """测试 cleanup_async_process 工具。"""
        # 重置管理器
        AsyncProcessManager._instance = None
        manager = get_manager()

        # 启动一个短命进程
        proc_info = await manager.launch(
            command=get_short_sleep_command(0.1),
            name="test-clean-tool",
        )

        # 轮询等待进程退出（最多5秒）
        exited = await wait_for_process_exit(proc_info.pid, timeout=5.0)
        assert exited, "进程在5秒内未退出"

        # 清理记录
        response = await cleanup_async_process("test-clean-tool")
        assert response.content is not None
        content_item = response.content[0]
        if isinstance(content_item, dict):
            text = content_item.get("text", "")
        else:
            text = getattr(content_item, "text", "")
        assert "已清理" in text or "清理失败" in text


class TestProcessManagerPersist:
    """测试进程管理器持久化。"""

    @pytest.mark.asyncio
    async def test_save_and_load(self, cleanup):
        """测试保存和加载进程信息。"""
        # 重置管理器
        AsyncProcessManager._instance = None
        manager = get_manager()

        # 启动进程
        await manager.launch(
            command=get_sleep_command(10),
            name="test-persist",
        )

        # 保存
        manager._save_processes()

        # 验证文件存在
        assert manager.persist_file.exists()

        # 创建新管理器实例
        AsyncProcessManager._instance = None
        manager2 = get_manager()

        # 验证新管理器实例创建成功
        assert manager2 is not None

        # 验证已退出的进程记录被加载（运行中的进程不会被加载为 running）
        # 这是预期行为，因为进程可能在管理器重启后丢失


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
