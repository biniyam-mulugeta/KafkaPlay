# Screenshots

These are captured from the dev stack, which produces realistic demo data:

```bash
make dev
cd frontend && npx playwright test test/e2e/screenshots.spec.ts
```

The spec writes PNGs into this directory in both light and dark themes.
They are generated rather than committed by hand so they cannot drift from
the actual UI.
