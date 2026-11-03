//! Settings of the desktop shell itself (not the server's): `desktop.json` in the app's config
//! folder. Fields this version does not know are kept and written back unchanged.

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tauri::{AppHandle, Manager};

const FILE: &str = "desktop.json";

#[derive(Clone, Debug, Default, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopSettings {
    /// The tray icon; closing the window can then keep the app running.
    #[serde(default)]
    pub tray: bool,
}

fn file(app: &AppHandle) -> Result<PathBuf, String> {
    let folder = app
        .path()
        .app_config_dir()
        .map_err(|error| error.to_string())?;
    Ok(folder.join(FILE))
}

/// The file's object; empty when the file is missing or is not a JSON object.
fn document(path: &Path) -> Map<String, Value> {
    fs::read(path)
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

/// The defaults when the file is missing or broken.
pub fn read(path: &Path) -> DesktopSettings {
    serde_json::from_value(Value::Object(document(path))).unwrap_or_default()
}

/// Replaces the known fields; the others stay as they are. The file is replaced whole, so a
/// crash leaves the old one or the new one.
pub fn write(path: &Path, settings: &DesktopSettings) -> io::Result<()> {
    let mut document = document(path);
    if let Value::Object(known) = serde_json::to_value(settings)? {
        document.extend(known);
    }
    if let Some(folder) = path.parent() {
        fs::create_dir_all(folder)?;
    }
    let partial = path.with_extension("json.part");
    fs::write(&partial, serde_json::to_vec_pretty(&document)?)?;
    fs::rename(&partial, path)
}

pub fn load(app: &AppHandle) -> DesktopSettings {
    file(app).map(|path| read(&path)).unwrap_or_default()
}

#[tauri::command]
pub fn desktop_settings(app: AppHandle) -> DesktopSettings {
    load(&app)
}

/// Saves the settings and applies them at once (the tray comes or goes).
#[tauri::command]
pub async fn set_desktop_settings(
    app: AppHandle,
    settings: DesktopSettings,
) -> Result<DesktopSettings, String> {
    // Checked first: a tray that cannot be made is not saved as on.
    if settings.tray {
        crate::tray::check_available()?;
    }
    let path = file(&app)?;
    write(&path, &settings).map_err(|error| error.to_string())?;
    crate::tray::set_enabled(&app, settings.tray)?;
    Ok(read(&path))
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Folder(PathBuf);

    impl Folder {
        fn new(name: &str) -> Self {
            let path = std::env::temp_dir().join(format!(
                "reframe-desktop-settings-{name}-{}",
                std::process::id()
            ));
            let _ = fs::remove_dir_all(&path);
            fs::create_dir_all(&path).unwrap();
            Folder(path)
        }
    }

    impl Drop for Folder {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn a_missing_file_gives_the_tray_off() {
        let folder = Folder::new("missing");
        assert_eq!(read(&folder.0.join(FILE)), DesktopSettings { tray: false });
    }

    #[test]
    fn a_broken_file_gives_the_defaults_and_is_replaced_on_save() {
        let folder = Folder::new("broken");
        let path = folder.0.join(FILE);
        for broken in ["{\"tray\": tru", "[true]", "{\"tray\": \"yes\"}"] {
            fs::write(&path, broken).unwrap();
            assert_eq!(read(&path), DesktopSettings::default(), "{broken}");
        }
        write(&path, &DesktopSettings { tray: true }).unwrap();
        assert_eq!(read(&path), DesktopSettings { tray: true });
    }

    #[test]
    fn a_save_keeps_the_fields_it_does_not_know() {
        let folder = Folder::new("unknown");
        let path = folder.0.join(FILE);
        fs::write(
            &path,
            r#"{"tray": false, "future": {"a": [1, 2]}, "other": "x"}"#,
        )
        .unwrap();
        write(&path, &DesktopSettings { tray: true }).unwrap();
        let saved: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(
            saved,
            serde_json::json!({"tray": true, "future": {"a": [1, 2]}, "other": "x"})
        );
        assert_eq!(read(&path), DesktopSettings { tray: true });
    }

    #[test]
    fn a_save_makes_the_config_folder() {
        let folder = Folder::new("folder");
        let path = folder.0.join("org.reframe.desktop").join(FILE);
        write(&path, &DesktopSettings { tray: true }).unwrap();
        assert_eq!(read(&path), DesktopSettings { tray: true });
        assert!(!path.with_extension("json.part").exists());
    }
}
