# Frontend Development Guidelines

> Best practices for frontend development in this project.

---

## Overview

The implemented interface is plain JavaScript/HTML/CSS under `src/aha/web`.
Read its local web contract before changing code. Other topic files remain bootstrap templates;
React hook patterns do not describe this application.

## Pre-Development Checklist

- Read [Local Web Contract](./local-web-contract.md) and the active task's design.
- Check invalidation, optional-field payload shapes and frozen batch behavior at both ends.
- Preserve Chinese product text and bundled local assets.

## Quality Check

- Run Node syntax validation and backend HTTP tests.
- Exercise actual browser creation/download after payload or lifecycle changes.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Local Web Contract](./local-web-contract.md) | Actual DOM, state, API, privacy and download conventions | Implemented |
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Component Guidelines](./component-guidelines.md) | Component patterns, props, composition | To fill |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks, data fetching patterns | To fill |
| [State Management](./state-management.md) | Local state, global state, server state | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Type Safety](./type-safety.md) | Type patterns, validation | To fill |

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
