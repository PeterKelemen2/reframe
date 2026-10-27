// The hooks of the check pages. The same page runs in the app (Tauri) and in a browser that
// loads the built UI with ?page=<name>&base=<url>&token=<token>.
import { invoke } from "@tauri-apps/api/core";

export const inTauri = "__TAURI_INTERNALS__" in window;
const query = new URLSearchParams(window.location.search);
const settings = window.__REFRAME_SPIKE__ ?? {};

/** Every Content-Security-Policy violation since the page started (also sent to `log`). */
export const cspViolations = [];
document.addEventListener("securitypolicyviolation", (event) => {
  const violation = {
    directive: event.effectiveDirective,
    blocked: event.blockedURI,
    source: event.sourceFile,
    line: event.lineNumber,
    sample: event.sample,
    disposition: event.disposition,
    policy: event.originalPolicy,
  };
  cspViolations.push(violation);
  log({ check: "csp", ...violation });
});

/** The page to show: `REFRAME_SPIKE_PAGE` in the app, `?page=` in a browser; null for 4a's page. */
export function pageName() {
  return settings.page ?? query.get("page");
}

/** A query parameter of the browser run, or a setting of the app's (`snapshotDir`). */
export function option(name) {
  return settings[name] ?? query.get(name);
}

/** `{baseUrl, token}` of the sidecar. */
export async function backend() {
  if (inTauri) return invoke("backend_info");
  return { baseUrl: query.get("base"), token: query.get("token") };
}

/** `fetch` against the sidecar with its token. */
export async function api(path, init = {}) {
  const { baseUrl, token } = await backend();
  const headers = { Authorization: `Bearer ${token}`, ...init.headers };
  return fetch(`${baseUrl}${path}`, { ...init, headers });
}

/**
 * One record for the check script. In the app: a JSON line on the shell's stdout,
 * `{"event": "spike_log", "ms": <since the shell's main()>, ...record}`. In a browser: the same
 * object (`ms` from performance.now()) passed to `window.spikeLogSink` when a Playwright script
 * exposed one, kept in `window.__spikeLog`, and written to the console.
 */
export async function log(record) {
  if (inTauri) return invoke("spike_log", { record });
  const line = { ...record, event: "spike_log", ms: performance.now() };
  (window.__spikeLog ??= []).push(line);
  console.log(JSON.stringify(line));
  if (typeof window.spikeLogSink === "function") await window.spikeLogSink(line);
}

/**
 * A PNG of the web view made by WebKitGTK: `{ok: true, path, width, height}`, or
 * `{ok: false, reason}`. A relative path goes into `REFRAME_SPIKE_SNAPSHOT_DIR`.
 */
export async function snapshot(path) {
  if (!inTauri) return { ok: false, reason: "not in the app: take a Playwright screenshot" };
  try {
    return { ok: true, ...(await invoke("snapshot", { path })) };
  } catch (error) {
    return { ok: false, reason: String(error) };
  }
}

/** Resolves after `count` animation frames (the frame that shows a change is painted). */
export function frames(count = 2) {
  return new Promise((resolve) => {
    const step = (left) => (left === 0 ? resolve() : requestAnimationFrame(() => step(left - 1)));
    step(count);
  });
}
