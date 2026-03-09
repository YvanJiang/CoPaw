# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""The shell command tool."""

import asyncio
import locale
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from agentscope.tool import ToolResponse
from agentscope.message import TextBlock

from copaw.constant import WORKING_DIR
from copaw.envs.store import load_envs

logger = logging.getLogger(__name__)


def _get_shell_config_cmd() -> str:
    """Get the shell configuration source command based on user's shell.

    Detects the user's shell and returns a command to source the appropriate
    configuration file (e.g., .zshrc, .bashrc, .bash_profile).

    Returns:
        `str`: Command to source shell config, or empty string if not applicable.
    """
    shell = os.environ.get("SHELL", "").lower()
    home = os.path.expanduser("~")

    # Determine which config file to source
    config_file = None

    if "zsh" in shell:
        # For zsh, prefer .zshrc, fallback to .zprofile
        zshrc = os.path.join(home, ".zshrc")
        zprofile = os.path.join(home, ".zprofile")
        if os.path.exists(zshrc):
            config_file = zshrc
        elif os.path.exists(zprofile):
            config_file = zprofile
    elif "bash" in shell:
        # For bash, prefer .bashrc, fallback to .bash_profile
        bashrc = os.path.join(home, ".bashrc")
        bash_profile = os.path.join(home, ".bash_profile")
        bash_login = os.path.join(home, ".bash_login")
        if os.path.exists(bashrc):
            config_file = bashrc
        elif os.path.exists(bash_profile):
            config_file = bash_profile
        elif os.path.exists(bash_login):
            config_file = bash_login

    if config_file:
        logger.info(
            f"[Shell Tool] Detected shell: {shell}, will source: {config_file}"
        )
        # Use 'source' for bash/zsh, but need to handle the case where
        # shell might be different from the one we're targeting
        return f'source "{config_file}" 2>/dev/null || true'

    logger.info(f"[Shell Tool] No shell config found for: {shell}")
    return ""


def _execute_subprocess_sync(
    cmd: str,
    cwd: str,
    timeout: int,
    source_shell_config: bool = True,
) -> tuple[int, str, str]:
    """Execute subprocess synchronously in a thread.

    This function runs in a separate thread to avoid Windows asyncio
    subprocess limitations.

    Args:
        cmd (`str`):
            The shell command to execute.
        cwd (`str`):
            The working directory for the command execution.
        timeout (`int`):
            The maximum time (in seconds) allowed for the command to run.
        source_shell_config (`bool`, defaults to `True`):
            Whether to source shell configuration file before executing command.

    Returns:
        `tuple[int, str, str]`:
            A tuple containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """
    # Build command with shell config sourcing if enabled
    if source_shell_config and sys.platform != "win32":
        shell_config = _get_shell_config_cmd()
        if shell_config:
            # Combine sourcing with the actual command
            full_cmd = f"{shell_config} && {cmd}"
            logger.info(
                f"[Shell Tool] Executing with shell config sourced: {cwd=}"
            )
        else:
            full_cmd = cmd
            logger.info(f"[Shell Tool] Executing without shell config: {cwd=}")
    else:
        full_cmd = cmd
        logger.info(
            f"[Shell Tool] Executing on Windows or config disabled: {cwd=}"
        )

    try:
        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            encoding=locale.getpreferredencoding(False) or "utf-8",
            errors="replace",
            check=True,
        )
        logger.info(
            f"[Shell Tool] Command completed: returncode={result.returncode}, "
            f"stdout_len={len(result.stdout)}, stderr_len={len(result.stderr)}",
        )
        return (
            result.returncode,
            result.stdout.strip("\n"),
            result.stderr.strip("\n"),
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"[Shell Tool] Command timeout after {timeout}s")
        return (
            -1,
            "",
            f"Command execution exceeded the timeout of {timeout} seconds.",
        )
    except subprocess.CalledProcessError as e:
        logger.info(
            f"[Shell Tool] Command failed with returncode={e.returncode}"
        )
        return e.returncode, e.stdout.strip("\n"), e.stderr.strip("\n")
    except Exception as e:
        logger.error(f"[Shell Tool] Command execution error: {e}")
        return -1, "", str(e)


