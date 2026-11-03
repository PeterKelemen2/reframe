//! Quitting: a close of the main window asks the page first (it shows the running-jobs
//! dialog), then the backend is stopped. Every way the app ends stops a sidecar it started.

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::{AppHandle, Emitter, Manager, RunEvent, Window, WindowEvent};

use crate::backend::{Backend, BackendState};

/// The `quit-requested` event, sent to the main window; the page answers with `quit_app` or
/// does nothing (Cancel).
pub const QUIT_EVENT: &str = "quit-requested";

const MAIN: &str = "main";

static PAGE_READY: AtomicBool = AtomicBool::new(false);

/// Asks to quit, as a close of the main window does (the tray's Quit). The page is asked only
/// when it can answer; else the app quits at once.
pub fn request_quit(app: &AppHandle) {
    let state = app.state::<Backend>().state();
    if asks_page(PAGE_READY.load(Ordering::SeqCst), &state)
        && let Some(window) = app.get_webview_window(MAIN)
    {
        // The window may be hidden in the tray: the dialog must be seen.
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
        if app.emit_to(MAIN, QUIT_EVENT, ()).is_ok() {
            return;
        }
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move { quit(&app).await });
}

/// A page that never called `quit_ready`, or one without a server to count jobs on, cannot
/// answer: waiting for it would leave a window that does not close.
fn asks_page(page_ready: bool, state: &BackendState) -> bool {
    page_ready && matches!(state, BackendState::Ready { .. })
}

async fn quit(app: &AppHandle) {
    app.state::<Backend>().stop().await;
    app.exit(0);
}

pub fn on_window_event(window: &Window, event: &WindowEvent) {
    if let WindowEvent::CloseRequested { api, .. } = event
        && window.label() == MAIN
    {
        api.prevent_close();
        request_quit(window.app_handle());
    }
}

pub fn on_run_event(app: &AppHandle, event: RunEvent) {
    if let RunEvent::Exit = event {
        tauri::async_runtime::block_on(app.state::<Backend>().stop());
    }
}

/// The page handles `quit-requested` from now on.
#[tauri::command]
pub fn quit_ready() {
    PAGE_READY.store(true, Ordering::SeqCst);
}

/// Stops the backend if this app started it, then exits.
#[tauri::command]
pub async fn quit_app(app: AppHandle) {
    quit(&app).await;
}

/// Keep running in the tray.
#[tauri::command]
pub fn hide_main_window(app: AppHandle) -> Result<(), String> {
    let window = app.get_webview_window(MAIN).ok_or("no main window")?;
    window.hide().map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::BackendError;

    #[test]
    fn the_page_is_asked_only_when_it_can_answer() {
        let ready = BackendState::Ready {
            info: crate::backend::BackendInfo {
                base_url: "http://127.0.0.1:1".to_owned(),
                token: "t".to_owned(),
                instance: "i".to_owned(),
                owned: true,
                private_queue: None,
            },
        };
        let failed = BackendState::Failed {
            error: BackendError {
                message: "m".to_owned(),
                log: None,
            },
        };
        assert!(asks_page(true, &ready));
        assert!(!asks_page(false, &ready));
        assert!(!asks_page(true, &BackendState::Starting));
        assert!(!asks_page(true, &failed));
    }
}
