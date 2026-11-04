//! The windows: the main window (its size, place and maximised state kept between runs) and the
//! detached preview window.

use tauri::plugin::TauriPlugin;
use tauri::{AppHandle, Manager, Runtime, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_window_state::StateFlags;

const PREVIEW: &str = "preview";

/// Keeps the size, the place and the maximised state of each window. Not whether it was
/// visible: an app quit from the tray would start hidden.
pub fn window_state<R: Runtime>() -> TauriPlugin<R> {
    tauri_plugin_window_state::Builder::new()
        .with_state_flags(StateFlags::SIZE | StateFlags::POSITION | StateFlags::MAXIMIZED)
        .build()
}

// Each window is built hidden and shown after: the plugin restores its state while it is
// built, and a window shown first would jump there.

pub fn create_main_window(app: &AppHandle) -> tauri::Result<()> {
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Reframe")
        .inner_size(1280.0, 800.0)
        .min_inner_size(1100.0, 700.0)
        .visible(false)
        .build()?
        .show()
}

/// Opens the preview window on `/preview/<source_id>`, or focuses it when it is open.
#[tauri::command]
pub async fn open_preview_window(app: AppHandle, source_id: String) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(PREVIEW) {
        let _ = window.unminimize();
        return window.set_focus().map_err(|error| error.to_string());
    }
    if !is_source_id(&source_id) {
        return Err(format!("Not a source id: {source_id:?}"));
    }
    let url = WebviewUrl::App(format!("preview/{source_id}").into());
    let window = WebviewWindowBuilder::new(&app, PREVIEW, url)
        .title("Reframe preview")
        .inner_size(960.0, 720.0)
        .min_inner_size(480.0, 360.0)
        .visible(false)
        .build()
        .map_err(|error| error.to_string())?;
    window.show().map_err(|error| error.to_string())
}

/// The server's source ids are hex; anything else would change the route.
fn is_source_id(value: &str) -> bool {
    !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_alphanumeric())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_source_id_cannot_leave_the_preview_route() {
        assert!(is_source_id("3f9a0c4e1b2d7a8f6e5c4b3a"));
        for other in ["", "../settings", "a/b", "a?b", "a#b", "a b"] {
            assert!(!is_source_id(other), "{other:?}");
        }
    }
}
