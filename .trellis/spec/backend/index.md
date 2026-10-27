# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

The first implemented package is the Python local usage-evidence tool in `src/aha`.
Read its executable contract before changing code. The other topic files remain bootstrap templates.

## Pre-Development Checklist

- Read [Usage Evidence Contract](./usage-evidence-contract.md) and the active task's PRD/design.
- Identify the source read boundary, application-store owner and affected frozen-artifact contracts.
- Use an isolated data directory and keep personal source/evidence outside Git.

## Quality Check

- Run unittest, Ruff, strict mypy and compileall as specified in the contract.
- Exercise native Windows/browser/Excel behavior for release or cross-layer changes.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Usage Evidence Contract](./usage-evidence-contract.md) | Actual source, arithmetic, store, HTTP and release contracts | Implemented |
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Database Guidelines](./database-guidelines.md) | ORM patterns, queries, migrations | To fill |
| [Error Handling](./error-handling.md) | Error types, handling strategies | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | To fill |

---

## How to Fill These Guidelines

For each guideline file:

1. Document your project's **actual conventions** (not ideals)
2. Include **code examples** from your codebase
3. List **forbidden patterns** and why
4. Add **common mistakes** your team has made

The goal is to help AI assistants and new team members understand how YOUR project works.

---

**Language**: All documentation should be written in **English**.
