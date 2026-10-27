//! What the check pages need from the shell: the page to show, a log line on stdout, a PNG of
//! the web view, and the paths of each drag-and-drop event as bytes.

use std::fs::File;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::time::Instant;

use serde_json::{Value, json};
use tauri::{AppHandle, DragDropEvent, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use webkit2gtk::{SnapshotOptions, SnapshotRegion, WebViewExt};

/// Builds the main window from its configuration with the overrides of the environment:
/// `REFRAME_SPIKE_PAGE` (the check page), `REFRAME_SPIKE_SNAPSHOT_DIR` (where relative
/// snapshot paths go), `REFRAME_SPIKE_NO_DRAG_DROP` (WebKitGTK handles drops, not Tauri),
/// `REFRAME_SPIKE_WINDOW_SIZE` (`WxH`) and `REFRAME_SPIKE_WINDOW_POSITION` (`X,Y`; X11 only).
pub fn create_window(app: &AppHandle) -> tauri::Result<WebviewWindow> {
    let config = app
        .config()
        .app
        .windows
        .iter()
        .find(|window| window.label == "main")
        .expect("tauri.conf.json has the main window")
        .clone();
    let mut builder = WebviewWindowBuilder::from_config(app, &config)?;
    let page = std::env::var("REFRAME_SPIKE_PAGE").ok();
    if let Some(page) = &page {
        let snapshot_dir = std::env::var("REFRAME_SPIKE_SNAPSHOT_DIR").ok();
        let settings = json!({ "page": page, "snapshotDir": snapshot_dir });
        builder = builder.initialization_script(format!("window.__REFRAME_SPIKE__ = {settings};"));
    }
    if std::env::var_os("REFRAME_SPIKE_NO_DRAG_DROP").is_some() {
        builder = builder.disable_drag_drop_handler();
    }
    if let Some((width, height)) = pair("REFRAME_SPIKE_WINDOW_SIZE", 'x') {
        builder = builder.inner_size(width, height);
    }
    if let Some((x, y)) = pair("REFRAME_SPIKE_WINDOW_POSITION", ',') {
        builder = builder.position(x, y);
    }
    builder.build()
}

fn pair(name: &str, separator: char) -> Option<(f64, f64)> {
    let value = std::env::var(name).ok()?;
    let (first, second) = value.split_once(separator)?;
    Some((first.trim().parse().ok()?, second.trim().parse().ok()?))
}

/// One JSON line `{"event": "spike_log", "ms": …, …record}`; `event` and `ms` are the shell's.
pub fn log_line(started: Instant, record: Value) -> String {
    let mut line = serde_json::Map::new();
    if let Value::Object(fields) = record {
        line.extend(fields);
    } else {
        line.insert("value".to_owned(), record);
    }
    line.insert("event".to_owned(), json!("spike_log"));
    line.insert(
        "ms".to_owned(),
        json!(started.elapsed().as_secs_f64() * 1000.0),
    );
    Value::Object(line).to_string()
}

fn path_record(path: &Path) -> Value {
    let bytes = path.as_os_str().as_bytes();
    json!({
        "lossy": path.to_string_lossy(),
        "hex": bytes.iter().map(|byte| format!("{byte:02x}")).collect::<String>(),
        "utf8": std::str::from_utf8(bytes).is_ok(),
        "exists": path.exists(),
        "dir": path.is_dir(),
    })
}

/// The drag-and-drop events as Tauri's runtime hands them to the window, before they are
/// serialised for the page (`drop_native` lines; `Over` is left out, it comes per motion).
pub fn on_window_event(started: Instant, event: &WindowEvent) {
    let WindowEvent::DragDrop(event) = event else {
        return;
    };
    let (kind, paths, position) = match event {
        DragDropEvent::Enter { paths, position } => ("enter", Some(paths), Some(position)),
        DragDropEvent::Drop { paths, position } => ("drop", Some(paths), Some(position)),
        DragDropEvent::Leave => ("leave", None, None),
        _ => return,
    };
    let paths: Option<Vec<Value>> =
        paths.map(|paths| paths.iter().map(|path| path_record(path)).collect());
    crate::sidecar::report(
        "drop_native",
        started,
        json!({
            "kind": kind,
            "paths": paths,
            "position": position.map(|position| [position.x, position.y]),
        }),
    );
}

/// A PNG of the web view's visible area, made by WebKitGTK (`webkit_web_view_get_snapshot`).
/// A relative path is taken inside `REFRAME_SPIKE_SNAPSHOT_DIR`.
pub async fn snapshot(window: WebviewWindow, path: String) -> Result<Value, String> {
    let mut target = PathBuf::from(&path);
    if target.is_relative() {
        let folder = std::env::var_os("REFRAME_SPIKE_SNAPSHOT_DIR")
            .ok_or("a relative path needs REFRAME_SPIKE_SNAPSHOT_DIR")?;
        target = PathBuf::from(folder).join(target);
    }
    let (reply, answer) = tokio::sync::oneshot::channel();
    window
        .with_webview(move |webview| {
            webview.inner().snapshot(
                SnapshotRegion::Visible,
                SnapshotOptions::NONE,
                None::<&webkit2gtk::gio::Cancellable>,
                move |result| {
                    let _ = reply.send(save_png(result, &target));
                },
            );
        })
        .map_err(|error| error.to_string())?;
    answer.await.map_err(|error| error.to_string())?
}

fn save_png(
    result: Result<cairo::Surface, webkit2gtk::Error>,
    path: &Path,
) -> Result<Value, String> {
    let surface = result.map_err(|error| format!("snapshot failed: {error}"))?;
    let image = cairo::ImageSurface::try_from(surface)
        .map_err(|_| "the snapshot is not an image surface".to_owned())?;
    let mut file = File::create(path).map_err(|error| format!("{}: {error}", path.display()))?;
    image
        .write_to_png(&mut file)
        .map_err(|error| format!("{}: {error}", path.display()))?;
    Ok(json!({ "path": path, "width": image.width(), "height": image.height() }))
}
