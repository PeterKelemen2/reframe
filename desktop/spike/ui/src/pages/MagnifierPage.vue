<script setup>
import { onMounted, ref } from "vue";

import { CROP, ZOOM, drawAll, fitFrame, prepare } from "../magnifier/draw.js";
import { PATH, Run, clockStep, drivePage, pathPoint } from "../magnifier/run.js";
import { api, backend, inTauri, log, option, snapshot } from "../spike.js";

const MAIN = { width: 860, height: 484 };
const HORIZONTAL_STRIP = { width: 372, height: 88 };
const VERTICAL_STRIP = { width: 88, height: 240 };
/** Quiet time after which a pointer move counts as the first of a new movement. */
const QUIET_MS = 300;
/** Quiet time after an external run before the next one may start. */
const REARM_MS = 600;

const status = ref("loading the frame…");
const mainCanvas = ref(null);
const topCanvas = ref(null);
const bottomCanvas = ref(null);
const leftCanvas = ref(null);
const rightCanvas = ref(null);

const seconds = Number(option("seconds") ?? 4);
const pageRuns = Number(option("pageRuns") ?? 3);
const pageModes = (option("pageModes") ?? "full,cached,none").split(",").filter(Boolean);
const externalMode = option("mode") ?? "full";

let view = null;
let fitted = null;
let state = "loading";
let run = null;
let externalLabel = option("drive") ?? "real";
let externalCount = 0;
let lastMove = -Infinity;
let idleCursor = null;
let idleQueued = false;

async function json(response) {
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
}

async function sourceId() {
  const path = option("source");
  if (path) {
    const accepted = await json(
      await api("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths: [path] }),
      }),
    );
    for (;;) {
      const task = await json(await api(`/api/tasks/${accepted.task_id}`));
      if (task.state === "done") return task.result.sources[0].id;
      if (task.state !== "queued" && task.state !== "running") throw new Error(JSON.stringify(task));
      await sleep(100);
    }
  }
  // In the app the check script probes the source through the API; the page takes it from there.
  for (let tries = 0; tries < 600; tries += 1) {
    const sources = await json(await api("/api/sources"));
    if (sources.length > 0) return sources[0].id;
    await sleep(100);
  }
  throw new Error("no source was probed within 60 s");
}

async function loadFrame() {
  const id = await sourceId();
  const asked = performance.now();
  const answer = await json(
    await api("/api/preview/frames", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_id: id, timestamps: [Number(option("at") ?? 2.5)] }),
    }),
  );
  const answered = performance.now();
  const link = answer.frames[0];
  const { baseUrl } = await backend();
  const response = await fetch(`${baseUrl}${link.url}`);
  if (!response.ok) throw new Error(`frame ${response.status}`);
  const blob = await response.blob();
  const fetched = performance.now();
  const image = await createImageBitmap(blob);
  const decoded = performance.now();
  await log({
    check: "magnifier",
    type: "frame",
    answer: { ...answer, frames: answer.frames.map((f) => ({ ...f, url: f.url.split("?")[0] })) },
    signed_query: link.url.includes("?") ? link.url.split("?")[1].replace(/=[^&]*/g, "=…") : null,
    content_type: response.headers.get("content-type"),
    bytes: blob.size,
    bitmap: [image.width, image.height],
    times_ms: {
      frames_route: round(answered - asked),
      png_fetch: round(fetched - answered),
      decode: round(decoded - fetched),
    },
  });
  return image;
}

function strip(canvas, size) {
  return { context: prepare(canvas, size.width, size.height), ...size };
}

