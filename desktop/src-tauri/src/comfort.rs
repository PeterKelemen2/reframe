//! The windows: the main window (its size and place kept between runs) and the detached
//! preview window.
//!
//! Stub until D-6 lands: a plain main window, no window state, no preview window.

use tauri::plugin::{Builder, TauriPlugin};
use tauri::{AppHandle, Runtime, WebviewUrl, WebviewWindowBuilder};

pub fn window_state<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("reframe-window-state").build()
}

pub fn create_main_window(app: &AppHandle) -> tauri::Result<()> {
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Reframe")
        .inner_size(1280.0, 800.0)
        .min_inner_size(1100.0, 700.0)
        .build()?;
    Ok(())
}

/// Opens (or focuses) the preview window on `/preview/<source_id>`.
#[tauri::command]
pub async fn open_preview_window(_app: AppHandle, _source_id: String) -> Result<(), String> {
    Err("the preview window is not built yet".to_owned())
}
