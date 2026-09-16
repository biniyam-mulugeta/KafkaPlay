## What and why

<!-- What changed, and what problem it solves. Link an issue if there is one. -->

## How it was verified

<!-- Commands you ran, and anything you could NOT verify. Say so plainly. -->

- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] Integration tests run against a real broker, or not applicable

## Checklist

- [ ] Dependencies pinned exactly — no ranges
- [ ] No stubs or TODOs left in the changed code
- [ ] Nothing cluster-specific hard-coded (topics, groups, field paths, thresholds)
- [ ] No new persistence of message payloads
- [ ] Broker calls are cached, timed out, and user-initiated where they cost anything
- [ ] Unreachable brokers and unsupported APIs degrade with an explanation
- [ ] Keyboard navigable, visible focus, status not conveyed by colour alone
- [ ] Both light and dark themes checked
- [ ] New user-facing strings added to `locales/en.json` and `locales/hu.json`
- [ ] `CHANGELOG.md` updated
