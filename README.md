# retemplar

> Fleet-scale repo templating and structural lifecycle management.

## Purpose

Organizations often have dozens or hundreds of repositories that share a common structure (CI workflows, lint configs, Dockerfiles, etc.). Over time, these repos **drift** from the original template. retemplar solves this by:

- Using any repo as a **living template** (Repo-as-Template, RAT)
- Letting other repos **adopt** that template version
- Applying **template-to-template deltas** as small, explainable PRs
- Supporting **managed paths**, **section-level rules**, and **inline blocks** to control ownership
- Recording provenance in a `.retemplar.lock` file

The result: consistent, auditable upgrades across your entire fleet of repos.

## Current Status

- **Phase**: Design + implementation (MVP: Repo-as-Template mode)
- **Primary Doc**: [`docs/design-doc.md`](docs/design-doc.md)
- **Goal**: Deliver CLI + GitHub integration for adopting and upgrading repos

## Development Workflow

```bash
# Install dependencies (planned)
poetry install

# See available commands
retemplar --help

# Adopt a repo into RAT mode
retemplar adopt --template rat:gh:org/main@v2025.08.01

# Plan upgrade to new template ref
retemplar plan --to rat:gh:org/main@v2025.09.01

# Apply and open a PR
retemplar apply --open-pr