def _get_default_env_file() -> Optional[str]:
    """Get the default shell configuration file based on OS and shell.

    Returns:
        `Optional[str]`: Path to the default env file, or None if not found.
    """
    import os

    if sys.platform == "win32":
        # Windows: Check for common env files in USERPROFILE
        user_profile = os.environ.get("USERPROFILE", "")
        candidates = [
            os.path.join(user_profile, ".env"),
            os.path.join(user_profile, "env.bat"),
        ]
    else:
        # Linux/Mac: Check shell type and corresponding rc file
        home = os.path.expanduser("~")
        shell = os.environ.get("SHELL", "").lower()

        if "zsh" in shell:
            candidates = [
                os.path.join(home, ".zshrc"),
                os.path.join(home, ".bashrc"),
            ]
        elif "bash" in shell:
            candidates = [
                os.path.join(home, ".bashrc"),
                os.path.join(home, ".bash_profile"),
                os.path.join(home, ".profile"),
            ]
        else:
            # Fallback for other shells
            candidates = [
                os.path.join(home, ".zshrc"),
                os.path.join(home, ".bashrc"),
                os.path.join(home, ".profile"),
            ]

    # Return the first existing file
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return None


def _build_env_exports_win32(envs: dict[str, str]) -> str:
    """Build Windows environment variable export commands.

    Args:
        envs: Dictionary of environment variables.

    Returns:
        PowerShell commands to set environment variables.
    """
    if not envs:
        return ""
    exports = []
    for key, value in envs.items():
        # Escape single quotes in value for PowerShell
        escaped_value = value.replace("'", "''")
        exports.append(
            f"[Environment]::SetEnvironmentVariable('{key}', '{escaped_value}', 'Process')",
        )
    return "; ".join(exports)


def _build_env_exports_unix(envs: dict[str, str]) -> str:
    """Build Unix/Linux/Mac environment variable export commands.

    Args:
        envs: Dictionary of environment variables.

    Returns:
        Shell export commands to set environment variables.
    """
    if not envs:
        return ""
    exports = []
    for key, value in envs.items():
        # Escape single quotes in value and wrap in single quotes
        escaped_value = value.replace("'", "'\\''")
        exports.append(f"export {key}='{escaped_value}'")
    return " && ".join(exports)


def _escape_for_powershell_double_quotes(s: str) -> str:
    """Escape a string for safe embedding in PowerShell double-quoted string.

    In PowerShell double-quoted strings, double quotes must be escaped with
    backslash: \".

    Args:
        s: The string to escape.

    Returns:
        The escaped string safe for PowerShell double quotes.
    """
    return s.replace('"', '\\"')


def _escape_for_powershell_single_quotes(s: str) -> str:
    """Escape a string for safe embedding in PowerShell single-quoted string.

    In PowerShell, single quotes within single-quoted strings are escaped
    by doubling them: ''.

    Args:
        s: The string to escape.

    Returns:
        The escaped string safe for PowerShell single quotes.
    """
    return s.replace("'", "''")


