//! Updates of an installed app: one check at start, the user's yes, a download that is verified
//! against the release key, then the quit flow (the page's running-jobs question) and the install
//! as the app exits, after the backend has stopped.

use std::sync::Mutex;

use tauri::plugin::TauriPlugin;
use tauri::utils::config::BundleType;
use tauri::utils::platform::bundle_type;
use tauri::{AppHandle, Manager, RunEvent, Wry};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::{Update, UpdaterExt};

struct Pending {
    update: Update,
    bytes: Vec<u8>,
}

/// A downloaded and verified update, installed by the next quit.
static PENDING: Mutex<Option<Pending>> = Mutex::new(None);

pub fn updater_plugin() -> TauriPlugin<Wry, tauri_plugin_updater::Config> {
    tauri_plugin_updater::Builder::new().build()
}

/// The check at start, and the install at exit.
pub fn plugin() -> TauriPlugin<Wry> {
    tauri::plugin::Builder::new("reframe-update")
        .setup(|app, _| {
            check_at_start(app);
            Ok(())
        })
        .on_event(|app, event| {
            if let RunEvent::Exit = event {
                install_pending(app);
            }
        })
        .build()
}

/// A build that no installer made has nothing to replace; the plugin cannot install an rpm (it
/// would take the AppImage path and fail after the user said yes); an MSI is installed per
/// machine, and its updates are the administrator's.
fn updatable(bundle: Option<BundleType>) -> bool {
    matches!(
        bundle,
        Some(BundleType::Nsis | BundleType::AppImage | BundleType::Deb)
    )
}

/// Asks the release endpoint once, in the background. A failed check says nothing: offline is
/// normal.
fn check_at_start(app: &AppHandle) {
    if !updatable(bundle_type()) {
        return;
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        remove_used_installers(&app.package_info().name);
        let Ok(updater) = app.updater() else { return };
        if let Ok(Some(update)) = updater.check().await {
            offer(app, update);
        }
    });
}

/// The plugin keeps the installer it ran in a folder of its own under the temporary folder (a
/// running installer cannot delete itself): the next start removes it. One still in use stays
/// for a later start.
fn remove_used_installers(app_name: &str) {
    let Ok(entries) = std::fs::read_dir(std::env::temp_dir()) else {
        return;
    };
    for entry in entries.flatten() {
        if is_used_installer(&entry.file_name().to_string_lossy(), app_name) {
            let _ = std::fs::remove_dir_all(entry.path());
        }
    }
}

/// The plugin's folder name: `<app name>-<version>-updater-<random>`.
fn is_used_installer(name: &str, app_name: &str) -> bool {
    name.strip_prefix(app_name)
        .and_then(|rest| rest.strip_prefix('-'))
        .and_then(|rest| rest.split_once("-updater-"))
        .is_some_and(|(version, random)| !version.is_empty() && !random.is_empty())
}

fn offer(app: AppHandle, update: Update) {
    let text = format!(
        "Reframe {} is available (this is {}).\n\n\
         Reframe downloads it in the background, then quits to install it and starts again. \
         If jobs are running, you are asked first.",
        update.version, update.current_version
    );
    let mut dialog = app
        .dialog()
        .message(text)
        .title("Update Reframe")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Install and restart".to_owned(),
            "Later".to_owned(),
        ));
    if let Some(window) = app.get_webview_window("main") {
        dialog = dialog.parent(&window);
    }
    dialog.show(move |install| {
        if install {
            tauri::async_runtime::spawn(download(app, update));
        }
    });
}

async fn download(app: AppHandle, update: Update) {
    match update.download(|_, _| {}, || {}).await {
        Ok(bytes) => {
            *lock() = Some(Pending { update, bytes });
            crate::quit::request_quit(&app);
        }
        Err(error) => show_error(&app, &error.to_string()),
    }
}

/// On Windows the installer takes over and this process exits here; elsewhere the new version
/// is started. No dialog can show while the event loop ends: a failed install is offered again
/// at the next start, as the version has not changed.
fn install_pending(app: &AppHandle) {
    let Some(pending) = lock().take() else { return };
    // Plugins see the exit before the app's own handler: the installer must not find the
    // sidecar's files in use.
    tauri::async_runtime::block_on(app.state::<crate::backend::Backend>().stop());
    if pending.update.install(&pending.bytes).is_ok() {
        app.restart();
    }
}

fn show_error(app: &AppHandle, error: &str) {
    app.dialog()
        .message(format!("The update could not be installed.\n\n{error}"))
        .title("Update Reframe")
        .kind(MessageDialogKind::Error)
        .show(|_| {});
}

fn lock() -> std::sync::MutexGuard<'static, Option<Pending>> {
    PENDING
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_an_app_that_its_user_installed_and_the_plugin_can_replace_checks() {
        assert!(updatable(Some(BundleType::Nsis)));
        assert!(updatable(Some(BundleType::AppImage)));
        assert!(updatable(Some(BundleType::Deb)));
        assert!(!updatable(Some(BundleType::Rpm)));
        assert!(!updatable(Some(BundleType::Msi)));
        assert!(!updatable(None));
    }

    #[test]
    fn only_the_plugins_installer_folders_are_removed() {
        assert!(is_used_installer("Reframe-0.1.1-updater-UTeCC4", "Reframe"));
        assert!(is_used_installer("Reframe-1.0.0-rc.1-updater-x", "Reframe"));
        assert!(!is_used_installer("Reframe-notes", "Reframe"));
        assert!(!is_used_installer("Reframe-0.1.1-updater-", "Reframe"));
        assert!(!is_used_installer("Reframe--updater-abc", "Reframe"));
        assert!(!is_used_installer("OtherApp-0.1.1-updater-abc", "Reframe"));
        assert!(!is_used_installer("ReframeX-0.1.1-updater-abc", "Reframe"));
    }
}
