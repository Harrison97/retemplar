# retemplar - Claude Context File

> This file provides context for Claude (and other AI assistants) to collaborate effectively on this project. It explains the purpose, architecture, current status, and key files so the AI can give better answers.

---

## Project Purpose

`retemplar` is an open-source tool for **repository templating and structural lifecycle management at scale**.  

It helps organizations manage fleets of repos by:

- Allowing any repo to act as a **Repo-as-Template (RAT)**
- Letting other repos **adopt** that template at a given version/ref
- Tracking provenance in a `.retemplar.lock` file
- Applying **template-to-template deltas** as small, explainable PRs
- Supporting **managed paths**, **section-level ownership**, and **inline blocks** to control drift

The goal is **consistent, auditable upgrades across all repos**, while preserving local changes where desired.

---

## Current Status

- **Phase**: Early development
- **Focus**: Repo-as-Template (RAT) MVP
- **Priority Features**:
  - CLI (`adopt`, `plan`, `apply`, `drift`)
  - `.retemplar.lock` schema & validation
  - RAT delta computation + 3-way merges
  - Drift detection & conflict resolution (default: conflict markers in PRs)
  - GitHub provider for PR automation
- **Reference Spec**: [`doc/design-doc.md`](doc/design-doc.md)

---

## Architecture Overview

### Core Components (MVP)
- **CLI**: `retemplar adopt`, `plan`, `apply`, `drift`
- **RAT Engine**: render template refs and compute deltas
- **Lockfile Manager**: read/write/validate `.retemplar.lock`
- **Ownership Engine**: manage paths, sections, and inline blocks
- **Drift Detector**: detect and categorize drift (template-only, local-only, conflicts)
- **Patch Engine**: structured ops for YAML/TOML/JSON and text merges
- **Provider Layer**: GitHub integration (branches, PRs, labels)

### Future Extensions
- Promotion of RATs into **Template Packs**
- Template switching for **major migrations**
- Multi-SCM support (GitLab, Bitbucket, Azure DevOps)
- Policy enforcement (e.g., minimum template versions)

---

## Key Files

~~~text
README.md           # Repo introduction
CLAUDE.md           # AI assistant context (this file)
doc/design-doc.md   # Full technical design specification
~~~

---

## Development Workflow

### Planned Tooling
- **Language**: Python 3.12+
- **Package Manager**: poetry / pipx
- **Linting & Type Checking**: ruff, mypy
- **Testing**: pytest
- **SCM**: GitHub (initial provider)

### Example CLI Usage
~~~bash
# Adopt a repo into RAT mode
retemplar adopt --template rat:gh:org/main@v2025.08.01

# Plan upgrade from old ref to new ref
retemplar plan --to rat:gh:org/main@v2025.09.01

# Apply changes and open a PR
retemplar apply --open-pr

# Detect drift vs lockfile baseline
retemplar drift
~~~

---

## Collaboration Guidelines

- **Source of Truth**: Keep `doc/design-doc.md` up to date with design decisions.  
- **Focus Now**: Deliver the RAT MVP before exploring Template Packs or migrations.  
- **Drift Handling**: Preserve user changes where appropriate, surface conflicts clearly in PRs.  
- **PRs as Delivery**: All changes flow through Git PRs; no silent modifications.  
- **AI Collaboration**:  
  - Ask for context in terms of *repo lifecycle management* (not just one-off templating).  
  - Use examples and workflows from `doc/design-doc.md`.  
  - Keep answers implementation-focused and scoped to MVP unless explicitly asked about future directions.

---

*Last updated: 2025-08-25*
