# -*- coding: utf-8 -*-
"""异步进程管理器 - 管理异步进程的生命周期。

- 启动进程并记录 PID
- 查询进程状态
- 停止进程
- 清理已终止进程
- 退出时清理所有进程
"""
import asyncio
import json
import logging
import os
import platform
import signal
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from copaw.constant import WORKING_DIR
from copaw.envs.store import load_envs

logger = logging.getLogger(__name__)

# 平台检测
IS_WINDOWS = platform.system() == "Windows"
IS_POSIX = os.name == "posix"


def _get_default_env_file() -> Optional[str]:
    """获取默认的 shell 配置文件路径。

    根据操作系统和当前 shell 类型，返回对应的配置文件路径
    （如 ~/.zshrc、~/.bashrc、~/.bash_profile 等）。

    Returns:
        `Optional[str]`: 配置文件路径，如果不存在则返回 None。
    """
    if IS_WINDOWS:
        # Windows: 检查常见的环境文件
        user_profile = os.environ.get("USERPROFILE", "")
        candidates = [
            os.path.join(user_profile, ".env"),
            os.path.join(user_profile, "env.bat"),
        ]
    else:
        # Linux/Mac: 根据 shell 类型选择配置文件
        home = os.path.expanduser("~")
        shell = os.environ.get("SHELL", "").lower()

        if "zsh" in shell:
            candidates = [
                os.path.join(home, ".zshrc"),
                os.path.join(home, ".zprofile"),
                os.path.join(home, ".bashrc"),
            ]
        elif "bash" in shell:
            candidates = [
                os.path.join(home, ".bashrc"),
                os.path.join(home, ".bash_profile"),
                os.path.join(home, ".bash_login"),
                os.path.join(home, ".profile"),
            ]
        else:
            # 其他 shell 的默认候选
            candidates = [
                os.path.join(home, ".zshrc"),
                os.path.join(home, ".bashrc"),
                os.path.join(home, ".profile"),
            ]

    # 返回第一个存在的文件
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return None


def _build_env_exports_unix(envs: Dict[str, str]) -> str:
    """构建 Unix/Linux/Mac 环境变量导出命令。

    Args:
        envs: 环境变量字典。

    Returns:
        Shell export 命令字符串。
    """
    if not envs:
        return ""
    exports = []
    for key, value in envs.items():
        # 转义单引号
        escaped_value = value.replace("'", "'\\''")
        exports.append(f"export {key}='{escaped_value}'")
    return " && ".join(exports)


def _build_command_with_env(command: str) -> str:
    """构建带有环境变量 source 的命令。

    自动检测并 source 默认的 shell 配置文件，同时加载 envs.json 中的环境变量。

    Args:
        command: 原始 shell 命令。

    Returns:
        包装后的命令字符串。
    """
    cmd = (command or "").strip()

    # 加载环境变量
    envs = load_envs()
    env_file = _get_default_env_file()

    if IS_WINDOWS:
        # Windows: 直接返回原命令，环境变量已通过 env 参数传递
        return cmd
    else:
        # 构建环境变量导出
        env_exports = _build_env_exports_unix(envs)

        if not env_file:
            if env_exports:
                return f"{env_exports} && {cmd}"
            return cmd

        # Unix/Linux/Mac: source 配置文件并导出环境变量
        if env_exports:
            return f'source "{env_file}" && {env_exports} && {cmd}'
        return f'source "{env_file}" && {cmd}'


class ProcessState(str, Enum):
    """进程状态枚举。"""

    RUNNING = "running"
    EXITED = "exited"
    STOPPED = "stopped"
    ORPHANED = "orphaned"


