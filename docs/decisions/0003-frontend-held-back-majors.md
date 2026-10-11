# 0003 — Stay on PrimeVue 4 and TypeScript 6

- Status: accepted
- Date: 2026-10-11
- Steps: F-0

## Context

The plan names **PrimeVue 4** (02 §Tech stack, 06 §Stack) and says "use current stable
dependency versions" (CLAUDE.md). At F-0, two packages have a newer stable major than the one
that works for Reframe.

### PrimeVue 5 is not open source

```console
$ npm view primevue dist-tags
{ 'v2-stable': '2.10.4', 'v3-stable': '3.53.1', 'v4-stable': '4.5.5', latest: '5.0.2' }
$ npm view primevue@4.5.5 license
MIT
$ npm view primevue@5.0.2 license
SEE LICENSE IN LICENSE.md
$ npm view primevue@5.0.2 dependencies
{ ..., '@primeui/license-manager': '^1.0.0' }
$ npm view @primeuix/themes@3.0.1 license      # the PrimeVue 5 theme package
SEE LICENSE IN LICENSE.md
```

`LICENSE.md` in the `primevue@5.0.2` tarball says: "PrimeUI, a family of commercial UI
libraries". It is free (Community License) only for organisations under set revenue, staff and
funding limits, with annual renewal. "A valid license key is required to use this software."
"A missing, invalid, or expired key may cause the software to display a license notice." It
also forbids reverse engineering and redistribution "so that third parties can develop with it".

Reframe is GPL-3.0-or-later (01 §Open questions, item 2), and 09 §Licensing lists PrimeVue
as MIT. Users must be able to rebuild and redistribute the frontend. A licence key and a
proprietary licence make that impossible, so PrimeVue 5 cannot be used.

PrimeVue 4 is still published under the `v4-stable` tag. The last release is 4.5.5
(2026-04-08). Its theme package is `@primeuix/themes` **2.x** (2.0.3, MIT). The 3.x theme
package is for PrimeVue 5 and has the same proprietary licence.

### vue-tsc does not run on TypeScript 7

```console
$ npm view typescript dist-tags
{ ..., latest: '7.0.2', next: '7.1.0-dev.20261011.1' }
$ npm view typescript@7.0.2 exports    # the native (Go) compiler
{ '.': './lib/version.cjs', './unstable/ast': ..., './unstable/sync': ..., ... }
```

vue-tsc 3.3.13 (latest) loads `require.resolve('typescript/lib/tsc')`. TypeScript 7 does not
export that path. With `typescript@7.0.2` installed:

```console
$ npx vue-tsc --noEmit -p tsconfig.app.json
Error [ERR_PACKAGE_PATH_NOT_EXPORTED]: Package subpath './lib/tsc' is not defined by "exports"
in .../node_modules/typescript/package.json
```

The plan needs vue-tsc with `strictTemplates` to check templates (oxlint does not lint them).
TypeScript 6.0.3 (2026-04-16) is the newest release with the JavaScript compiler API.

## Decision

- Use **PrimeVue 4** (`primevue@^4.5.5`) with **`@primeuix/themes@^2.0.3`** (Aura preset). Do
  not add `@primevue/auto-import-resolver` 5.x or any `@primeui/*` package.
- Use **TypeScript 6** (`typescript@~6.0.3`) until vue-tsc supports TypeScript 7.
- The lock file pins the exact versions.

## Consequences

- PrimeVue 4 may get few or no new releases. If it is abandoned, or a security problem is not
  fixed, choose another MIT/Apache UI kit (for example Reka UI or Naive UI) in a new decision
  record. Keep PrimeVue usage behind our own `components/base/` wrappers (F-1) to make such a
  change cheaper.
- Dependency update bots (Q-1.3) must not propose PrimeVue 5, `@primeuix/themes` 3 or
  TypeScript 7. Add ignore rules for these majors when Q-1.3 is set up.
- Revisit TypeScript 7 when a vue-tsc release supports it (check: `npx vue-tsc --version` and
  run `npm run typecheck` with `typescript@7`).
- `THIRD_PARTY_NOTICES` (09 §Licensing) stays correct: PrimeVue 4 is MIT.

## Plan changes

- `02-architecture.md` §Tech stack: Frontend row says TypeScript 6. UI kit row says PrimeVue 4
  (MIT) and not 5.
- `06-web-app.md` §Stack: same.
