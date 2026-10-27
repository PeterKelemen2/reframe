// The magnifier's drawing: the fitted frame with the crop overlay and a cursor loupe on the main
// canvas, and the source pixels around each crop line, zoomed with nearest-neighbour sampling,
// on four strip canvases.

export const ZOOM = 4;
export const LOUPE_RADIUS = 80;
/** Source pixels on each side of a crop line in an edge strip. */
export const STRIP_DEPTH = 11;
export const CROP = { top: 140, bottom: 140, left: 96, right: 96 };

const TINT = "rgba(255, 0, 90, 0.35)";
const LINE = "#ffd400";

/** A canvas's 2D context with its backing store at the device pixel ratio, in CSS pixels. */
export function prepare(canvas, width, height) {
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const context = canvas.getContext("2d", { alpha: false });
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return context;
}

/**
 * The redraw of every canvas for a cursor at `cursor` (CSS pixels on the main canvas, or null).
 * `fitted` is the frame already scaled to the main canvas (the "cached" mode) or null, which
 * scales the full 4K bitmap again (the "full" mode).
 */
export function drawAll(view, cursor, fitted) {
  const { image, main, strips } = view;
  const scale = main.width / image.width;
  const source = cursor
    ? { x: clamp(cursor.x / scale, 0, image.width - 1), y: clamp(cursor.y / scale, 0, image.height - 1) }
    : { x: image.width / 2, y: image.height / 2 };
  drawMain(main.context, image, main.width, main.height, scale, fitted);
  if (cursor) drawLoupe(main.context, image, cursor, source);
  drawHorizontalStrip(strips.top, image, source.x, CROP.top);
  drawHorizontalStrip(strips.bottom, image, source.x, image.height - CROP.bottom);
  drawVerticalStrip(strips.left, image, source.y, CROP.left);
  drawVerticalStrip(strips.right, image, source.y, image.width - CROP.right);
}

function drawMain(context, image, width, height, scale, fitted) {
  context.imageSmoothingEnabled = true;
  if (fitted) {
    context.drawImage(fitted, 0, 0, width, height);
  } else {
    context.drawImage(image, 0, 0, image.width, image.height, 0, 0, width, height);
  }
  const top = CROP.top * scale;
  const bottom = height - CROP.bottom * scale;
  const left = CROP.left * scale;
  const right = width - CROP.right * scale;
  context.fillStyle = TINT;
  context.fillRect(0, 0, width, top);
  context.fillRect(0, bottom, width, height - bottom);
  context.fillRect(0, top, left, bottom - top);
  context.fillRect(right, top, width - right, bottom - top);
  context.strokeStyle = LINE;
  context.lineWidth = 1;
  context.strokeRect(left + 0.5, top + 0.5, right - left - 1, bottom - top - 1);
}

function drawLoupe(context, image, cursor, source) {
  const span = (2 * LOUPE_RADIUS) / ZOOM;
  const sx = Math.floor(source.x) - span / 2;
  const sy = Math.floor(source.y) - span / 2;
  context.save();
  context.beginPath();
  context.arc(cursor.x, cursor.y, LOUPE_RADIUS, 0, 2 * Math.PI);
  context.clip();
  context.fillStyle = "#000";
  context.fillRect(cursor.x - LOUPE_RADIUS, cursor.y - LOUPE_RADIUS, 2 * LOUPE_RADIUS, 2 * LOUPE_RADIUS);
  context.imageSmoothingEnabled = false;
  context.drawImage(
    image,
    sx,
    sy,
    span,
    span,
    cursor.x - LOUPE_RADIUS,
    cursor.y - LOUPE_RADIUS,
    2 * LOUPE_RADIUS,
    2 * LOUPE_RADIUS,
  );
  context.restore();
  context.strokeStyle = "#fff";
  context.lineWidth = 2;
  context.beginPath();
  context.arc(cursor.x, cursor.y, LOUPE_RADIUS, 0, 2 * Math.PI);
  context.stroke();
}

/** Rows `line - STRIP_DEPTH … line + STRIP_DEPTH` around a horizontal crop line at `line`. */
function drawHorizontalStrip(strip, image, centreX, line) {
  const { context, width, height } = strip;
  const columns = width / ZOOM;
  const sx = clamp(Math.round(centreX - columns / 2), 0, image.width - columns);
  const sy = line - STRIP_DEPTH;
  context.imageSmoothingEnabled = false;
  context.drawImage(image, sx, sy, columns, 2 * STRIP_DEPTH, 0, 0, width, height);
  context.fillStyle = TINT;
  // The removed rows are above the top line and from the bottom line down.
  if (line < image.height / 2) context.fillRect(0, 0, width, STRIP_DEPTH * ZOOM);
  else context.fillRect(0, STRIP_DEPTH * ZOOM, width, STRIP_DEPTH * ZOOM);
  context.fillStyle = LINE;
  context.fillRect(0, STRIP_DEPTH * ZOOM - 1, width, 2);
}

/** Columns `line - STRIP_DEPTH … line + STRIP_DEPTH` around a vertical crop line at `line`. */
function drawVerticalStrip(strip, image, centreY, line) {
  const { context, width, height } = strip;
  const rows = height / ZOOM;
  const sy = clamp(Math.round(centreY - rows / 2), 0, image.height - rows);
  const sx = line - STRIP_DEPTH;
  context.imageSmoothingEnabled = false;
  context.drawImage(image, sx, sy, 2 * STRIP_DEPTH, rows, 0, 0, width, height);
  context.fillStyle = TINT;
  if (line < image.width / 2) context.fillRect(0, 0, STRIP_DEPTH * ZOOM, height);
  else context.fillRect(STRIP_DEPTH * ZOOM, 0, STRIP_DEPTH * ZOOM, height);
  context.fillStyle = LINE;
  context.fillRect(STRIP_DEPTH * ZOOM - 1, 0, 2, height);
}

/** The frame scaled once to the main canvas, for the "cached" mode. */
export function fitFrame(image, width, height) {
  const canvas = document.createElement("canvas");
  const context = prepare(canvas, width, height);
  context.imageSmoothingEnabled = true;
  context.drawImage(image, 0, 0, image.width, image.height, 0, 0, width, height);
  return canvas;
}

function clamp(value, low, high) {
  return Math.min(Math.max(value, low), high);
}
