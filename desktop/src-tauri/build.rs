fn main() {
    // With an app manifest, a window may call only the app commands its capability allows.
    let manifest = tauri_build::AppManifest::new().commands(&[
        "backend_info",
        "backend_retry",
        "quit_ready",
        "quit_app",
        "hide_main_window",
        "take_open_paths",
        "set_taskbar_progress",
        "open_preview_window",
        "desktop_settings",
        "set_desktop_settings",
    ]);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(manifest))
        .expect("the Tauri build step");
}
