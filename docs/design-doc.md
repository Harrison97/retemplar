# retemplar – Technical Design Document

## 1. Problem Statement

Organizations accumulate hundreds or thousands of repositories. These repos typically share a common skeleton: CI/CD workflows, lint/test configs, infra manifests, and language-specific build files. Over time, template drift occurs:

- Some repos reflect old template versions.
- Some were never templated, but share ~80% overlap.
- Local changes to template-owned files create conflicts with upgrades.

Today, common solutions (Cookiecutter, Copier, Backstage Scaffolder) focus on **day-0 repo creation**. Renovate/Dependabot focus on **dependency bumps**, not **structural upgrades**. There is no standard for **day-N structural lifecycle management across a repo fleet**.

This creates pain:

- High cost to roll out org-wide changes (new CI standards, security scanning, linting).
- Inconsistent compliance.
- Difficulty onboarding new services.

We need a tool to:

- Use an existing repo as a **living template** (Repo-as-Template, RAT).
- Incrementally upgrade downstream repos with small, explainable PRs.
- Preserve local changes while enforcing template rules.
- Support gradual extraction of a RAT into a formal **Template Pack**.
- Eventually, support **major migrations** (template switching).

---

## 2. Tenets

1. **Incremental, not destructive.**  
   We upgrade via template-to-template deltas, not wholesale rewrites.

2. **Explainable diffs.**  
   Every change must show *why* it is proposed (RAT delta, migration recipe, overlay).

3. **Scoped ownership.**  
   Templates own only what they declare (paths, sections, managed blocks). Everything else is user-owned.

4. **Adopt-first.**  
   Any repo can join the ecosystem by adopting a RAT tag, without major rewrites.

5. **Promotion-ready.**  
   A RAT can be promoted into a first-class template pack without breaking provenance in downstreams.

6. **Escape hatches required.**  
   Users can override with `preserve`, `ignore`, or overlays. The tool must support deviations.

7. **Git-native.**  
   All upgrades flow via Git branches + PRs, never silent pushes.

---

## 3. Goals (MVP: RAT)

- Define a **Repo-as-Template (RAT)** mode: any repo tag can act as a template source.
- Allow downstream repos to **adopt** a RAT version.
- Compute **template deltas** between RAT tags and apply upgrades as **3-way merges**.
- Support **drift detection** and resolution strategies (`enforce`, `preserve`, `merge`, `patch`).
- Provide **inline managed blocks** for section-level ownership.
- Store provenance in a `.retemplar.lock` lockfile.
- Provide fleet operations: `plan`, `apply`, `drift`, `adopt`.
- Provide CLI and initial GitHub provider for PRs.

---

## 4. Non-Goals (MVP)

- No major architecture migrations (template switching).
- No multi-SCM support beyond GitHub.
- No codemod integrations beyond simple structured patches.
- No Backstage/service catalog integration.

---

## 5. High-Level Architecture

### 5.1 Components

- **CLI (`retemplar`)**: entrypoint for plan/apply/adopt.
- **RAT Engine**:  
  - Renders upstream RAT@ref.  
  - Computes template-to-template deltas.  
  - Applies diffs as 3-way merges.
- **Lockfile Manager**: Reads/writes `.retemplar.lock`.
- **Ownership Engine**: Evaluates managed paths, section rules, managed blocks.
- **Drift Detector**: Compares repo state against lockfile baseline.
- **Patch Engine**: Applies semantic operations (`yaml_set`, `toml_set`, `move`, `delete`).
- **Provider Layer**: SCM integration (GitHub API for PRs).

### 5.2 Data Flows

**Adoption**
- User runs `retemplar adopt --template rat:gh/org/main@tag`.
- Engine renders upstream RAT@tag.
- Computes structural fingerprint.
- Writes `.retemplar.lock` with `template: rat`, `ref: tag`, `managed_paths`.

**Plan**
- Input: Repo@HEAD, `.retemplar.lock`, RAT@old, RAT@new.
- Engine computes TemplateDelta = `diff(RAT@old, RAT@new)`.
- For each managed path: run Ownership Engine → Patch Engine → Plan.
- Output: human-readable diff grouped by category.

