# Contributing

Thanks for considering a contribution.

## Getting set up

```bash
git clone https://github.com/biniyam-mulugeta/Offsetscope.git
cd Offsetscope
make install     # venv + npm install
make dev         # broker, schema registry, seeder, console
```

Or run the two halves separately with hot reload:

```bash
make backend     # API on :8080
make frontend    # Vite on :5173, proxied to the backend
```

## Before you open a pull request

```bash
make lint        # ruff, mypy --strict, eslint, tsc
make test        # backend + frontend unit tests
```

Both must pass. There is no hosted CI, so these local runs are the only check before review. If you changed anything that talks to Kafka, also run the integration tests against a broker (`OFFSETSCOPE_TEST_BOOTSTRAP=localhost:9092 make test-integration`).

Integration tests need a broker and skip cleanly without one:

```bash
OFFSETSCOPE_TEST_BOOTSTRAP=localhost:9092 make test-integration
```

## House rules

**Pin every dependency exactly.** No `^`, no `~`, no ranges. Reproducible builds matter more than automatic upgrades.

**No stubs in merged work.** A feature is done or it is not in the branch. A page that will exist later renders an honest "not built yet" state rather than a dead link.

**Nothing cluster-specific.** This tool must work against any Kafka. No topic names, consumer group names, field paths, or thresholds baked into code — they belong in configuration.

**Be careful with brokers.** Lag comes from the AdminClient, never a shadow consumer. Cache admin reads. Put a timeout on every broker call. Scans only run when a user asks for one.

**Never persist message payloads.** They stream to the browser and are forgotten. If you think you need to store something message-derived, it must be masked, aggregated, opt-in, and given a retention window.

**Degrade, do not crash.** An unreachable broker or an unsupported admin API produces a clear degraded response and a banner, never a stack trace or a spinner that never stops.

**Accessibility is not optional.** Keyboard navigation, visible focus rings, WCAG AA contrast. Status must never be conveyed by colour alone — pair it with an icon or shape.

## Style

- **Python**: ruff (100 columns) and `mypy --strict`. Run `make format`.
- **TypeScript**: eslint and `tsc --noEmit`. Prefer explicit types at module boundaries.
- **Comments** explain *why*, not *what*. Do not narrate the code.
- **Tests** describe behaviour, not implementation. A test whose name does not match its assertion is worse than no test.

## Commits and pull requests

Conventional-ish prefixes are appreciated: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`.

Keep pull requests focused. Describe what changed and why, and mention anything you could not verify.

## Adding a translation

1. Copy `locales/en.json` to `locales/<code>.json` and translate the values.
2. Add the code to `SUPPORTED_LOCALES` and `LOCALE_LABELS` in `frontend/src/i18n/index.ts`.
3. Import it in the same file.

Keys stay in English; only values are translated.

## Adding a theme

Create `themes/<name>/theme.json` with `colors.light`, `colors.dark`, `colors.categorical`, `fonts`, and `productName`. Optionally add `logo.svg`. Select it with `THEME=<name>`.

Check both light and dark, and verify contrast. Status colours must stay visually distinct from brand colours.

## Reporting bugs

Include the console version, the broker and version (or managed provider), what you expected, what happened, and any relevant log lines. Redact credentials.

Security issues go to [`SECURITY.md`](SECURITY.md), not the public tracker.
