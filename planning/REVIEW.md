# Change Review

## Findings

### [P2] Exclude machine-local Claude permissions from version control

`.claude/settings.local.json:4-26` grants broad local capabilities, including every command matching `codex exec *`, and contains machine-specific filesystem paths. The file is currently untracked, but `.gitignore` does not exclude it, so a routine `git add -A` would stage these permissions for everyone who clones the repository. Add `.claude/settings.local.json` to `.gitignore`; if any of these permissions are meant to be shared, move only the narrowly scoped rules to the tracked project settings instead.

## Validation

- Reviewed `git diff HEAD` and every untracked file, excluding `planning/REVIEW.md` itself as the generated review artifact.
- `git diff --check HEAD` passed.
- `.claude/settings.local.json` parses as valid JSON.
- No automated tests were run because there are no application-code changes since `HEAD`.
