# retemplar

> Keep many repos in sync with a living template — without trampling local changes.

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

### Inline blocks:
Example:
```
# retemplar:begin id=<ID?> mode=ignore|protect
...your local content...
# retemplar:end
```
- Ignore will keep your code untouched
- Protect will create a diff of your code and the template for review

### CLI
```bash
pip install retemplar


# adopt repo to a template
retemplar adopt --template rat:../TEMPLATE

# NOTE: You will need to configure the lockfile yourself now

# preview changes
retemplar plan --to rat:../TEMPLATE


# apply
retemplar apply --to rat:../TEMPLATE
```
