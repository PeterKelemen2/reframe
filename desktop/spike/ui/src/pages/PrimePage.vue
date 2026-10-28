<script>
import PrimeVue from "primevue/config";
import ToastService from "primevue/toastservice";

import { primeVueOptions } from "../prime/theme.js";

export function install(app) {
  app.use(PrimeVue, primeVueOptions);
  app.use(ToastService);
}
</script>

<script setup>
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dialog from "primevue/dialog";
import Select from "primevue/select";
import Slider from "primevue/slider";
import Tab from "primevue/tab";
import TabList from "primevue/tablist";
import TabPanel from "primevue/tabpanel";
import TabPanels from "primevue/tabpanels";
import Tabs from "primevue/tabs";
import Toast from "primevue/toast";
import { useToast } from "primevue/usetoast";
import { nextTick, onMounted, ref } from "vue";

import { DARK_MODE_CLASS } from "../prime/theme.js";
import { api, cspViolations, frames, log, option, snapshot } from "../spike.js";

const THEMES = ["light", "dark"];
const STATES = ["base", "select", "dialog"];
// Long enough for PrimeVue's enter transitions (Dialog, Select overlay, Toast).
const SETTLE_MS = 700;

const codecs = ["HEVC", "AVC", "AV1", "VP9"];
const statuses = ["Queued", "Encoding", "Done", "Failed", "Paused"];
const rows = Array.from({ length: 200 }, (_, index) => ({
  id: index + 1,
  name: `Show.Name.S${String(1 + Math.floor(index / 20)).padStart(2, "0")}E${String(1 + (index % 20)).padStart(2, "0")}.1080p.BluRay.mkv`,
  codec: codecs[index % codecs.length],
  duration: `${40 + (index % 17)}:${String((index * 7) % 60).padStart(2, "0")}`,
  size: `${(1.1 + (index % 23) * 0.37).toFixed(2)} GB`,
  status: statuses[index % statuses.length],
}));

const languages = ref([]);
const language = ref(null);
const quality = ref(22);
const tab = ref("queue");
const dialogVisible = ref(false);
const select = ref(null);
const toast = useToast();

function box(selector) {
  const element = document.querySelector(selector);
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  return [rect.x, rect.y, rect.width, rect.height].map((value) => Math.round(value * 100) / 100);
}

function font(selector) {
  const element = document.querySelector(selector);
  if (!element) return null;
  const style = getComputedStyle(element);
  return `${style.fontWeight} ${style.fontSize}/${style.lineHeight} ${style.fontFamily}`;
}

// A deliberate violation: shows that the policy is in force and which one it is.
function cspProbe() {
  try {
    eval("1");
    return "eval ran: no script-src policy";
  } catch (error) {
    return `eval refused: ${error.name}`;
  }
}

function measure() {
  const scroller = document.querySelector(".p-datatable-table-container");
  const bodyRows = [...document.querySelectorAll(".p-datatable-tbody > tr")];
  const body = getComputedStyle(document.body);
  return {
    viewport: [window.innerWidth, window.innerHeight, window.devicePixelRatio],
    userAgent: navigator.userAgent,
    font: { family: body.fontFamily, size: body.fontSize },
    tabFont: font(".p-tab"),
    buttonFont: font(".p-button-label"),
    scrollbar: scroller ? scroller.offsetWidth - scroller.clientWidth : null,
    rows: bodyRows.length,
    rowHeights: bodyRows.slice(0, 3).map((row) => row.getBoundingClientRect().height),
    lastRowTop: bodyRows.length ? bodyRows.at(-1).offsetTop : null,
    header: box(".p-datatable-thead > tr > th"),
    table: box(".p-datatable"),
    tablist: box(".p-tablist"),
    tab: box(".p-tab"),
    select: box(".p-select"),
    overlay: box(".p-select-overlay"),
    option: box(".p-select-option"),
    slider: box(".p-slider"),
    handle: box(".p-slider-handle"),
    button: box(".p-button"),
    dialog: box(".p-dialog"),
    toast: box(".p-toast-message"),
  };
}

