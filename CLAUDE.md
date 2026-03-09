# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CoPaw is a personal AI assistant that runs locally and connects to multiple chat channels (DingTalk, Feishu, QQ, Discord, iMessage, Telegram, etc.). It is built on top of the AgentScope framework.

## Development Commands

### Setup

```bash
# Install for development (includes test dependencies)
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Testing

```bash
# Run all tests
pytest

# Run tests excluding slow tests
pytest -m "not slow"

# Run a specific test file
pytest tests/test_command_dispatch.py

# Run a specific test class
pytest tests/test_async_process.py::TestAsyncProcessNotification

# Run a specific test method
pytest tests/test_async_process.py::TestAsyncProcessNotification::test_auto_notify_on_completion

# Run only failed tests from last run
pytest --lf

# Run with coverage
pytest --cov=copaw
```

### Linting and Formatting

```bash
# Run all pre-commit checks
pre-commit run --all-files

# Python only (pre-commit handles this)
black --line-length=79 src/
flake8 --extend-ignore=E203 src/
pylint src/

# Console/Website only
cd console && npm run format
cd website && npm run format
```

### Console (Frontend)

```bash
cd console

# Install dependencies (clean install)
npm ci

# Development server
npm run dev

# Build for production
npm run build

# Build and copy to Python package (required before pip install)
npm run build
mkdir -p ../src/copaw/console
cp -R dist/. ../src/copaw/console/
```

### Running the Application

```bash
# Initialize working directory (creates config, skills)
copaw init --defaults

# Start the web console
copaw app

# With debug logging
copaw app --debug

# Daemon mode
copaw daemon start
```

### Build Scripts

```bash
# Build wheel with console (run from repo root)
bash scripts/wheel_build.sh

# Build Docker image
bash scripts/docker_build.sh [IMAGE_TAG]

# Build website
bash scripts/website_build.sh
```

## Architecture

### Project Structure

```
src/copaw/
├── cli/              # CLI commands (click-based)
├── app/              # FastAPI web app, channels, routers
├── agents/           # Core agent logic, skills, memory
├── providers/        # LLM provider registry and models
├── config/           # Configuration management
├── local_models/     # Local model backends (llama.cpp, MLX, Ollama)
├── tunnel/           # Tunneling for external access
└── utils/            # Utility functions

console/              # React + TypeScript frontend
website/              # Documentation website
tests/                # pytest test suite
```

### Key Architectural Patterns

**Agent Architecture**
- `CoPawAgent` in `agents/react_agent.py` extends AgentScope's `ReActAgent`
- Integrates tools (shell, file ops, browser), skills, and memory management
- Uses hooks for bootstrap guidance (`agents/hooks/bootstrap.py`) and memory compaction (`agents/hooks/memory_compaction.py`)
- Tools are registered via `register_tool()` and can have naming conflicts resolved via `namesake_strategy`

**Channel System** (`app/channels/`)
- All channels extend `BaseChannel` in `app/channels/base.py`
- Unified in-process contract: native payload → `content_parts` → agent
- Channels are registered in `app/channels/registry.py`
- Custom channels can be loaded from the working directory
- Key lifecycle: `receive` → `build_agent_request_from_native` → `_process` → `send_message_content`
- Use `uses_manager_queue = True` for long-lived channels (manager creates queue and consumer loop)
- Content parts use AgentScope runtime types: `TextContent`, `ImageContent`, `FileContent`, etc.

**Skills System** (`agents/skills/`)
- Each skill is a directory with `SKILL.md` (YAML front matter + instructions)
- Optional `references/` for reference docs, `scripts/` for tools
- Built-in skills: cron, file_reader, pdf, docx, pptx, xlsx, browser_visible, news
- Skills are merged from built-in and user's `customized_skills/` into `active_skills/`
- Loaded dynamically at runtime by `skills_manager.py`

**Model Provider System** (`providers/`)
- `registry.py`: Provider definitions with `id`, `name`, `default_base_url`
- Supports cloud APIs (OpenAI-compatible), local backends (llama.cpp, MLX, Ollama)
- Custom providers can be added via Console or `providers.json`

**Memory Management** (`agents/memory/`)
- `MemoryManager` with in-memory and persistent storage
- Auto-compaction hook keeps recent messages and compacts older ones
- Integration with ReMe for long-term memory

**Configuration**
- Working directory defaults to `~/.copaw/`
- Config files: `config.json`, `providers.json`, `channels.json`
- Skills directory: `customized_skills/` (user) + `active_skills/` (runtime)

### Important Conventions

**Commit Messages**: Use Conventional Commits format:
```
<type>(<scope>): <subject>
```
Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`

**Code Style**:
- Python: Black with 79-character line length
- Skills excluded from linting (they may have custom formatting)
- Console/Website: Prettier for TypeScript/React

**Skills Development**:
- `SKILL.md` front matter must have `name` and `description`
- Description should include trigger keywords for the model to recognize when to use the skill
- Place scripts in `scripts/` subdirectory

**Channel Development**:
- Set class attribute `channel` to a unique key (e.g., `"telegram"`)
- Implement lifecycle: receive → `content_parts` → `process` → send response
- Use `uses_manager_queue = True` for long-lived channels
- Override `build_agent_request_from_native()` to convert channel-specific payloads to AgentScope runtime content parts
- Override `send()` and optionally `send_media()` for channel-specific output

## HTTP Basic Auth Configuration

Add `auth` section to `config.json` to enable HTTP Basic Auth:

```json
{
  "auth": {
    "enabled": true,
    "username": "admin",
    "password": "your-secure-password",
    "excluded_paths": ["/webhook/feishu", "/webhook/feishu/health"]
  }
}
```

- `enabled`: Whether to enable authentication
- `username`: Login username
- `password`: Login password (empty string disables auth)
- `excluded_paths`: Paths that don't require authentication (webhook endpoints excluded by default)