function cursorOf(event) {
  const rect = mainCanvas.value.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function redraw(cursor, mode) {
  // "none" keeps the frame loop and the events but draws nothing: Firefox's and WebKitGTK's
  // own frame timing, for comparison.
  if (mode === "none") return;
  drawAll(view, cursor, mode === "cached" ? fitted : null);
}

function onCanvasMove(event) {
  if (state === "armed") startExternal();
  if (run) {
    run.pointer(event, cursorOf(event));
    return;
  }
  if (state === "loading") return;
  idleCursor = cursorOf(event);
  if (!idleQueued) {
    idleQueued = true;
    requestAnimationFrame(() => {
      idleQueued = false;
      redraw(idleCursor, externalMode);
    });
  }
}

function onDocumentMove(event) {
  const now = performance.now();
  if (!run && now - lastMove > QUIET_MS) {
    log({
      check: "magnifier",
      type: "pointer",
      x: event.clientX,
      y: event.clientY,
      trusted: event.isTrusted,
      pointer_type: event.pointerType,
      on_canvas: event.target === mainCanvas.value,
    });
  }
  lastMove = now;
}

async function startExternal() {
  state = "running";
  externalCount += 1;
  run = new Run(externalLabel, externalMode, seconds, (cursor) => redraw(cursor, externalMode));
  status.value = `run ${externalCount} (${externalLabel}) …`;
  run.start();
  const record = await run.done;
  run = null;
  await log({ ...record, index: externalCount });
  state = "cooldown";
  status.value = `run ${externalCount} done`;
  rearm();
}

function rearm() {
  if (performance.now() - lastMove < REARM_MS) {
    setTimeout(rearm, 100);
    return;
  }
  state = "armed";
  status.value = `armed: the next pointer movement over the frame starts run ${externalCount + 1}`;
  log({ check: "magnifier", type: "armed", next: externalCount + 1, label: externalLabel });
}

async function pageDrivenRuns() {
  for (const mode of pageModes) {
    for (let index = 1; index <= pageRuns; index += 1) {
      status.value = `page-driven run ${index} (${mode}) …`;
      run = new Run("page", mode, seconds, (cursor) => redraw(cursor, mode));
      run.start();
      drivePage(run, mainCanvas.value);
      const record = await run.done;
      run = null;
      await log({ ...record, index });
      await sleep(300);
    }
  }
}

function makeView(image, canvases) {
  return {
    image,
    main: { context: prepare(canvases.main, MAIN.width, MAIN.height), ...MAIN },
    strips: {
      top: strip(canvases.top, HORIZONTAL_STRIP),
      bottom: strip(canvases.bottom, HORIZONTAL_STRIP),
      left: strip(canvases.left, VERTICAL_STRIP),
      right: strip(canvases.right, VERTICAL_STRIP),
    },
  };
}

/**
 * Redraws back to back on canvases of their own, without and with a one-pixel read of each
 * canvas after every redraw. The read waits for the drawing to finish, so it shows a redraw's
 * full cost where the frame loop's clock (1 ms in WebKitGTK and Firefox) and a GPU canvas's
 * deferred drawing hide it. Reading pixels can make a browser stop accelerating a canvas, so
 * the shown canvases are never read.
 */
function bench(image) {
  const make = () => document.createElement("canvas");
  const canvases = { main: make(), top: make(), bottom: make(), left: make(), right: make() };
  const scratch = makeView(image, canvases);
  const contexts = [scratch.main.context, ...Object.values(scratch.strips).map((s) => s.context)];
  const result = {};
  for (const mode of ["full", "cached"]) {
    for (const [name, count, read] of [
      ["queued", 120, false],
      ["read_back", 60, true],
    ]) {
      const started = performance.now();
      for (let i = 0; i < count; i += 1) {
        const point = pathPoint(i * PATH.eventEvery, MAIN.width, MAIN.height);
        drawAll(scratch, point, mode === "cached" ? fitted : null);
        if (read) for (const context of contexts) context.getImageData(0, 0, 1, 1);
      }
      result[`${mode}_${name}_ms`] = round((performance.now() - started) / count);
    }
  }
  return result;
}

function layout() {
  const rect = (element) => {
    const box = element.getBoundingClientRect();
    return [box.x, box.y, box.width, box.height].map(round);
  };
  return {
    main: rect(mainCanvas.value),
    strips: {
      top: rect(topCanvas.value),
      bottom: rect(bottomCanvas.value),
      left: rect(leftCanvas.value),
      right: rect(rightCanvas.value),
    },
    bar: rect(document.querySelector(".bar")),
    viewport: [window.innerWidth, window.innerHeight],
    device_pixel_ratio: window.devicePixelRatio,
  };
}

window.spikeMagnifier = {
  label(name) {
    externalLabel = name;
  },
  get state() {
    return state;
  },
};

onMounted(async () => {
  document.addEventListener("pointermove", onDocumentMove, { capture: true });
  const step = clockStep();
  let image;
  try {
    image = await loadFrame();
  } catch (error) {
    status.value = `failed: ${error}`;
    log({ check: "magnifier", type: "failed", error: String(error) });
    return;
  }
  view = makeView(image, {
    main: mainCanvas.value,
    top: topCanvas.value,
    bottom: bottomCanvas.value,
    left: leftCanvas.value,
    right: rightCanvas.value,
  });
  const before = performance.now();
  fitted = fitFrame(image, MAIN.width, MAIN.height);
  const fitMs = round(performance.now() - before);
  redraw({ x: MAIN.width * 0.3, y: MAIN.height * 0.2 }, "full");
  state = "page";
  status.value = "page-driven runs…";
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const shot = inTauri && option("snapshotDir") ? await snapshot("magnifier-webkitgtk.png") : null;
  await log({
    check: "magnifier",
    type: "ready",
    layout: layout(),
    clock_step: step,
    fit_ms: fitMs,
    user_agent: navigator.userAgent,
    path: PATH,
    zoom: ZOOM,
    crop: CROP,
    snapshot: shot,
  });
  await log({ check: "magnifier", type: "bench", ...bench(image) });
  await pageDrivenRuns();
  rearm();
});

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function round(value) {
  return Math.round(value * 1000) / 1000;
}
</script>

<template>
  <div class="magnifier">
    <header>Crop magnifier: {{ ZOOM }}× strips, loupe; crop {{ CROP.top }} / {{ CROP.bottom }} / {{ CROP.left }} / {{ CROP.right }}</header>
    <canvas ref="mainCanvas" class="main" @pointermove="onCanvasMove" />
    <section class="strips">
      <span>Top edge</span>
      <canvas ref="topCanvas" />
      <span>Bottom edge</span>
      <canvas ref="bottomCanvas" />
      <div class="pair">
        <div>
          <span>Left edge</span>
          <canvas ref="leftCanvas" />
        </div>
        <div>
          <span>Right edge</span>
          <canvas ref="rightCanvas" />
        </div>
      </div>
    </section>
    <footer class="bar">{{ status }}</footer>
  </div>
</template>

<style scoped>
.magnifier {
  position: fixed;
  inset: 0;
  background: #1d1f21;
  color: #ddd;
  font: 13px system-ui, sans-serif;
  overflow: hidden;
}
header {
  position: absolute;
  left: 16px;
  top: 12px;
}
.main {
  position: absolute;
  left: 16px;
  top: 44px;
  display: block;
  cursor: crosshair;
}
.strips {
  position: absolute;
  left: 892px;
  top: 44px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.strips canvas {
  display: block;
}
.pair {
  display: flex;
  gap: 16px;
}
.bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 40px;
  line-height: 40px;
  padding: 0 16px;
  background: #2a2d30;
}
</style>
