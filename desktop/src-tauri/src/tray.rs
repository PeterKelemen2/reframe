//! The optional tray icon (off by default): queue progress, pause all, show, quit.
//!
//! Stub until D-6 lands: no tray.

use tauri::AppHandle;

/// Creates the tray when the desktop setting is on.
pub fn setup(_app: &AppHandle) -> tauri::Result<()> {
    Ok(())
}

/// `value` is 0…1, or `None` when nothing runs.
pub fn show_progress(_app: &AppHandle, _value: Option<f64>) {}
