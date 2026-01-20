# Agent Guidelines for Whisper-Typing

This document serves as the authoritative guide for AI agents and developers working on the `whisper-typing` (package: `whisper_typing`) repository. Adherence to these guidelines is mandatory to ensure code quality, consistency, and build stability.

## 1. Project Overview & Environment

- **Project Name:** `whisper-typing`
- **Language:** Python 3.13+ (Strict requirement)
- **Package Manager:** `uv` (Replaces pip/poetry/venv)
- **Build Backend:** `hatchling`
- **Formatter:** `dprint` (Fast, opinionated formatting)
- **Linter:** `ruff` (Strict linting with `ALL` ruleset enabled)
- **Testing:** `pytest` with `pytest-cov` (Enforcing 100% coverage)

## 2. Development Workflow & Commands

All commands should be executed via `uv run` to ensure they run in the isolated project environment.

### Essential Commands Table

| Category       | Action               | Command                           | Notes                                 |
| -------------- | -------------------- | --------------------------------- | ------------------------------------- |
| **Setup**      | Install Dependencies | `uv sync`                         | Run this first.                       |
| **Formatting** | Format Code          | `dprint fmt`                      | Run before every commit.              |
| **Linting**    | Check Code           | `uv run ruff check`               | Checks for linting errors.            |
| **Linting**    | Fix Code             | `uv run ruff check --fix`         | Automatically fixes simple errors.    |
| **Testing**    | Run All Tests        | `uv run pytest`                   | Runs all tests with coverage.         |
| **Testing**    | Run Single File      | `uv run pytest tests/test_app.py` | useful for focused TDD.               |
| **Testing**    | Run Specific Case    | `uv run pytest -k "test_name"`    | Filters tests by name.                |
| **Coverage**   | View Missing         | `uv run coverage report -m`       | See which lines are missing coverage. |
| **Coverage**   | Generate HTML        | `uv run coverage html`            | detailed report in `htmlcov/`.        |
| **Git Hooks**  | Run Pre-commit       | `uv run lefthook run pre-commit`  | Runs all checks locally.              |
| **Deps**       | Add Package          | `uv add <package>`                | Adds to pyproject.toml & locks.       |
| **Deps**       | Remove Package       | `uv remove <package>`             | Removes from project.                 |

### The "Golden Loop"

When making changes, follow this cycle:

1. **Explore:** Read relevant files in `src/` and `tests/`.
2. **Edit:** Apply changes.
3. **Format:** Run `dprint fmt`.
4. **Lint:** Run `uv run ruff check --fix`.
5. **Test:** Run `uv run pytest`.
6. **Verify:** Check if coverage is still 100%.

## 3. Code Style & Standards

### 3.1 Type Hints

Strict static typing is enforced.

- **Arguments/Returns:** Every function signature must have type hints.
- **Void Functions:** Must explicitly return `-> None`.
- **Collections:** Use standard generics (e.g., `list[str]`, `dict[str, int]`) instead of `typing.List`.
- **Optional:** Use `str | None` (Python 3.10+ syntax) instead of `Optional[str]`.

### 3.2 Docstrings

Documentation is required for all public modules, classes, and functions.

- **Style:** Google or NumPy style is preferred.
- **Format:** Triple double quotes `"""`.
- **Content:**
  - First line: Imperative summary (e.g., "Calculates the Fibonacci sequence.").
  - Body: Detailed description if complex.
  - Args/Returns: Document parameters and return values.
- **Note:** `D` (pydocstyle) rules are ignored in `tests/`, but enforced in `src/`.

### 3.3 Imports

- **Ordering:** Standard library -> Third party -> Local application.
- **Style:** Absolute imports are preferred over relative imports.
  - **Good:** `from whisper_typing.transcriber import Transcriber`
  - **Bad:** `from ..transcriber import Transcriber`
- **Public API:** Use `__all__ = [...]` in `__init__.py` files to control exports.

### 3.4 Naming Conventions

- **Variables/Functions:** `snake_case` (e.g., `calculate_sequence`)
- **Classes:** `PascalCase` (e.g., `AppController`)
- **Constants:** `UPPER_CASE` (e.g., `MAX_ITERATIONS`)
- **Modules:** `snake_case` (e.g., `transcriber.py`)
- **Test Functions:** Must start with `test_` (e.g., `test_transcription_success`)

## 4. Testing & Coverage Rules

This project maintains a **strict 100% test coverage** policy.

- **Configuration:** Defined in `pyproject.toml` (`fail_under = 100`).
- **Implication:** Every line of code, including error branches and `if` statements, must be executed by at least one test.
- **New Features:** Do not submit code without a corresponding test in `tests/`.
- **Test Structure:** Mirror the `src/` directory structure.
  - `src/whisper_typing/core.py` -> `tests/whisper_typing/test_core.py` (or `tests/test_core.py` if flat).

## 5. Linting Configuration Details

The project uses `ruff` with the `ALL` selector, meaning strictly all rules are enabled by default.

### Exceptions (Global)

These are ignored in `pyproject.toml` to avoid conflicts or preference:

- `COM812`: Trailing comma missing (Conflicts with dprint).
- `D203`: 1 blank line before class docstring (We use D211: no blank line).
- `D213`: Multi-line docstring summary at second line (We use D212: summary at first line).

### Exceptions (Tests)

- `S101`: Use of `assert` (Standard for pytest, security warning ignored).
- `D`: Docstring rules (Tests generally don't require docstrings).

## 6. Directory Structure

```text
D:\Github\whispher-typing\
├── src\
│   └── whisper_typing\        # Main package source
│       ├── __init__.py
│       └── ...
├── tests\                     # Test suite
│   ├── __init__.py
│   └── ...
├── pyproject.toml             # Project configuration (ruff, pytest, coverage)
├── dprint.json                # Formatting rules
├── lefthook.yml               # Git hooks configuration
└── AGENTS.md                  # This file
```

## 7. Agent Operational Protocol

When working in this repository, agents must:

1. **Respect Conventions:** Do not introduce new formatting styles or patterns that deviate from existing code.
2. **Read First:** Always read `pyproject.toml` and existing source files before planning changes.
3. **Explain Actions:** When running destructive commands or writing files, briefly explain the _why_.
4. **Self-Correct:** If a build command fails, analyze the error output, fix the code, and re-run the verify step.
5. **No Hallucinations:** Do not import packages that are not listed in `pyproject.toml` without explicitly adding them to the plan.
6. **Pathing:** Use absolute paths when using file system tools.
7. **Scoped Changes:** Focus on the requested task. Do not refactor unrelated code unless it is blocking.
8. **Dependency Safety:** Always use `uv add` to modify dependencies; never edit `pyproject.toml` manually for packages.

## 8. Common Pitfalls to Avoid

- **Forgot Type Hint:** Ruff will catch this. Ensure `def func(a: int) -> int:` syntax.
- **Coverage Drop:** Adding a new `if` condition without a test case that triggers it will cause the build to fail.
- **Formatting Conflicts:** Do not try to manually format code if it conflicts with `dprint`. Just run `dprint fmt`.
- **Relative Imports in Tests:** Ensure tests import from the installed package context.
- **Lockfile Desync:** If you see errors about dependencies, run `uv sync` to ensure the environment matches `uv.lock`.
