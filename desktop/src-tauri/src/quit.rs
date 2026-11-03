//! Quitting: a close of the main window asks the page first (it shows the running-jobs
//! dialog), then the backend is stopped.
//!
//! Stub until D-3 lands: a close quits at once.
#![allow(dead_code)] // The stub leaves parts of the contract unused.

use tauri::{AppHandle, Manager, RunEvent, Window, WindowEvent};

use crate::backend::Backend;

/// The `quit-requested` event, sent to the main window; the page answers with `quit_app` or
/// does nothing (Cancel).
pub const QUIT_EVENT: &str = "quit-requested";

/// Asks to quit, as a close of the main window does (the tray's Quit).
pub fn request_quit(app: &AppHandle) {
    app.exit(0);
}

pub fn on_window_event(_window: &Window, _event: &WindowEvent) {}

pub fn on_run_event(app: &AppHandle, event: RunEvent) {
    if let RunEvent::Exit = event {
        tauri::async_runtime::block_on(app.state::<Backend>().stop());
    }
}

/// The page handles `quit-requested` from now on.
#[tauri::command]
pub fn quit_ready() {}

/// Stops the backend if this app started it, then exits.
#[tauri::command]
pub async fn quit_app(app: AppHandle) {
    app.state::<Backend>().stop().await;
    app.exit(0);
}

/// Keep running in the tray.
#[tauri::command]
pub fn hide_main_window(app: AppHandle) -> Result<(), String> {
    let window = app.get_webview_window("main").ok_or("no main window")?;
    window.hide().map_err(|error| error.to_string())
}
