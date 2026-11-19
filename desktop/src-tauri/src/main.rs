//! The Reframe desktop app: the shared Vue frontend in a Tauri window, backed by the queue's
//! owner (a running `reframe-server`, or the frozen sidecar this app starts).

// No console window next to the app on Windows (release builds).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod appimage;
mod backend;
mod comfort;
mod desktop_settings;
mod external;
mod media;
mod open_paths;
mod progress;
mod quit;
mod tray;
mod updater;

use tauri::Manager;

fn main() {
    // Until the build: the arguments are read, and a second launch hands over its folder, there.
    let image_folder = appimage::enter_launch_folder();
    // Before the builder: the owner is looked for, and the sidecar started, while GTK and
    // WebKitGTK load.
    let context = tauri::generate_context!();
    let backend = backend::Backend::start(&context);
    let app = tauri::Builder::default()
        // First: a second launch must reach the running app before anything else starts.
        .plugin(open_paths::single_instance())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(comfort::window_state())
        .plugin(updater::updater_plugin())
        .plugin(updater::plugin())
        .manage(backend)
        .manage(open_paths::Pending::from_args(std::env::args_os().skip(1)))
        .invoke_handler(tauri::generate_handler![
            backend::backend_info,
            backend::backend_retry,
            quit::quit_ready,
            quit::quit_app,
            quit::hide_main_window,
            open_paths::take_open_paths,
            progress::set_taskbar_progress,
            comfort::open_preview_window,
            desktop_settings::desktop_settings,
            desktop_settings::set_desktop_settings,
            external::open_external,
            media::webview_plays_video,
        ])
        .on_window_event(quit::on_window_event)
        .setup(|app| {
            app.state::<backend::Backend>().attach(app.handle().clone());
            comfort::create_main_window(app.handle())?;
            tray::setup(app.handle())?;
            Ok(())
        })
        .build(context)
        .expect("the Tauri app is built");
    // The windows, and so WebKit's helper processes, start in `run`.
    appimage::leave_launch_folder(image_folder);
    app.run(quit::on_run_event);
}