def _build_command_with_env(command: str) -> str:
    """Build shell command with environment variable sourcing.

    Automatically detects and sources the default shell configuration file
    based on the operating system and current shell, and also loads
    environment variables from envs.json via load_envs().

    Args:
        command (`str`):
            The shell command to execute.

    Returns:
        `str`: The combined command with environment sourcing.
    """
    cmd = (command or "").strip()

    # Load environment variables from envs.json
    envs = load_envs()

    env_file = _get_default_env_file()

    if sys.platform == "win32":
        # Build env exports from envs.json
        env_exports = _build_env_exports_win32(envs)

        # Escape user command for PowerShell double-quoted context
        escaped_cmd = _escape_for_powershell_double_quotes(cmd)

        if not env_file:
            if env_exports:
                return f'powershell -Command "{env_exports}; {escaped_cmd}"'
            return cmd

        # Windows: Use PowerShell to load environment variables from file
        # Supports .env format (KEY=VALUE) and .bat format
        if env_file.lower().endswith(".bat") or env_file.lower().endswith(
            ".cmd"
        ):
            # For batch files, use call to execute them
            if env_exports:
                return f'call "{env_file}" && powershell -Command "{env_exports}; {escaped_cmd}"'
            return f'call "{env_file}" && {cmd}'
        else:
            # Escape file path for PowerShell single-quoted context
            escaped_env_file = _escape_for_powershell_single_quotes(env_file)

            # For .env files, use PowerShell to parse and set variables
            ps_script_parts = [
                f'powershell -Command "',
                f"Get-Content -Path '{escaped_env_file}' | ",
                f"ForEach-Object {{ ",
                f"if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') ",
                f"{{ [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process') }} ",
                f"}}",
            ]
            if env_exports:
                ps_script_parts.append(f"; {env_exports}")
            ps_script_parts.append(f'; {escaped_cmd}"')
            return "".join(ps_script_parts)
    else:
        # Build env exports from envs.json
        env_exports = _build_env_exports_unix(envs)

        if not env_file:
            if env_exports:
                return f"{env_exports} && {cmd}"
            return cmd

        # Linux/Mac: Use source command (sh compatible)
        if env_exports:
            return f'source "{env_file}" && {env_exports} && {cmd}'
        return f'source "{env_file}" && {cmd}'


