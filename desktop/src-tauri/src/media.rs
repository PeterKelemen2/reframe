//! Whether the webview can play a `<video>`. WebKitGTK aborts its web process, instead of
//! reporting a media error, when GStreamer lacks the elements its player creates; an AppImage's
//! AppRun points GStreamer at plugin folders inside the image, which may hold none.

use std::ffi::OsString;
use std::path::{Path, PathBuf};

/// The plugins of `appsink`, `appsrc` and `autoaudiosink`.
const PLAYER_PLUGINS: [&str; 2] = ["libgstapp.so", "libgstautodetect.so"];

/// `false` when GStreamer's system plugin path is set and its folders, with those of the extra
/// plugin path, lack the player's plugins. Unset, GStreamer uses the system's folders: `true`.
pub fn plays_video(
    vars: impl Fn(&str) -> Option<OsString>,
    is_file: impl Fn(&Path) -> bool,
) -> bool {
    let first = |names: [&str; 2]| names.iter().find_map(|name| vars(name));
    let Some(system) = first(["GST_PLUGIN_SYSTEM_PATH_1_0", "GST_PLUGIN_SYSTEM_PATH"]) else {
        return true;
    };
    let extra = first(["GST_PLUGIN_PATH_1_0", "GST_PLUGIN_PATH"]);
    let folders: Vec<PathBuf> = std::env::split_paths(&system)
        .chain(extra.iter().flat_map(std::env::split_paths))
        .filter(|folder| !folder.as_os_str().is_empty())
        .collect();
    PLAYER_PLUGINS
        .iter()
        .all(|plugin| folders.iter().any(|folder| is_file(&folder.join(plugin))))
}

#[tauri::command]
pub fn webview_plays_video() -> bool {
    plays_video(|name| std::env::var_os(name), Path::is_file)
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    fn vars(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<OsString> {
        let pairs: Vec<(String, OsString)> = pairs
            .iter()
            .map(|(name, value)| (name.to_string(), OsString::from(value)))
            .collect();
        move |name| {
            pairs
                .iter()
                .find(|(key, _)| key == name)
                .map(|(_, value)| value.clone())
        }
    }

    fn files(paths: &[&str]) -> impl Fn(&Path) -> bool {
        let paths: Vec<PathBuf> = paths.iter().map(PathBuf::from).collect();
        move |path| paths.iter().any(|file| file == path)
    }

    /// What AppRun sets when nothing set the variables before it.
    fn apprun() -> Vec<(&'static str, &'static str)> {
        vec![
            ("GST_PLUGIN_SYSTEM_PATH", "/tmp/.mount_R/usr/lib/gstreamer:"),
            (
                "GST_PLUGIN_SYSTEM_PATH_1_0",
                "/tmp/.mount_R/usr/lib/gstreamer-1.0:",
            ),
        ]
    }

    #[test]
    fn an_appimage_without_gstreamer_plugins_cannot_play() {
        let system = files(&["/usr/lib/gstreamer-1.0/libgstapp.so"]);
        assert!(!plays_video(vars(&apprun()), system));
    }

    #[test]
    fn an_appimage_with_the_players_plugins_can_play() {
        let image = files(&[
            "/tmp/.mount_R/usr/lib/gstreamer-1.0/libgstapp.so",
            "/tmp/.mount_R/usr/lib/gstreamer-1.0/libgstautodetect.so",
        ]);
        assert!(plays_video(vars(&apprun()), image));
    }

    #[test]
    fn one_of_the_players_plugins_is_not_enough() {
        let image = files(&["/tmp/.mount_R/usr/lib/gstreamer-1.0/libgstapp.so"]);
        assert!(!plays_video(vars(&apprun()), image));
    }

    #[test]
    fn the_extra_plugin_path_counts() {
        let mut pairs = apprun();
        pairs.push(("GST_PLUGIN_PATH_1_0", "/opt/gst"));
        let extra = files(&["/opt/gst/libgstapp.so", "/opt/gst/libgstautodetect.so"]);
        assert!(plays_video(vars(&pairs), extra));
    }

    #[test]
    fn without_a_plugin_path_gstreamer_uses_the_systems_folders() {
        assert!(plays_video(vars(&[]), files(&[])));
    }
}