async function apply(theme, state) {
  document.documentElement.classList.toggle(DARK_MODE_CLASS, theme === "dark");
  dialogVisible.value = state === "dialog";
  if (state === "select") select.value.show();
  else select.value.hide();
  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
  await frames(2);
  return measure();
}

async function snapshotAll() {
  for (const theme of THEMES) {
    for (const state of STATES) {
      const metrics = await apply(theme, state);
      const shot = await snapshot(`webkitgtk-${theme}-${state}.png`);
      await log({ check: "prime", type: "state", theme, state, metrics, snapshot: shot });
    }
  }
  await apply("light", "base");
  await log({ check: "prime", type: "done", csp: cspViolations });
}

onMounted(async () => {
  try {
    const answer = await api("/api/languages");
    const body = await answer.json();
    languages.value = body.languages
      .slice(0, 40)
      .map((entry) => ({ label: `${entry.english_name} (${entry.native_name})`, value: entry.tag }));
  } catch (error) {
    await log({ check: "prime", type: "languages_failed", error: String(error) });
  }
  language.value = languages.value[3]?.value ?? null;
  toast.add({ severity: "info", summary: "Encode queued", detail: "Show.Name.S01E01.1080p.BluRay.mkv" });
  window.spikePrime = { apply, measure, themes: THEMES, states: STATES };
  await apply("light", "base");
  // From the page itself: an evaluate call of a test driver may be exempt from the policy.
  await log({ check: "prime", type: "csp_probe", probe: cspProbe() });
  await log({ check: "prime", type: "ready", languages: languages.value.length });
  if (option("snapshotDir")) await snapshotAll();
});
</script>

<template>
  <main class="prime">
    <Toast />
    <header class="prime-bar">
      <h1>PrimeVue check</h1>
      <Select ref="select" v-model="language" :options="languages" option-label="label" option-value="value" placeholder="Audio language" class="prime-select" />
      <div class="prime-quality">
        <span>Quality {{ quality }}</span>
        <Slider v-model="quality" :min="0" :max="51" class="prime-slider" />
      </div>
      <Button label="Encode settings" @click="dialogVisible = true" />
    </header>
    <Tabs v-model:value="tab">
      <TabList>
        <Tab value="queue">Queue</Tab>
        <Tab value="video">Video</Tab>
        <Tab value="audio">Audio</Tab>
      </TabList>
      <TabPanels>
        <TabPanel value="queue">
          <DataTable :value="rows" scrollable scroll-height="380px" size="small" data-key="id">
            <Column field="id" header="#" />
            <Column field="name" header="Source" />
            <Column field="codec" header="Codec" />
            <Column field="duration" header="Duration" />
            <Column field="size" header="Size" />
            <Column field="status" header="Status" />
          </DataTable>
        </TabPanel>
        <TabPanel value="video"><p>Video settings</p></TabPanel>
        <TabPanel value="audio"><p>Audio settings</p></TabPanel>
      </TabPanels>
    </Tabs>
    <Dialog v-model:visible="dialogVisible" modal header="Encode settings" :style="{ width: '28rem' }">
      <p>Encoder: x265, preset slow, CRF {{ quality }}.</p>
      <div class="prime-dialog-buttons">
        <Button label="Cancel" severity="secondary" @click="dialogVisible = false" />
        <Button label="Save" @click="dialogVisible = false" />
      </div>
    </Dialog>
  </main>
</template>

<style>
/* The body rules of frontend/src/styles/main.css. */
html,
body {
  height: 100%;
  margin: 0;
}
body {
  background: var(--p-content-background);
  color: var(--p-text-color);
  font-family: system-ui, sans-serif;
}
.prime {
  padding: 0.75rem 1.25rem;
}
.prime-bar {
  display: flex;
  gap: 1.25rem;
  align-items: center;
}
.prime-bar h1 {
  font-size: 1.25rem;
  margin: 0 1rem 0 0;
}
.prime-select {
  width: 14rem;
}
.prime-quality {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  width: 12rem;
}
.prime-dialog-buttons {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
</style>
