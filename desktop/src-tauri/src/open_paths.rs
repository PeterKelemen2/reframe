//! Paths given on the command line (`reframe-desktop file.mkv folder/`) and by a second launch,
//! waiting until the main window's page takes them.
//!
//! A name that is not valid Unicode arrives with U+FFFD in it (the second launch's plugin
//! converts it that way too): the page reports such a path instead of opening it.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};

use tauri::plugin::TauriPlugin;
use tauri::{Emitter, Manager, Runtime, State};

/// The `open-paths` event, sent to the main window when paths are waiting in `take_open_paths`.
pub const OPEN_PATHS_EVENT: &str = "open-paths";

const MAIN: &str = "main";

/// A second launch hands its paths to this app, which comes to the front; the second process
/// exits 0.
pub fn single_instance<R: Runtime>() -> TauriPlugin<R> {
    tauri_plugin_single_instance::init(|app, argv, cwd| {
        app.state::<Pending>().push(handed_over(argv, &cwd));
        if let Some(window) = app.get_webview_window(MAIN) {
            // The window may be hidden in the tray or minimised.
            let _ = window.show();
            let _ = window.unminimize();
            let _ = window.set_focus();
        }
        // Without a page listening yet, the paths wait: the page takes them at its start.
        let _ = app.emit_to(MAIN, OPEN_PATHS_EVENT, ());
    })
}

/// The plugin's `argv` starts with the executable.
fn handed_over(argv: Vec<String>, cwd: &str) -> Vec<String> {
    absolute_paths(argv.into_iter().skip(1).map(OsString::from), Path::new(cwd))
}

/// Flags are not paths, and a relative path without a known folder to start from is dropped:
/// the server would resolve it against its own folder.
fn absolute_paths(args: impl Iterator<Item = OsString>, cwd: &Path) -> Vec<String> {
    args.filter(|arg| !arg.is_empty() && !arg.as_encoded_bytes().starts_with(b"-"))
        .map(|arg| cwd.join(arg).components().collect::<PathBuf>())
        .filter(|path| path.is_absolute())
        .map(|path| path.to_string_lossy().into_owned())
        .collect()
}

pub struct Pending(Mutex<Vec<String>>);

impl Pending {
    /// The first launch's arguments, without the executable.
    pub fn from_args(args: impl Iterator<Item = OsString>) -> Self {
        let cwd = std::env::current_dir().unwrap_or_default();
        Self(Mutex::new(absolute_paths(args, &cwd)))
    }

    fn push(&self, paths: Vec<String>) {
        self.0
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .extend(paths);
    }

    fn take(&self) -> Vec<String> {
        std::mem::take(&mut self.0.lock().unwrap_or_else(PoisonError::into_inner))
    }
}

/// The waiting paths, once each, in the order they came.
#[tauri::command]
pub fn take_open_paths(pending: State<'_, Pending>) -> Vec<String> {
    pending.take()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn paths(args: &[&str], cwd: &str) -> Vec<String> {
        absolute_paths(args.iter().map(OsString::from), Path::new(cwd))
    }

    #[test]
    fn a_relative_path_is_made_absolute_against_the_launch_folder() {
        assert_eq!(
            paths(&["file1.mkv", "folder/", "./sub/../b.mkv"], "/home/u/films"),
            [
                "/home/u/films/file1.mkv",
                "/home/u/films/folder",
                "/home/u/films/sub/../b.mkv"
            ]
        );
    }

    #[test]
    fn an_absolute_path_stays_as_it_is() {
        assert_eq!(
            paths(&["/media/a.mkv", "/media/season 1/"], "/home/u"),
            ["/media/a.mkv", "/media/season 1"]
        );
    }

    #[test]
    fn spaces_and_accents_are_kept_byte_for_byte() {
        assert_eq!(
            paths(&["Ünnepi film – 2.mkv", "日本語/ä b.mkv"], "/tmp/Ő ű"),
            ["/tmp/Ő ű/Ünnepi film – 2.mkv", "/tmp/Ő ű/日本語/ä b.mkv"]
        );
    }

    #[test]
    fn flags_and_empty_arguments_are_not_paths() {
        assert_eq!(
            paths(&["--display=:1", "-v", "", "a.mkv"], "/m"),
            ["/m/a.mkv"]
        );
    }

    #[test]
    fn a_relative_path_without_a_launch_folder_is_dropped() {
        assert_eq!(paths(&["a.mkv", "/m/b.mkv"], ""), ["/m/b.mkv"]);
    }

    #[cfg(unix)]
    #[test]
    fn a_name_that_is_not_unicode_arrives_marked_for_the_report() {
        use std::os::unix::ffi::OsStringExt;
        let bad = OsString::from_vec(b"bad\xffname.mkv".to_vec());
        assert_eq!(
            absolute_paths([bad].into_iter(), Path::new("/m")),
            ["/m/bad\u{FFFD}name.mkv"]
        );
    }

    #[test]
    fn a_second_launch_gives_its_paths_but_not_its_executable() {
        let argv = vec![
            "/usr/bin/reframe-desktop".to_owned(),
            "other.mkv".to_owned(),
        ];
        assert_eq!(handed_over(argv, "/home/u"), ["/home/u/other.mkv"]);
    }

    #[test]
    fn each_waiting_path_is_taken_once_in_order() {
        let pending = Pending(Mutex::new(vec!["/m/a.mkv".to_owned()]));
        pending.push(vec!["/m/b.mkv".to_owned(), "/m/c".to_owned()]);
        assert_eq!(pending.take(), ["/m/a.mkv", "/m/b.mkv", "/m/c"]);
        assert!(pending.take().is_empty());
        pending.push(vec!["/m/d.mkv".to_owned()]);
        assert_eq!(pending.take(), ["/m/d.mkv"]);
    }
}
