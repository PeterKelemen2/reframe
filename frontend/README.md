# Reframe frontend

The Vue 3 single-page app. The web build is served by `reframe-server`. The desktop build runs
inside the Tauri shell. The spec is `docs/plan/06-web-app.md`, Part B.

Stack: Vue 3.5 · TypeScript 6 (strict) · Vite 8 · Pinia · Vue Router · PrimeVue 4 (styled
mode, Aura-based preset) · Lucide (`@lucide/vue`) · vue-i18n · Vitest · oxlint · oxfmt ·
vue-tsc. PrimeVue and TypeScript stay one major behind the latest release; see
`docs/decisions/XXXX-frontend-held-back-majors.md`.

## Commands

Node: the major in `.node-version` (the current LTS). From `frontend/`:

```sh
npm ci
npm run dev:web        # Vite dev server; /api (and the /api/events WebSocket) → 127.0.0.1:8765
npm run lint           # oxlint
npm run fmt            # oxfmt (write); npm run fmt:check in CI
npm run typecheck      # vue-tsc --noEmit (strict templates), app and Node configs
npm test               # vitest run
npm run build:web      # dist/ for reframe-server
npm run build:desktop  # dist/ for Tauri (VITE_PLATFORM=desktop)
```

## Platform builds

`src/platform/index.ts` picks the `Platform` implementation from `VITE_PLATFORM`. The value
comes from `.env` (`web`, the default) or `.env.desktop` (`vite build --mode desktop`). The
scripts use `--mode` instead of an environment-variable prefix, so they work on Windows too.
`vite.config.ts` rejects any other value. The condition is constant at build time, so the web
bundle does not contain `desktop.ts`, and the desktop bundle does not contain `web.ts`.

## Linting and type checks

- oxlint (`.oxlintrc.json`) runs the `eslint`, `oxc`, `typescript`, `vue`, `import`, `unicorn`
  and `promise` plugins (plus `vitest` for `*.test.ts`). Correctness rules are errors.
- oxlint lints the `<script>` / `<script setup lang="ts">` blocks of `.vue` files. Checked on
  2026-10-11 with oxlint 1.87.0: a scratch `.vue` file gave `typescript(no-explicit-any)`,
  `eslint(no-debugger)`, `promise(param-names)`, `vue(no-export-in-script-setup)` and
  `vue(valid-define-props)` errors. It does not lint `<template>`.
- vue-tsc checks the templates (`vueCompilerOptions.strictTemplates`). Checked the same day: an
  unknown component, an unknown prop and an unknown event on a PrimeVue `Message`, and an
  undefined template variable all fail `npm run typecheck`. `data-*` attributes are allowed
  (`dataAttributes`).
- The tsconfigs are not `composite`/incremental. A stale `.tsbuildinfo` hid changes to
  `vueCompilerOptions`, so `npm run typecheck` always checks from scratch.

## Formatting

oxfmt is pinned to an exact version (`0.72.0`, no `^`) because it is still in beta and its
output can change between releases. Update it on purpose, run `npm run fmt`, and commit the
version bump and the reformatted files together.

Settings (`.oxfmtrc.json`): print width 100, 2 spaces, no semicolons, single quotes, trailing
commas, LF. `sortPackageJson` is off. `package-lock.json` and `dist/` are ignored.
`.gitattributes` keeps LF line endings on Windows checkouts, so `fmt:check` passes there too.

Checked on 2026-10-11 with oxfmt 0.72.0 on two badly formatted `.vue` files with templates:

- oxfmt formats **all three blocks** of a `.vue` file: `<script setup lang="ts">` (as
  TypeScript), `<template>` (as Vue HTML) and `<style scoped>` (as CSS). The output matches
  Prettier's Vue formatting: one attribute per line when a tag is too long, `{{ x }}`
  interpolation spacing, wrapped text, and attribute order kept.
- With the default `htmlWhitespaceSensitivity: "css"`, inline content next to a closing tag
  gives Prettier's `Hello</Message\n>` pattern. Put text on its own line to avoid it.
- The content of `<pre>` and `<textarea>` is not changed.
- A second run changes nothing (`oxfmt --check` passes on its own output).
- In this project oxfmt also formats `.ts`, `.json`, `.css`, `.html` and `.md` files.
