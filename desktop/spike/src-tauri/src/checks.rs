//! What the check pages need from the shell: the page to show, a log line on stdout, a PNG of
//! the web view, and the paths of each drag-and-drop event as bytes.

use std::fs::OpenOptions;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Component, Path, PathBuf};
use std::time::Instant;

use serde_json::{Value, json};
use tauri::{AppHandle, DragDropEvent, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use webkit2gtk::{SnapshotOptions, SnapshotRegion, WebViewExt};

/// Builds the main window from its configuration with the overrides of the environment:
/// `REFRAME_SPIKE_PAGE` (the check page), `REFRAME_SPIKE_SNAPSHOT_DIR` (where relative
/// snapshot paths go), `REFRAME_SPIKE_NO_DRAG_DROP` (WebKitGTK handles drops, not Tauri),
/// `REFRAME_SPIKE_WINDOW_SIZE` (`WxH`) and `REFRAME_SPIKE_WINDOW_POSITION` (`X,Y`; X11 only).
/// WebKitGTK keeps its data and caches in `data_dir`; without one it keeps nothing.
pub fn create_window(app: &AppHandle, data_dir: Option<PathBuf>) -> tauri::Result<WebviewWindow> {
    let config = app
        .config()
        .app
        .windows
        .iter()
        .find(|window| window.label == "main")
        .expect("tauri.conf.json has the main window")
        .clone();
    let mut builder = WebviewWindowBuilder::from_config(app, &config)?;
    builder = match data_dir {
        Some(folder) => builder.data_directory(folder),
        None => builder.incognito(true),
    };
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

/// A PNG of the web view's visible area, made by WebKitGTK (`webkit_web_view_get_snapshot`),
/// written below `REFRAME_SPIKE_SNAPSHOT_DIR` only (see [`snapshot_target`]).
pub async fn snapshot(window: WebviewWindow, path: String) -> Result<Value, String> {
    let folder = std::env::var_os("REFRAME_SPIKE_SNAPSHOT_DIR").map(PathBuf::from);
    let target = snapshot_target(folder.as_deref(), Path::new(&path))?;
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

/// Where [`snapshot`] may write `path`: below `folder` (a relative path is taken inside it),
/// not through `..` and not through a symlink that leads out of it. The error says why not.
pub fn snapshot_target(folder: Option<&Path>, path: &Path) -> Result<PathBuf, String> {
    let shown = path.display();
    let folder = folder.ok_or("a snapshot needs REFRAME_SPIKE_SNAPSHOT_DIR")?;
    if path.components().any(|part| part == Component::ParentDir) {
        return Err(format!("{shown}: `..` is not allowed in a snapshot path"));
    }
    let joined = folder.join(path);
    let (Some(parent), Some(name)) = (joined.parent(), joined.file_name()) else {
        return Err(format!("{shown}: not a file path"));
    };
    let real = |path: &Path| {
        path.canonicalize()
            .map_err(|error| format!("{}: {error}", path.display()))
    };
    let (root, parent) = (real(folder)?, real(parent)?);
    if !parent.starts_with(&root) {
        return Err(format!(
            "{shown}: outside the snapshot folder {}",
            root.display()
        ));
    }
    let target = parent.join(name);
    if target.is_symlink() {
        return Err(format!("{shown}: a symlink; snapshots do not follow one"));
    }
    Ok(target)
}

fn save_png(
    result: Result<cairo::Surface, webkit2gtk::Error>,
    path: &Path,
) -> Result<Value, String> {
    let surface = result.map_err(|error| format!("snapshot failed: {error}"))?;
    let image = cairo::ImageSurface::try_from(surface)
        .map_err(|_| "the snapshot is not an image surface".to_owned())?;
    // O_NOFOLLOW: a symlink put in the folder after the check is not followed out of it.
    let mut file = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|error| format!("{}: {error}", path.display()))?;
    image
        .write_to_png(&mut file)
        .map_err(|error| format!("{}: {error}", path.display()))?;
    Ok(json!({ "path": path, "width": image.width(), "height": image.height() }))
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::os::unix::fs::symlink;

    use super::*;

    /// A snapshot folder with a subfolder, next to a folder outside it.
    struct Folders {
        top: PathBuf,
        shots: PathBuf,
        outside: PathBuf,
    }

    impl Folders {
        fn new(name: &str) -> Self {
            let top = std::env::temp_dir()
                .join(format!("reframe-spike-test-{name}-{}", std::process::id()));
            let shots = top.join("shots");
            let outside = top.join("outside");
            fs::create_dir_all(shots.join("sub")).unwrap();
            fs::create_dir_all(&outside).unwrap();
            Self {
                top,
                shots,
                outside,
            }
        }

        fn target(&self, path: impl AsRef<Path>) -> Result<PathBuf, String> {
            snapshot_target(Some(&self.shots), path.as_ref())
        }
    }

    impl Drop for Folders {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.top);
        }
    }

    #[test]
    fn a_path_below_the_folder_is_written_there() {
        let folders = Folders::new("inside");
        let real = folders.shots.canonicalize().unwrap();
        assert_eq!(folders.target("a.png"), Ok(real.join("a.png")));
        let absolute = folders.shots.join("sub").join("b.png");
        assert_eq!(folders.target(absolute), Ok(real.join("sub").join("b.png")));
    }

    #[test]
    fn a_path_out_of_the_folder_is_refused_with_its_reason() {
        let folders = Folders::new("outside");
        symlink(&folders.outside, folders.shots.join("link")).unwrap();
        symlink(folders.outside.join("x.png"), folders.shots.join("x.png")).unwrap();
        let refused = [
            (folders.outside.join("a.png"), "outside the snapshot folder"),
            (PathBuf::from("../outside/a.png"), "`..` is not allowed"),
            (
                folders.shots.join("sub/../../outside/a.png"),
                "`..` is not allowed",
            ),
            (PathBuf::from("link/a.png"), "outside the snapshot folder"),
            (PathBuf::from("x.png"), "a symlink"),
        ];
        for (path, reason) in refused {
            let answer = folders.target(&path);
            assert!(
                answer.as_ref().is_err_and(|error| error.contains(reason)),
                "{}: {answer:?}",
                path.display()
            );
        }
    }

    #[test]
    fn without_a_snapshot_folder_nothing_is_written() {
        let answer = snapshot_target(None, Path::new("/tmp/a.png"));
        assert!(answer.is_err_and(|error| error.contains("REFRAME_SPIKE_SNAPSHOT_DIR")));
    }
}
