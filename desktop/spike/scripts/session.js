// KWin script of one window session (windows.py fills in CONFIG). It moves the windows of the
// session's processes to their spot on the secondary output as KWin adds them, keeps each one
// transparent until KWin reports it there, gives the keyboard back to the window that had it,
// and reports each step as a D-Bus call that kwin.Journal watches.
const C = CONFIG;

function log(event, extra) {
  const record = Object.assign({ event: event, script: C.script, t: Date.now() }, extra || {});
  callDBus(C.bus, "/", C.bus, C.member, JSON.stringify(record));
}

function rect(g) {
  return [Math.round(g.x), Math.round(g.y), Math.round(g.width), Math.round(g.height)];
}

function spotOf(w) {
  if (!w) return null;
  return C.pids[String(w.pid)] || C.classes[w.resourceClass] || null;
}

function describe(w) {
  return {
    id: w.internalId.toString(),
    pid: w.pid,
    cls: w.resourceClass,
    normal: w.normalWindow,
    dialog: w.dialog,
    popup: w.popupWindow,
    output: w.output ? w.output.name : null,
    geo: rect(w.frameGeometry),
    opacity: w.opacity,
  };
}

function secondary() {
  return workspace.screens.find(function (s) {
    return s.name === C.secondary;
  });
}

function onSecondary(w) {
  const screen = secondary();
  if (!screen || !w.output || w.output.name !== C.secondary) return false;
  const g = w.frameGeometry;
  const s = screen.geometry;
  return g.x >= s.x && g.y >= s.y && g.x + g.width <= s.x + s.width && g.y + g.height <= s.y + s.height;
}

const hidden = {};

function reveal(w) {
  const id = w.internalId.toString();
  if (hidden[id] && onSecondary(w)) {
    delete hidden[id];
    w.opacity = 1.0;
    log("shown", describe(w));
  }
}

const targets = {};
const MAX_TRIES = 8;

// A move alone takes effect at once; a resize waits for the client, which may answer with a
// size of its own and lose the request: so move first, and ask again while it is not there.
function apply(w) {
  const id = w.internalId.toString();
  const t = targets[id];
  if (!t) return;
  const g = w.frameGeometry;
  const width = t.width || g.width;
  const height = t.height || g.height;
  if (g.x === t.x && g.y === t.y && g.width === width && g.height === height) {
    delete targets[id];
    log("settled", describe(w));
    return;
  }
  if (t.tries >= MAX_TRIES) return;
  t.tries += 1;
  if (g.x !== t.x || g.y !== t.y) w.frameGeometry = { x: t.x, y: t.y, width: g.width, height: g.height };
  if (w.frameGeometry.width !== width || w.frameGeometry.height !== height) {
    w.frameGeometry = { x: t.x, y: t.y, width: width, height: height };
  }
}

function watch(w) {
  w.frameGeometryChanged.connect(function () {
    log("moved", describe(w));
    apply(w);
    reveal(w);
  });
  w.outputChanged.connect(function () {
    log("output", describe(w));
  });
}

function place(w) {
  const spot = spotOf(w);
  const g0 = w.frameGeometry;
  // GTK's X11 helper windows (1x1 at -99,-99) are never shown: leave them where they are.
  if (g0.width <= 1 || g0.height <= 1) {
    log("ignored", describe(w));
    return;
  }
  // Transparent before KWin paints it: KWin may have put it on another output.
  w.opacity = 0.0;
  hidden[w.internalId.toString()] = true;
  log("added", describe(w));
  watch(w);
  if (!(w.normalWindow || w.dialog)) {
    reveal(w);
    return;
  }
  const screen = secondary();
  if (!screen) {
    log("no_output", describe(w));
    return;
  }
  if (spot[0] === null) {
    reveal(w);
    return;
  }
  if (w.fullScreen) w.fullScreen = false;
  // Above the owner's windows on that output, so a drag between ours crosses none of theirs.
  if (C.above) w.keepAbove = true;
  targets[w.internalId.toString()] = {
    x: screen.geometry.x + spot[0],
    y: screen.geometry.y + spot[1],
    width: spot[2],
    height: spot[3],
    tries: 0,
  };
  apply(w);
  log("placed", describe(w));
  reveal(w);
}

function brief(w) {
  return w ? { id: w.internalId.toString(), cls: w.resourceClass, output: w.output.name } : null;
}

let keep = null;
if (C.keep) {
  keep =
    workspace.windowList().find(function (w) {
      return w.internalId.toString() === C.keep;
    }) || null;
}
if (!keep && workspace.activeWindow && !spotOf(workspace.activeWindow)) keep = workspace.activeWindow;
if (keep && spotOf(workspace.activeWindow)) workspace.activeWindow = keep;
log("loaded", { keep: brief(keep), active: brief(workspace.activeWindow) });

workspace.windowList().forEach(function (w) {
  if (spotOf(w)) watch(w);
});

workspace.windowAdded.connect(function (w) {
  if (spotOf(w)) place(w);
  else log("other", { pid: w.pid, cls: w.resourceClass, normal: w.normalWindow, output: w.output ? w.output.name : null });
});

workspace.windowRemoved.connect(function (w) {
  if (w === keep) keep = null;
  if (spotOf(w)) log("removed", { id: w.internalId.toString(), pid: w.pid });
});

workspace.windowActivated.connect(function (w) {
  if (!w) return;
  if (!spotOf(w)) {
    keep = w;
    log("active", { window: brief(w) });
  } else if (!C.guard) {
    log("ours_active", { window: brief(w) });
  } else if (keep) {
    workspace.activeWindow = keep;
    log("kept_active", { by: brief(w), keep: brief(keep), active: brief(workspace.activeWindow) });
  }
});

if (C.cursor) {
  workspace.cursorPosChanged.connect(function () {
    log("cursor", { x: workspace.cursorPos.x, y: workspace.cursorPos.y });
  });
  log("cursor", { x: workspace.cursorPos.x, y: workspace.cursorPos.y });
}