**Apply**
- Executes patch plan.
- Runs 3-way merge (Base=RAT@old, Theirs=RAT@new, Ours=Repo).
- Applies overlays.
- Runs hooks/tests.
- Opens PR.

**Drift**
- Compare repo files vs lockfile baseline.
- Categorize:  
  - Template-only changes  
  - Local-only drift  
  - Both changed → **conflict**
- Default behavior: **insert conflict markers + manual resolution in PR**.

---

## 6. Lockfile Schema (`.retemplar.lock`)

The lockfile is the authoritative record of template provenance and ownership scope. It is committed to source control.

### 6.1 Design Goals

- Deterministic upgrades.  
- Scoped ownership.  
- Drift-aware.  
- Explainable.  
- Evolvable.  
- Auditable.  

### 6.2 Key Concepts

- **Template Source**  
  - `kind`: `"rat"` or `"pack"`.  
  - `repo` + `ref` (RAT) OR `name` + `version` (Pack).  
  - Optional `subpath` for subdir templates.  

- **Variables**  
  Arbitrary key/values persisted for reproducibility.  

- **Ownership & Strategies**  
  - `managed_paths`: globs or structured rules.  
    - `enforce`: template wins.  
    - `preserve`: local wins.  
    - `merge`: attempt merge.  
    - `patch`: section-level rules.  
  - `ignore_paths`: explicit excludes.  
  - Default for unlisted paths: **unmanaged (no-op)**.

- **Managed Blocks**  
  Inline hash-checked blocks inside files. Example:

  ~~~toml
  # retemplar:begin id=ruff hash=sha256:abcd...
  [tool.ruff]
  line-length = 88
  # retemplar:end id=ruff
  ~~~

- **Fingerprints**  
  Structural hash of applied template for managed areas.

- **Lineage**  
  Records adoption, upgrades, reconciles, switches.

- **Overlays**  
  Deviations recorded as diffs or structured ops, re-applied after template changes.

### 6.3 Example Lockfile

~~~yaml
schema_version: "1.0.0"

template:
  kind: rat
  repo: gh:acme/main-svc
  ref: v2025.08.01
version: rat@v2025.08.01

variables:
  service_name: billing
  owner_team: platform

managed_paths:
  - path: ".github/workflows/**"
    strategy: enforce

  - path: "pyproject.toml"
    strategy: patch
    rules:
      - path: "tool.ruff"
        action: enforce
      - path: "project.dependencies"
        action: preserve

ignore_paths:
  - "README.md"

fingerprint:
  algo: sha256
  value: "8d0b...c9a"

lineage:
  - kind: adopt
    source: { kind: rat, repo: gh:acme/main-svc, ref: v2025.06.01 }
    at: "2025-08-10T14:12:22Z"
  - kind: upgrade
    from: "rat@v2025.06.01"
    to: "rat@v2025.08.01"
    at: "2025-08-21T08:55:00Z"
~~~

---

## 7. Expanded Examples

### 7.1 Simple CI Workflow Rename

Template v1.3 → v1.4:
~~~diff
-.github/workflows/pytest.yml
+.github/workflows/ci.yml
~~~

**Plan output:**
~~~text
[CI] Move workflow: pytest.yml → ci.yml
~~~

**Apply result:** PR with a `git mv` preserving history.

---

### 7.2 pyproject.toml with Mixed Ownership

Template delta: bump ruff version 0.3 → 0.5.  

Repo today:
~~~toml
[project]
dependencies = ["fastapi", "sqlalchemy"]

[tool.ruff]
line-length = 88
ruff = "0.3.0"
~~~

**Plan output:**
~~~diff
 [tool.ruff]
-ruff = "0.3.0"
+ruff = "0.5.0"
~~~

Dependencies untouched due to `preserve`.

---

### 7.3 Drift Conflict

Repo has locally changed `line-length = 120` in `[tool.ruff]`.  
Template bump wants `ruff = 0.5.0`.

**Plan shows conflict:**
~~~diff
  <<<<<<< local
  line-length = 120
  ruff = "0.3.0"
  =======
  line-length = 88
  ruff = "0.5.0"
  >>>>>>> template
~~~

**Default behavior:** insert conflict markers → manual resolution in PR.  

Reviewer decides whether to keep local or template line-length, then commits resolution.
