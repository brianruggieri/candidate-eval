# Copilot Instructions

## Code Style

- **Indentation:** Tabs (not spaces). This is the project convention per CLAUDE.md.
- **Line length:** 100 characters (ruff)
- **Quotes:** Double quotes for strings

## Testing

- Real data preferred over mocks. Use fixture files in `tests/fixtures/`.
- Tests use tabs for indentation, matching the rest of the codebase.

## Project Context

This is a Python 3.11+ project using pydantic v2, click, and FastAPI. Build system is hatchling via pyproject.toml. Linting is done with ruff.
