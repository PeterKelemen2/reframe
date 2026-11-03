//! The server the app talks to: the queue's owner when one is running, else the sidecar.
//!
//! Stub until D-3 lands: it serves the address in `REFRAME_DESKTOP_STUB_BACKEND`
//! (`<base url> <token>`) and starts nothing.
#![allow(dead_code)] // The stub leaves parts of the contract unused.

use serde::Serialize;
use tauri::{AppHandle, Emitter, State};

/// The `backend-state` event, sent to every window on each change.
pub const STATE_EVENT: &str = "backend-state";

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendInfo {
    pub base_url: String,
    pub token: String,
    /// `GET /api/health`'s `instance` of the server.
    pub instance: String,
    /// The app started this server (its sidecar), so quitting stops it.
    pub owned: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendError {
    pub message: String,
    /// The sidecar log, when there is one to read.
    pub log: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(tag = "state", rename_all = "lowercase")]
pub enum BackendState {
    Starting,
    Ready { info: BackendInfo },
    Failed { error: BackendError },
}

pub struct Backend {
    state: BackendState,
}

impl Backend {
    /// Finds the owner or starts the sidecar. Called on the main thread before the builder.
    pub fn start() -> Self {
        let state = match std::env::var("REFRAME_DESKTOP_STUB_BACKEND") {
            Ok(value) => match value.split_once(' ') {
                Some((base_url, token)) => BackendState::Ready {
                    info: BackendInfo {
                        base_url: base_url.to_owned(),
                        token: token.to_owned(),
                        instance: String::new(),
                        owned: false,
                    },
                },
                None => failed("REFRAME_DESKTOP_STUB_BACKEND is not `<base url> <token>`"),
            },
            Err(_) => failed("The server is not built yet"),
        };
        Self { state }
    }

    /// From now on state changes reach the windows as `backend-state` events.
    pub fn attach(&self, app: AppHandle) {
        let _ = app.emit(STATE_EVENT, &self.state);
    }

    pub fn state(&self) -> BackendState {
        self.state.clone()
    }

    /// Waits while the backend is starting.
    pub async fn info(&self) -> Result<BackendInfo, BackendError> {
        match &self.state {
            BackendState::Ready { info } => Ok(info.clone()),
            BackendState::Failed { error } => Err(error.clone()),
            BackendState::Starting => Err(failed_error("starting")),
        }
    }

    /// Runs the start order again after a failure.
    pub fn retry(&self) {}

    /// Sends a request without a body to the current backend; returns the status code.
    pub async fn request(&self, method: &str, path: &str) -> Result<u16, String> {
        Err(format!("{method} {path}: the server is not built yet"))
    }

    /// Stops a sidecar this app started (the shutdown request, then a kill after 5 s); leaves
    /// any other owner running. Returns when it is gone.
    pub async fn stop(&self) {}
}

fn failed(message: &str) -> BackendState {
    BackendState::Failed {
        error: failed_error(message),
    }
}

fn failed_error(message: &str) -> BackendError {
    BackendError {
        message: message.to_owned(),
        log: None,
    }
}

#[tauri::command]
pub async fn backend_info(backend: State<'_, Backend>) -> Result<BackendInfo, BackendError> {
    backend.info().await
}

#[tauri::command]
pub fn backend_retry(backend: State<'_, Backend>) {
    backend.retry();
}
