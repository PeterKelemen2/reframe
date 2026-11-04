//! Queue progress on the taskbar (and in the tray).
//!
//! Linux: the app's own Unity `LauncherEntry.Update` signal on the session bus, which KDE Plasma
//! and Ubuntu's dock read (Tauri's own call needs libunity). Windows: the taskbar button's bar.

use tauri::AppHandle;

/// The entry the deb and rpm packages install (named after the product); its `StartupWMClass`
/// matches the window's app id, the binary name.
#[cfg(target_os = "linux")]
pub const DESKTOP_ENTRY: &str = "Reframe.desktop";

/// `value` is 0…1, or `None` to clear.
#[tauri::command]
pub async fn set_taskbar_progress(app: AppHandle, value: Option<f64>) {
    crate::tray::show_progress(&app, value);
    show(&app, value).await;
}

#[cfg(target_os = "linux")]
async fn show(_app: &AppHandle, value: Option<f64>) {
    launcher::send(value).await;
}

#[cfg(windows)]
async fn show(app: &AppHandle, value: Option<f64>) {
    use tauri::Manager;
    if let Some(window) = app.get_webview_window("main") {
        // Nothing to report to: the bar is a hint, the queue shows the progress too.
        let _ = window.set_progress_bar(progress_bar(value));
    }
}

#[cfg(not(any(target_os = "linux", windows)))]
async fn show(_app: &AppHandle, _value: Option<f64>) {}

#[cfg_attr(not(windows), allow(dead_code))] // Built and tested everywhere, used on Windows.
fn progress_bar(value: Option<f64>) -> tauri::window::ProgressBarState {
    use tauri::window::{ProgressBarState, ProgressBarStatus};
    match value {
        Some(value) => ProgressBarState {
            status: Some(ProgressBarStatus::Normal),
            progress: Some((value * 100.0).round() as u64),
        },
        None => ProgressBarState {
            status: Some(ProgressBarStatus::None),
            progress: None,
        },
    }
}

#[cfg(target_os = "linux")]
mod launcher {
    use std::collections::HashMap;

    use tokio::sync::OnceCell;
    use zbus::zvariant::Value;
    use zbus::{Connection, Message};

    const PATH: &str = "/org/reframe/desktop/LauncherEntry";
    const INTERFACE: &str = "com.canonical.Unity.LauncherEntry";
    const MEMBER: &str = "Update";

    /// One connection for the app's lifetime; `None` when there is no session bus.
    static BUS: OnceCell<Option<Connection>> = OnceCell::const_new();

    pub fn update(value: Option<f64>) -> zbus::Result<Message> {
        let app_uri = format!("application://{}", super::DESKTOP_ENTRY);
        let properties = HashMap::from([
            ("progress", Value::from(value.unwrap_or(0.0))),
            ("progress-visible", Value::from(value.is_some())),
        ]);
        Message::signal(PATH, INTERFACE, MEMBER)?.build(&(app_uri, properties))
    }

    /// Best effort: without a session bus or a launcher that listens, nothing shows.
    pub async fn send(value: Option<f64>) {
        let bus = BUS
            .get_or_init(|| async { Connection::session().await.ok() })
            .await;
        if let (Some(bus), Ok(message)) = (bus, update(value)) {
            let _ = bus.send(&message).await;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(target_os = "linux")]
    mod launcher_entry {
        use std::collections::HashMap;

        use zbus::zvariant::OwnedValue;

        use super::super::launcher::update;

        fn body(value: Option<f64>) -> (String, HashMap<String, OwnedValue>) {
            update(value).unwrap().body().deserialize().unwrap()
        }

        #[test]
        fn is_the_unity_update_signal() {
            let message = update(Some(0.5)).unwrap();
            let header = message.header();
            assert_eq!(header.message_type(), zbus::message::Type::Signal);
            assert_eq!(
                header.interface().unwrap().as_str(),
                "com.canonical.Unity.LauncherEntry"
            );
            assert_eq!(header.member().unwrap().as_str(), "Update");
            assert!(header.path().unwrap().as_str().starts_with('/'));
            // The wire form: the body is two arguments, not one structure.
            assert_eq!(header.signature().to_string_no_parens(), "sa{sv}");
        }

        #[test]
        fn names_the_desktop_entry_and_shows_the_progress() {
            let (app_uri, properties) = body(Some(0.42));
            assert_eq!(app_uri, "application://Reframe.desktop");
            assert_eq!(f64::try_from(&properties["progress"]).unwrap(), 0.42);
            assert!(bool::try_from(&properties["progress-visible"]).unwrap());
        }

        #[test]
        fn hides_the_bar_when_nothing_runs() {
            let (_, properties) = body(None);
            assert!(!bool::try_from(&properties["progress-visible"]).unwrap());
        }
    }

    #[test]
    fn the_windows_bar_is_a_percentage_and_is_cleared_with_none() {
        use tauri::window::ProgressBarStatus;
        let state = progress_bar(Some(0.426));
        assert!(matches!(state.status, Some(ProgressBarStatus::Normal)));
        assert_eq!(state.progress, Some(43));
        let cleared = progress_bar(None);
        assert!(matches!(cleared.status, Some(ProgressBarStatus::None)));
        assert_eq!(cleared.progress, None);
    }
}
