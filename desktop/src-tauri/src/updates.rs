//! The update check: once per start, the signed release manifest (`latest.json`); the user
//! decides whether to install.

use std::time::Duration;

use tauri::AppHandle;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

/// Replaces the endpoint of `tauri.conf.json`, for a test release on another server.
const URL_ENV: &str = "REFRAME_UPDATE_URL";
/// Turns the check off (smoke tests, machines without network).
const OFF_ENV: &str = "REFRAME_NO_UPDATE_CHECK";
/// The check waits so that it does not slow down the start.
const DELAY: Duration = Duration::from_secs(10);

type Error = Box<dyn std::error::Error + Send + Sync>;

pub fn spawn_check(app: &AppHandle) {
    if turned_off(std::env::var(OFF_ENV).ok().as_deref()) {
        return;
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(DELAY).await;
        if let Err(error) = check(&app, std::env::var(URL_ENV).ok()).await {
            eprintln!("reframe-desktop: the update check failed: {error}");
        }
    });
}

fn turned_off(value: Option<&str>) -> bool {
    value.is_some_and(|v| !matches!(v.trim(), "" | "0"))
}

async fn check(app: &AppHandle, url: Option<String>) -> Result<(), Error> {
    let mut builder = app.updater_builder();
    if let Some(url) = url.filter(|u| !u.trim().is_empty()) {
        builder = builder.endpoints(vec![url.trim().parse()?])?;
    }
    let Some(update) = builder.build()?.check().await? else {
        return Ok(());
    };
    let text = format!(
        "Reframe {} is available (this is {}). Install it and restart now? Running encodes stop.",
        update.version, update.current_version
    );
    let (answer, answered) = tokio::sync::oneshot::channel();
    app.dialog()
        .message(text)
        .title("Update available")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Install and restart".into(),
            "Later".into(),
        ))
        .show(move |yes| {
            let _ = answer.send(yes);
        });
    if !answered.await.unwrap_or(false) {
        return Ok(());
    }
    update.download_and_install(|_, _| {}, || {}).await?;
    app.restart()
}

#[cfg(test)]
mod tests {
    use super::turned_off;

    #[test]
    fn only_an_empty_or_zero_value_keeps_the_check_on() {
        assert!(!turned_off(None));
        assert!(!turned_off(Some("")));
        assert!(!turned_off(Some(" 0 ")));
        assert!(turned_off(Some("1")));
        assert!(turned_off(Some("yes")));
    }
}
