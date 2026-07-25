<!-- Keep the change focused — unrelated cleanups belong in their own PR. -->

## What & why

<!-- What does this change, and why? -->

Fixes #<!-- issue number, if this closes one -->

## Checklist

- [ ] Backend tests pass — `cd backend && .venv/bin/pytest`
- [ ] Frontend checks pass — `cd frontend && npm run test && npx tsc --noEmit && npx eslint .`
- [ ] If UI-observable, I ran it in the browser and confirmed it works
- [ ] Follows the architectural rules in [CONTRIBUTING.md](../CONTRIBUTING.md) (events, `competition_id` scoping, `require_permission`, one hook per domain, design tokens)
- [ ] One migration for this PR if the schema changed, named `YYYY-MM-DD_<revid>_<desc>.py`
- [ ] This is **not** a security fix (those follow [SECURITY.md](../SECURITY.md))