@dataclass
class AsyncProcessInfo:
    """异步进程信息。"""

    pid: int
    name: str
    command: str
    started_at: str
    cwd: str
    status: str = ProcessState.RUNNING
    exited_at: Optional[str] = None
    exit_code: Optional[int] = None

    def to_dict(self) -> dict:
        """转换为字典。"""
        return {
            "pid": self.pid,
            "name": self.name,
            "command": self.command,
            "started_at": self.started_at,
            "cwd": self.cwd,
            "status": self.status.value
            if isinstance(self.status, ProcessState)
            else self.status,
            "exited_at": self.exited_at,
            "exit_code": self.exit_code,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AsyncProcessInfo":
        """从字典创建。"""
        status = data.get("status", ProcessState.RUNNING)
        # 兼容旧的状态字符串
        if isinstance(status, str):
            try:
                status = ProcessState(status)
            except ValueError:
                status = ProcessState.RUNNING
        return cls(
            pid=data["pid"],
            name=data["name"],
            command=data["command"],
            started_at=data["started_at"],
            cwd=data["cwd"],
            status=status,
            exited_at=data.get("exited_at"),
            exit_code=data.get("exit_code"),
        )


class AsyncProcessManager:
    """管理异步进程的生命周期。

    单例模式，确保整个应用中只有一个进程管理器实例。
    """

    _instance: Optional["AsyncProcessManager"] = None
    _initialized: bool = False

    def __new__(cls) -> "AsyncProcessManager":
        """单例模式。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """初始化进程管理器。"""
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True

        # 进程存储：name -> AsyncProcessInfo
        self._processes: Dict[str, AsyncProcessInfo] = {}
        # 异步锁（实例级别，避免事件循环问题）
        self._lock: asyncio.Lock = asyncio.Lock()
        # 持久化文件路径
        self._persist_file = WORKING_DIR / "async_processes.json"
        # 监控任务
        self._monitor_task: Optional[asyncio.Task] = None
        # 是否已启动监控
        self._monitor_started = False

        # 加载持久化的进程信息
        self._load_processes()

    @property
    def persist_file(self) -> Path:
        """获取持久化文件路径。"""
        return self._persist_file

    async def start_monitor(self) -> None:
        """启动后台监控任务。"""
        if self._monitor_started:
            return

        async with self._lock:
            if self._monitor_started:
                return
            self._monitor_started = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("[AsyncProcessManager] 后台监控任务已启动")

    async def stop_monitor(self) -> None:
        """停止后台监控任务。"""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
            self._monitor_started = False
            logger.info("[AsyncProcessManager] 后台监控任务已停止")

    async def _monitor_loop(self) -> None:
        """后台监控循环，每 5 秒检查一次进程状态。"""
        while True:
            try:
                await asyncio.sleep(5)
                await self._check_processes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[AsyncProcessManager] 监控循环出错：{e}")

    async def _check_processes(self) -> None:
        """检查所有进程状态，更新已退出的进程。"""
        async with self._lock:
            for name, proc_info in list(self._processes.items()):
                if proc_info.status != ProcessState.RUNNING:
                    continue

                # 使用 os 检查进程是否还在运行
                try:
                    os.kill(proc_info.pid, 0)
                except ProcessLookupError:
                    # 进程不存在
                    proc_info.status = ProcessState.EXITED
                    proc_info.exited_at = datetime.now().isoformat()
                    logger.info(
                        "[AsyncProcessManager] 进程 '%s' (PID: %s) 已退出",
                        name,
                        proc_info.pid,
                    )
                except PermissionError:
                    # 进程存在但没有权限发送信号（通常意味着进程还在运行）
                    pass
                except Exception as e:
                    logger.warning(
                        f"[AsyncProcessManager] 检查进程 '{name}' 状态失败：{e}",
                    )

            # 保存状态
            self._save_processes()

    async def launch(
        self,
        command: str,
        name: str,
        cwd: Optional[Path] = None,
    ) -> AsyncProcessInfo:
        """启动异步进程。

        Args:
            command: 要执行的命令
            name: 进程名称（唯一标识）
            cwd: 工作目录，默认为 WORKING_DIR

        Returns:
            进程信息对象
        """
        async with self._lock:
            # 检查同名进程是否已存在
            if name in self._processes:
                existing = self._processes[name]
                if existing.status == ProcessState.RUNNING:
                    # 检查是否真的还在运行
                    try:
                        os.kill(existing.pid, 0)
                        raise ValueError(
                            f"进程 '{name}' 已在运行 (PID: {existing.pid})",
                        )
                    except ProcessLookupError:
                        # 进程已退出，可以复用名称
                        logger.info(
                            f"[AsyncProcessManager] 进程 '{name}' 已退出，复用名称",
                        )
                        self._processes.pop(name)
                else:
                    # 已退出的进程，可以复用名称
                    self._processes.pop(name)

            working_dir = cwd if cwd is not None else WORKING_DIR
            now = datetime.now().isoformat()

            # 创建环境变量
            env = os.environ.copy()
            # 合并自定义环境变量
            envs = load_envs()
            env.update(envs)

            # 构建带环境 source 的命令（类似 shell.py 的处理）
            full_command = _build_command_with_env(command)

            # 启动进程
            # 注意：使用 DEVNULL 避免 PIPE 缓冲区满导致进程阻塞
            proc = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(working_dir),
                env=env,
                # Windows 不支持 start_new_session，使用 creationflags 替代
                start_new_session=not IS_WINDOWS,
                **(
                    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                    if IS_WINDOWS
                    else {}
                ),
            )

            # 创建进程信息（记录实际执行的完整命令）
            proc_info = AsyncProcessInfo(
                pid=proc.pid,
                name=name,
                command=full_command,
                started_at=now,
                cwd=str(working_dir),
                status=ProcessState.RUNNING,
            )

            # 存储进程
            self._processes[name] = proc_info

            # 保存状态
            self._save_processes()

            logger.info(
                f"[AsyncProcessManager] 进程 '{name}' 已启动 (PID: {proc.pid})",
            )

            return proc_info

    def get_process(self, name: str) -> Optional[AsyncProcessInfo]:
        """获取进程信息。

        Args:
            name: 进程名称

        Returns:
            进程信息对象，如果不存在则返回 None
        """
        return self._processes.get(name)

    def list_processes(self) -> List[AsyncProcessInfo]:
        """获取所有进程列表。

        Returns:
            进程信息列表
        """
        return list(self._processes.values())

    def list_running_processes(self) -> List[AsyncProcessInfo]:
        """获取所有运行中的进程列表。

        Returns:
            运行中的进程信息列表
        """
        return [
            p
            for p in self._processes.values()
            if p.status == ProcessState.RUNNING
        ]

    async def stop(self, name: str, force: bool = False) -> bool:
        """停止进程。

        Args:
            name: 进程名称
            force: 是否强制 kill（发送 SIGKILL 而非 SIGTERM）

        Returns:
            是否成功停止
        """
        async with self._lock:
            proc_info = self._processes.get(name)
            if proc_info is None:
                logger.warning(f"[AsyncProcessManager] 进程 '{name}' 不存在")
                return False

            if proc_info.status != ProcessState.RUNNING:
                logger.info(
                    f"[AsyncProcessManager] 进程 '{name}' 已退出，无需停止",
                )
                return True

            # 使用进程组信号停止，确保子进程也被终止
            try:
                sig = signal.SIGKILL if force else signal.SIGTERM
                try:
                    if IS_WINDOWS:
                        # Windows: 使用 taskkill 终止进程树
                        cmd = ["taskkill", "/PID", str(proc_info.pid)]
                        if force:
                            cmd.extend(["/F", "/T"])
                        else:
                            cmd.append("/T")
                        subprocess.run(
                            cmd,
                            capture_output=True,
                            check=False,
                        )
                    else:
                        # Unix/Linux/macOS: 先尝试发送给整个进程组
                        os.killpg(proc_info.pid, sig)
                except (ProcessLookupError, OSError):
                    # 进程组不存在，尝试发送给单个进程
                    os.kill(proc_info.pid, sig)

                # 短暂等待进程退出
                for _ in range(10):
                    await asyncio.sleep(0.1)
                    try:
                        os.kill(proc_info.pid, 0)
                    except ProcessLookupError:
                        # 进程已退出
                        break

                # 更新状态
                proc_info.status = ProcessState.STOPPED
                proc_info.exited_at = datetime.now().isoformat()
                self._save_processes()

                logger.info(
                    "[AsyncProcessManager] 进程 '%s' (PID: %s) 已停止",
                    name,
                    proc_info.pid,
                )
                return True

            except ProcessLookupError:
                # 进程已不存在
                proc_info.status = ProcessState.EXITED
                proc_info.exited_at = datetime.now().isoformat()
                self._save_processes()
                logger.info(
                    "[AsyncProcessManager] 进程 '%s' (PID: %s) 已退出",
                    name,
                    proc_info.pid,
                )
                return True
            except Exception as e:
                logger.error(
                    f"[AsyncProcessManager] 停止进程 '{name}' 失败：{e}",
                )
                return False

    async def stop_all(self) -> Dict[str, bool]:
        """停止所有运行中的进程。

        Returns:
            停止结果字典：{name: success}
        """
        results = {}
        running = self.list_running_processes()

        for proc_info in running:
            success = await self.stop(proc_info.name)
            results[proc_info.name] = success

        return results

    async def cleanup(self, name: str) -> bool:
        """清理已退出的进程记录。

        Args:
            name: 进程名称

        Returns:
            是否成功清理
        """
        async with self._lock:
            proc_info = self._processes.get(name)
            if proc_info is None:
                return False

            if proc_info.status == ProcessState.RUNNING:
                # 检查是否真的在运行
                try:
                    os.kill(proc_info.pid, 0)
                    logger.warning(
                        f"[AsyncProcessManager] 进程 '{name}' 仍在运行，无法清理",
                    )
                    return False
                except ProcessLookupError:
                    # 进程已退出，可以清理
                    pass

            # 清理记录
            self._processes.pop(name)
            self._save_processes()

            logger.info(f"[AsyncProcessManager] 进程 '{name}' 记录已清理")
            return True

    def _save_processes(self) -> None:
        """保存进程信息到持久化文件。"""
        try:
            data = {
                name: info.to_dict() for name, info in self._processes.items()
            }
            with open(self._persist_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(
                f"[AsyncProcessManager] 进程信息已保存到 {self._persist_file}",
            )
        except Exception as e:
            logger.error(
                f"[AsyncProcessManager] 保存进程信息失败：{e}",
            )

    def _load_processes(self) -> None:
        """从持久化文件加载进程信息。"""
        if not self._persist_file.exists():
            logger.debug(
                f"[AsyncProcessManager] 持久化文件不存在：{self._persist_file}",
            )
            return

        try:
            with open(self._persist_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for name, info_dict in data.items():
                proc_info = AsyncProcessInfo.from_dict(info_dict)
                # 只加载已退出的进程信息，运行中的进程需要重新检查
                if proc_info.status != ProcessState.RUNNING:
                    self._processes[name] = proc_info
                else:
                    # 检查进程是否真的还在运行
                    try:
                        os.kill(proc_info.pid, 0)
                        # 进程还在运行，但 asyncio 进程对象丢失，标记为 orphaned
                        proc_info.status = ProcessState.ORPHANED
                        self._processes[name] = proc_info
                        logger.warning(
                            "[AsyncProcessManager] 发现孤儿进程 '%s' (PID: %s)",
                            name,
                            proc_info.pid,
                        )
                    except ProcessLookupError:
                        # 进程已退出，更新状态
                        proc_info.status = ProcessState.EXITED
                        proc_info.exited_at = datetime.now().isoformat()
                        self._processes[name] = proc_info

            logger.info(
                "[AsyncProcessManager] 从 %s 加载了 %s 个进程记录",
                self._persist_file,
                len(self._processes),
            )
        except Exception as e:
            logger.error(f"[AsyncProcessManager] 加载进程信息失败：{e}")

    async def close(self) -> None:
        """关闭管理器，停止所有进程。"""
        await self.stop_all()
        await self.stop_monitor()
        logger.info("[AsyncProcessManager] 管理器已关闭")


# 全局管理器实例（延迟初始化）
_manager: Optional[AsyncProcessManager] = None


def get_manager() -> AsyncProcessManager:
    """获取全局进程管理器实例。"""
    global _manager
    if _manager is None:
        _manager = AsyncProcessManager()
    return _manager


async def cleanup_all_processes() -> None:
    """清理所有异步进程（用于程序退出时）。"""
    manager = get_manager()
    await manager.close()
