//! Paths given on the command line (`reframe-desktop file.mkv folder/`) and by a second launch.
//!
//! Stub until D-5 lands: no single-instance forwarding; the first launch's arguments are kept.
#![allow(dead_code)] // The stub leaves parts of the contract unused.

use std::ffi::OsString;
use std::sync::Mutex;

use tauri::plugin::{Builder, TauriPlugin};
use tauri::{Runtime, State};

/// The `open-paths` event, sent to the main window when paths are waiting in `take_open_paths`.
pub const OPEN_PATHS_EVENT: &str = "open-paths";

pub fn single_instance<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("reframe-open-paths").build()
}

pub struct Pending(Mutex<Vec<String>>);

impl Pending {
    pub fn from_args(args: impl Iterator<Item = OsString>) -> Self {
        Self(Mutex::new(
            args.map(|arg| arg.to_string_lossy().into_owned()).collect(),
        ))
    }
}

/// The waiting paths, once each.
#[tauri::command]
pub fn take_open_paths(pending: State<'_, Pending>) -> Vec<String> {
    std::mem::take(&mut pending.0.lock().expect("pending paths"))
}
