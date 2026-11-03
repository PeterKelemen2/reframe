//! Settings of the desktop shell itself (not the server's): kept in the app's config folder.
//!
//! Stub until D-6 lands: the defaults, not saved.

use serde::{Deserialize, Serialize};
use tauri::AppHandle;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopSettings {
    /// The tray icon; closing the window can then keep the app running.
    pub tray: bool,
}

#[tauri::command]
pub fn desktop_settings(_app: AppHandle) -> DesktopSettings {
    DesktopSettings::default()
}

#[tauri::command]
pub fn set_desktop_settings(
    _app: AppHandle,
    settings: DesktopSettings,
) -> Result<DesktopSettings, String> {
    Ok(settings)
}
