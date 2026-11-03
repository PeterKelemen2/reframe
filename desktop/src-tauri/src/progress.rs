//! Queue progress on the taskbar (and in the tray).
//!
//! Stub until D-4 lands: only the tray hears of it.
#![allow(dead_code)] // The stub leaves parts of the contract unused.

use tauri::AppHandle;

/// The desktop entry the launcher matches the window to (the Wayland app id is the binary name).
pub const DESKTOP_ENTRY: &str = "reframe-desktop.desktop";

/// `value` is 0…1, or `None` to clear.
#[tauri::command]
pub fn set_taskbar_progress(app: AppHandle, value: Option<f64>) {
    crate::tray::show_progress(&app, value);
}
