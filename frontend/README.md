# RestaurantOS frontend

This is the Next.js 16 frontend for RestaurantOS. Use the repository root
[`README.md`](../README.md) for full-stack setup and startup instructions.

The frontend requires `NEXT_PUBLIC_API_URL`; copy `.env.example` to
`.env.local` for local development.

```bash
npm ci
npm run dev
```

Available checks:

```bash
npm run lint
npm run typecheck
npm run build
```

The local application is served at <http://localhost:3000> and expects the API
at <http://localhost:8000> when using the supplied example configuration.

Known baseline limitation: the root-page connectivity probe still hardcodes the
localhost API URL. Other API modules use `NEXT_PUBLIC_API_URL`; this exception is
documented for a later behavior-focused change.
