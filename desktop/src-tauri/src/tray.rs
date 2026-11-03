//! The optional tray icon (off by default): queue progress, pause all, show, quit.

use std::sync::Mutex;

use tauri::menu::{Menu, MenuEvent, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager};

use crate::backend::Backend;

const ID: &str = "reframe";
const PROGRESS: &str = "progress";
const PAUSE: &str = "pause";
const SHOW: &str = "show";
const QUIT: &str = "quit";

struct Shown {
    /// Kept while the tray is off, so a tray switched on during a run shows it at once.
    progress: Option<f64>,
    item: Option<MenuItem<tauri::Wry>>,
}

static SHOWN: Mutex<Shown> = Mutex::new(Shown {
    progress: None,
    item: None,
});

/// Creates the tray when the desktop setting is on.
pub fn setup(app: &AppHandle) -> tauri::Result<()> {
    // A library removed since the setting was saved: the app starts without a tray.
    if crate::desktop_settings::load(app).tray && check_available().is_ok() {
        create(app)?;
    }
    Ok(())
}

/// Shows or hides the tray at once.
pub fn set_enabled(app: &AppHandle, on: bool) -> Result<(), String> {
    // Hidden, not removed: on Linux a removed tray's item stays on the bus, and a new one under
    // the same id then cannot register.
    match app.tray_by_id(ID) {
        Some(tray) => tray.set_visible(on).map_err(|error| error.to_string()),
        None if on => create(app).map_err(|error| error.to_string()),
        None => Ok(()),
    }
}

/// `value` is 0…1, or `None` when nothing runs.
pub fn show_progress(app: &AppHandle, value: Option<f64>) {
    let item = {
        let mut shown = lock();
        shown.progress = value;
        shown.item.clone()
    };
    // Outside the lock: each call waits for the main thread.
    if let Some(item) = item {
        let text = progress_text(value);
        let _ = item.set_text(&text);
        if let Some(tray) = app.tray_by_id(ID) {
            let _ = tray.set_tooltip(Some(format!("Reframe: {text}")));
        }
    }
}

fn lock() -> std::sync::MutexGuard<'static, Shown> {
    SHOWN
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn progress_text(value: Option<f64>) -> String {
    match value {
        Some(value) => format!("Queue: {:.0} %", value * 100.0),
        None => "No job is running".to_owned(),
    }
}

fn create(app: &AppHandle) -> tauri::Result<()> {
    let text = progress_text(lock().progress);
    let progress = MenuItem::with_id(app, PROGRESS, &text, false, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &progress,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, PAUSE, "Pause all", true, None::<&str>)?,
            &MenuItem::with_id(app, SHOW, "Show Reframe", true, None::<&str>)?,
            &MenuItem::with_id(app, QUIT, "Quit", true, None::<&str>)?,
        ],
    )?;
    let mut builder = TrayIconBuilder::with_id(ID)
        .menu(&menu)
        .tooltip(format!("Reframe: {text}"))
        .on_menu_event(on_menu_event);
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    lock().item = Some(progress);
    Ok(())
}

fn on_menu_event(app: &AppHandle, event: MenuEvent) {
    match event.id().as_ref() {
        PAUSE => {
            let app = app.clone();
            tauri::async_runtime::spawn(async move {
                // The page shows the queue's state; a server that is not ready has nothing to pause.
                let _ = app
                    .state::<Backend>()
                    .request("POST", "/api/queue/pause")
                    .await;
            });
        }
        SHOW => {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }
        QUIT => crate::quit::request_quit(app),
        _ => {}
    }
}

/// Linux loads the indicator library when the tray is made, and panics without it.
pub fn check_available() -> Result<(), String> {
    #[cfg(target_os = "linux")]
    if !any_loads(&[c"libayatana-appindicator3.so.1", c"libappindicator3.so.1"]) {
        return Err(
            "The tray needs the library libayatana-appindicator3 (or libappindicator3), \
             which is not installed"
                .to_owned(),
        );
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn any_loads(libraries: &[&std::ffi::CStr]) -> bool {
    libraries.iter().any(|library| {
        // SAFETY: `library` is a NUL-terminated name. The handle stays open: the tray opens the
        // same library later, so its initialisers run once either way.
        !unsafe { libc::dlopen(library.as_ptr(), libc::RTLD_LAZY) }.is_null()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_progress_line_is_a_rounded_percentage() {
        assert_eq!(progress_text(Some(0.426)), "Queue: 43 %");
        assert_eq!(progress_text(Some(0.0)), "Queue: 0 %");
        assert_eq!(progress_text(Some(1.0)), "Queue: 100 %");
    }

    #[test]
    fn the_progress_line_says_when_nothing_runs() {
        assert_eq!(progress_text(None), "No job is running");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn a_missing_indicator_library_is_found_before_the_tray_is_made() {
        assert!(!any_loads(&[c"libreframe-no-such-library.so.1"]));
        assert!(any_loads(&[
            c"libreframe-no-such-library.so.1",
            c"libc.so.6"
        ]));
    }
}
