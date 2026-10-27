// A fake KWin for session.js, for the tests (no compositor): the objects, properties and
// signals the script uses, in KWin 6.8's order for a new window (placed on an output,
// activated, then windowAdded). Every assignment the script makes to a window is kept with
// the window's state at that moment.
//
//   node session_fake_kwin.mjs <script.js> <scenario.json>
//
// Scenario: {screens: [{name, geo}], cursor: [x, y], windows: [spec], active: id,
//            add: [spec]}, spec = {id, pid, cls, geo, normal?}. Prints {records, windows,
// active} as JSON.
import fs from "node:fs";
import vm from "node:vm";

class Signal {
  constructor() {
    this.slots = [];
  }
  connect(slot) {
    this.slots.push(slot);
  }
  emit(...values) {
    for (const slot of this.slots) slot(...values);
  }
}

const [scriptPath, scenarioPath] = process.argv.slice(2);
const scenario = JSON.parse(fs.readFileSync(scenarioPath, "utf8"));
const records = [];
const screens = scenario.screens.map((s) => ({
  name: s.name,
  geometry: { x: s.geo[0], y: s.geo[1], width: s.geo[2], height: s.geo[3] },
}));

function outputAt(x, y) {
  return (
    screens.find(
      (s) =>
        x >= s.geometry.x &&
        x < s.geometry.x + s.geometry.width &&
        y >= s.geometry.y &&
        y < s.geometry.y + s.geometry.height,
    ) || null
  );
}

class Window {
  constructor(spec) {
    this.spec = spec;
    this.internalId = { toString: () => spec.id };
    this.pid = spec.pid;
    this.resourceClass = spec.cls;
    this.normalWindow = spec.normal ?? true;
    this.dialog = false;
    this.popupWindow = false;
    this.fullScreen = false;
    this.frameGeometryChanged = new Signal();
    this.outputChanged = new Signal();
    this.history = [];
    this.values = { opacity: 1, keepAbove: false, minimized: false };
    this.geo = { x: spec.geo[0], y: spec.geo[1], width: spec.geo[2], height: spec.geo[3] };
    this.output = this.centreOutput();
  }
  centreOutput() {
    return outputAt(this.geo.x + this.geo.width / 2, this.geo.y + this.geo.height / 2);
  }
  state() {
    return {
      output: this.output ? this.output.name : null,
      geo: [this.geo.x, this.geo.y, this.geo.width, this.geo.height],
      ...this.values,
    };
  }
  set(name, value) {
    this.values[name] = value;
    this.history.push({ set: name, value: value, ...this.state() });
  }
  get frameGeometry() {
    return { ...this.geo };
  }
  set frameGeometry(g) {
    const before = this.output;
    this.geo = { x: g.x, y: g.y, width: g.width, height: g.height };
    this.output = this.centreOutput();
    this.history.push({ set: "frameGeometry", ...this.state() });
    this.frameGeometryChanged.emit();
    if (before !== this.output) this.outputChanged.emit();
  }
  get opacity() {
    return this.values.opacity;
  }
  set opacity(value) {
    this.set("opacity", value);
  }
  get keepAbove() {
    return this.values.keepAbove;
  }
  set keepAbove(value) {
    this.set("keepAbove", value);
  }
  get minimized() {
    return this.values.minimized;
  }
  set minimized(value) {
    this.set("minimized", value);
  }
}

const windows = scenario.windows.map((spec) => new Window(spec));
const workspace = {
  screens: screens,
  cursorPos: { x: scenario.cursor[0], y: scenario.cursor[1] },
  activeScreen: outputAt(scenario.cursor[0], scenario.cursor[1]),
  windowAdded: new Signal(),
  windowRemoved: new Signal(),
  windowActivated: new Signal(),
  cursorPosChanged: new Signal(),
  active: windows.find((w) => w.spec.id === scenario.active) || null,
  get activeWindow() {
    return this.active;
  },
  set activeWindow(w) {
    this.active = w;
    if (w) this.activeScreen = w.output;
    this.windowActivated.emit(w);
  },
  windowList() {
    return windows;
  },
};

function callDBus(bus, path, iface, member, text) {
  records.push(JSON.parse(text));
}

vm.runInNewContext(fs.readFileSync(scriptPath, "utf8"), { workspace, callDBus });

for (const spec of scenario.add || []) {
  const w = new Window(spec);
  windows.push(w);
  workspace.activeWindow = w;
  workspace.windowAdded.emit(w);
}

const result = {};
for (const w of windows) result[w.spec.id] = { history: w.history, ...w.state() };
console.log(
  JSON.stringify({
    records: records,
    windows: result,
    active: workspace.active ? workspace.active.spec.id : null,
  }),
);
