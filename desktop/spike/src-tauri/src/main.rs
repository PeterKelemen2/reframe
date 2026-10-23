//! The D-0 spike: a Tauri 2 window whose page shows `GET /api/health` of its sidecar.
//!
//! For the measurement scripts it prints JSON lines on stdout and quits (as a closed window
//! does) when stdin gives the line `quit`.

#[cfg(not(target_os = "linux"))]
compile_error!("The D-0 spike runs on Linux only.");

mod sidecar;

use std::io::BufRead;
use std::time::Instant;

use serde_json::json;
use tauri::{AppHandle, Manager, RunEvent, State};

use crate::sidecar::{BackendInfo, Sidecar};

struct Started(Instant);

#[tauri::command]
async fn backend_info(sidecar: State<'_, Sidecar>) -> Result<BackendInfo, String> {
    sidecar.info().await
}

/// The page shows the health answer. `REFRAME_SPIKE_EXIT_AFTER_HEALTH` quits then, for the
/// cold-start runs.
#[tauri::command]
fn page_ready(
    app: AppHandle,
    started: State<'_, Started>,
    origin: String,
    times: serde_json::Value,
) {
    sidecar::report(
        "page_health",
        started.0,
        json!({ "origin": origin, "page": times }),
    );
    if std::env::var_os("REFRAME_SPIKE_EXIT_AFTER_HEALTH").is_some() {
        app.exit(0);
    }
}

/// The page shows that the server is not running.
#[tauri::command]
fn page_failed(started: State<'_, Started>, message: String) {
    sidecar::report("page_failed", started.0, json!({ "message": message }));
}

fn quit_on_stdin(app: AppHandle) {
    std::thread::spawn(move || {
        for line in std::io::stdin().lock().lines() {
            match line {
                Ok(line) if line.trim() == "quit" => {
                    app.exit(0);
                    return;
                }
                Ok(_) => {}
                Err(_) => return,
            }
        }
    });
}

fn main() {
    let started = Instant::now();
    // Started before the window, so the server starts while GTK and WebKitGTK load.
    // `REFRAME_SPIKE_SPAWN_IN_SETUP` starts it in the setup hook instead, to compare.
    let in_setup = std::env::var_os("REFRAME_SPIKE_SPAWN_IN_SETUP").is_some();
    let early = (!in_setup).then(|| sidecar::spawn(started));
    let app = tauri::Builder::default()
        .manage(Started(started))
        .invoke_handler(tauri::generate_handler![
            backend_info,
            page_ready,
            page_failed
        ])
        .setup(move |app| {
            let sidecar = early.unwrap_or_else(|| sidecar::spawn(started));
            sidecar.attach(app.handle().clone());
            app.manage(sidecar);
            quit_on_stdin(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("the spike app is built");
    app.run(|app, event| {
        if let RunEvent::Exit = event {
            let sidecar = app.state::<Sidecar>();
            tauri::async_runtime::block_on(sidecar.stop());
        }
    });
}
