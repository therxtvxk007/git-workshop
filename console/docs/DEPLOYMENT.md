# Deploying the console

The build output is static: a directory of HTML, CSS and JavaScript. There is no
server component in this repository. Anything that needs a secret — an engine
API key, a database service role — lives behind a function you deploy
separately, never in this bundle.

## Build

```bash
cd console
npm ci
npm run build      # tsc -b && vite build  ->  dist/
npm run preview    # serve dist/ locally
```

`npm run build` runs the type checker first and fails on any error, so a build
that succeeds has type-checked.

Chunks are split so the ten routes that draw no map never download MapLibre:

```
react     ~165 kB   react, react-dom, react-router-dom
index     ~537 kB   the application
maplibre  ~802 kB   loaded only when VITE_MAP_STYLE_URL is set
```

## Configuration

Copy `.env.example` to `.env.local` and set what applies. Vite inlines `VITE_*`
variables **at build time**, so a change to any of them needs a rebuild, and
anything placed in one is public. See `.env.example` for the full list; the
minimum for a real deployment is:

```bash
VITE_PRAMAANX_API_MODE=rest
VITE_PRAMAANX_API_BASE_URL=https://engine.example.internal
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=<anon key>
```

Leaving `VITE_PRAMAANX_API_MODE=mock` deploys the demo dataset. That is a
legitimate thing to deploy — for a walkthrough, or a review of the interface —
and the `SYNTHETIC` pill and safety banner make it unmistakable. It is not a
staging environment for the engine.

## Database

Apply the migrations in order against your Postgres:

```bash
supabase db push                     # or:
for f in supabase/migrations/*.sql; do psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"; done
```

They require the `pgcrypto` extension (created by `0001`) and Supabase's `auth`
schema. Then run the policy tests against a scratch database, following
`docs/SECURITY_ROLES.md` — a deployment whose RLS has not been executed is a
deployment whose RLS is a hypothesis.

Grant the first administrator by hand; the sign-up trigger only ever issues
`viewer`:

```sql
insert into public.user_roles (user_id, role)
select id, 'administrator' from auth.users where email = 'you@example.org';
```

## Serving

Any static host works. Two requirements:

1. **SPA fallback.** `/forecasts/:id`, `/review/:id` and `/scenarios/:id` are
   client-side routes; unknown paths must serve `index.html` rather than 404.

   ```nginx
   location / { try_files $uri $uri/ /index.html; }
   ```

2. **`Cache-Control: no-cache` on `index.html`.** Asset filenames are
   content-hashed and can be cached indefinitely; a cached `index.html` pins
   users to a stale bundle.

### Suggested headers

```
Content-Security-Policy: default-src 'self'; connect-src 'self' https://engine.example.internal https://your-project.supabase.co; img-src 'self' data: blob:; worker-src blob:; style-src 'self' 'unsafe-inline'
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
```

`worker-src blob:` and `img-src blob:` are needed by MapLibre if you configure a
basemap; drop them if you do not. `style-src 'unsafe-inline'` is required by the
inline styles the map and the probability bars use.

The console sets `noindex, nofollow`. It should not be publicly reachable at
all: keep it behind whatever network boundary the engine sits behind.

## The engine proxy

In REST mode the browser sends the user's session token and nothing else. If the
engine needs its own credential, deploy a function that validates the session,
attaches the credential server-side, and returns the engine's response
unchanged — the console's schema validation depends on the body not being
rewritten in transit. See `docs/API_INTEGRATION.md`.

## Checks before a release

```bash
npm run typecheck
npm run lint
npm test                                     # 59 unit/integration tests
npm run build
npx playwright test                          # 24 specs; needs a browser
```

Playwright's browser is not part of the app runtime. In an image that already
ships Chromium, point at it instead of downloading a second copy:

```bash
PLAYWRIGHT_CHROMIUM_PATH=/opt/pw-browsers/chromium npx playwright test
```

## What deploying this does not give you

The engine's calibration is `identity@uncalibrated` and its alert policy is
`fixed_threshold@placeholder` with no miss-rate guarantee. Deploying the console
does not change that, and the safety banner says so on every route and in every
export. If someone asks for the banner to be removed for a demonstration, the
answer is no: the banner is the reason this can be shown at all.