# pylint: disable=too-many-branches, too-many-statements
async def execute_shell_command(
    command: str,
    timeout: int = 60,
    cwd: Optional[Path] = None,
) -> ToolResponse:
    """Execute given command and return the return code, standard output and
    error within <returncode></returncode>, <stdout></stdout> and
    <stderr></stderr> tags.

    Automatically sources the default shell configuration file (~/.zshrc,
    ~/.bashrc, etc.) before executing the command, based on the operating
    system and current shell.

    Args:
        command (`str`):
            The shell command to execute.
        timeout (`int`, defaults to `10`):
            The maximum time (in seconds) allowed for the command to run.
            Default is 60 seconds.
        cwd (`Optional[Path]`, defaults to `None`):
            The working directory for the command execution.
            If None, defaults to WORKING_DIR.

    Returns:
        `ToolResponse`:
            The tool response containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """
    # 检查是否尝试直接调用 claude 命令
    # 匹配行首、管道符、分号、&&、|| 后的 claude 或 claude_XXX 命令
    claude_pattern = re.compile(
        r"(?:^|[;|&]|&&|\|\|)\s*(claude(?:[_-][a-zA-Z0-9_]+)?)\b",
        re.IGNORECASE,
    )
    matches = claude_pattern.findall(command)
    if matches:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"❌ 检测到不允许的命令 '{matches[0]}'。"
                    "请使用 launch_async_process 工具来启动 Claude 进程。",
                ),
            ],
        )

    # 检查是否尝试使用 sleep 进行系统等待
    # 匹配行首、管道符、分号、&&、|| 后的 sleep 命令
    sleep_pattern = re.compile(
        r"(?:^|[;|&]|&&|\|\|)\s*(sleep)\b",
        re.IGNORECASE,
    )
    if sleep_pattern.search(command):
        error_msg = (
            "❌ 检测到使用 sleep 命令进行系统等待。\n\n"
            "请停止当前会话，让自己睡一觉，并改用 "
            "launch_async_process 启动异步等待任务。\n\n"
            "示例（使用 notify_on_complete 自动发送完成通知）：\n"
            "launch_async_process(\n"
            "    command='sleep 60 && <your command>',\n"
            "    name='wait-task',\n"
            "    notify_on_complete=True,\n"
            "    notify_message='等待任务已完成'\n"
            ")"
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=error_msg,
                ),
            ],
        )

    cmd = _build_command_with_env(command)

    # Set working directory
    working_dir = cwd if cwd is not None else WORKING_DIR

    logger.info(
        f"[Shell Tool] Preparing to execute: {cmd[:100]}... in {working_dir}"
    )

    try:
        if sys.platform == "win32":
            # Windows: use thread pool to avoid asyncio subprocess limitations
            # cmd already includes env setup from _build_command_with_env()
            logger.info("[Shell Tool] Using Windows thread pool execution")
            returncode, stdout_str, stderr_str = await asyncio.to_thread(
                _execute_subprocess_sync,
                cmd,
                str(working_dir),
                timeout,
                source_shell_config=False,
            )
        else:
            # Unix: cmd already includes shell config sourcing from _build_command_with_env()
            logger.info(f"[Shell Tool] Executing in {working_dir}")

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                bufsize=0,
                cwd=str(working_dir),
            )

            try:
                # Apply timeout to communicate directly; wait()+communicate()
                # can hang if descendants keep stdout/stderr pipes open.
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                encoding = locale.getpreferredencoding(False) or "utf-8"
                stdout_str = stdout.decode(encoding, errors="replace").strip(
                    "\n",
                )
                stderr_str = stderr.decode(encoding, errors="replace").strip(
                    "\n",
                )
                returncode = proc.returncode
                logger.info(
                    f"[Shell Tool] Command completed: returncode={returncode}, "
                    f"stdout_len={len(stdout_str)}, stderr_len={len(stderr_str)}",
                )

            except asyncio.TimeoutError:
                logger.warning(
                    f"[Shell Tool] Command timeout after {timeout}s"
                )
                # Handle timeout
                stderr_suffix = (
                    f"⚠️ TimeoutError: The command execution exceeded "
                    f"the timeout of {timeout} seconds. "
                    f"Please consider increasing the timeout value if this command "
                    f"requires more time to complete."
                )
                returncode = -1
                try:
                    proc.terminate()
                    # Wait a bit for graceful termination
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=1)
                    except asyncio.TimeoutError:
                        # Force kill if graceful termination fails
                        proc.kill()
                        await proc.wait()

                    # Avoid hanging forever while draining pipes after timeout.
                    try:
                        stdout, stderr = await asyncio.wait_for(
                            proc.communicate(),
                            timeout=1,
                        )
                    except asyncio.TimeoutError:
                        stdout, stderr = b"", b""
                    encoding = locale.getpreferredencoding(False) or "utf-8"
                    stdout_str = stdout.decode(
                        encoding,
                        errors="replace",
                    ).strip(
                        "\n",
                    )
                    stderr_str = stderr.decode(
                        encoding,
                        errors="replace",
                    ).strip(
                        "\n",
                    )
                    if stderr_str:
                        stderr_str += f"\n{stderr_suffix}"
                    else:
                        stderr_str = stderr_suffix
                except ProcessLookupError:
                    stdout_str = ""
                    stderr_str = stderr_suffix

        # Format the response in a human-friendly way
        if returncode == 0:
            # Success case: just show the output
            if stdout_str:
                response_text = stdout_str
            else:
                response_text = "Command executed successfully (no output)."
        else:
            # Error case: show detailed information
            response_parts = [f"Command failed with exit code {returncode}."]
            if stdout_str:
                response_parts.append(f"\n[stdout]\n{stdout_str}")
            if stderr_str:
                response_parts.append(f"\n[stderr]\n{stderr_str}")
            response_text = "".join(response_parts)

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=response_text,
                ),
            ],
        )

    except Exception as e:
        logger.error(f"[Shell Tool] Command execution failed: {e}")
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Shell command execution failed due to \n{e}",
                ),
            ],
        )
