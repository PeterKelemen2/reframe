//! The server the app talks to: the queue's owner when one is running, else the sidecar this
//! app starts and restarts. One supervisor task at a time runs the start order and watches
//! the result; every change of [`BackendState`] reaches the windows as a `backend-state` event.

#[cfg(any(windows, test))]
mod job;
mod owner;
mod sidecar;
// The fake sidecars are shell scripts.
#[cfg(all(test, unix))]
mod tests;

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, State};
use tokio::sync::watch;

use owner::Found;
use sidecar::{Launch, Spawner, StartError};

/// The `backend-state` event, sent to every window on each change.
pub const STATE_EVENT: &str = "backend-state";

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendInfo {
    pub base_url: String,
    pub token: String,
    /// `GET /api/health`'s `instance` of the server.
    pub instance: String,
    /// The app started this server (its sidecar), so quitting stops it.
    pub owned: bool,
    /// Set when this server runs on a private queue: its jobs are not saved, and other front
    /// ends do not see them.
    pub private_queue: Option<PrivateQueue>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PrivateQueue {
    pub reason: PrivateReason,
    /// English, for the log and the page: who owns the queue.
    pub detail: String,
}

/// Why the queue's owner cannot be used.
#[derive(Clone, Copy, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum PrivateReason {
    /// It speaks another `api_version`.
    OtherVersion,
    /// It is a web-mode server, whose CORS refuses the app's page.
    WebServer,
    /// The queue lock is held, and no server answers for it.
    LockHeld,
    /// Its token cannot be sent in an HTTP header.
    UnusableToken,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendError {
    pub message: String,
    /// The sidecar log, when there is one to read.
    pub log: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "lowercase")]
pub enum BackendState {
    Starting,
    Ready { info: BackendInfo },
    Failed { error: BackendError },
}

/// How long each step may take. The tests shorten them.
#[derive(Clone, Debug)]
struct Timing {
    ready: Duration,
    stop: Duration,
    /// How long to look for the owner that won the queue lock before the sidecar runs on a
    /// private queue (the CLI waits as long).
    held_wait: Duration,
    poll: Duration,
    owner_poll: Duration,
    health: Duration,
    restart_window: Duration,
}

impl Default for Timing {
    fn default() -> Self {
        Self {
            ready: Duration::from_secs(20),
            stop: Duration::from_secs(5),
            held_wait: Duration::from_secs(5),
            poll: Duration::from_millis(50),
            owner_poll: Duration::from_secs(1),
            health: Duration::from_secs(2),
            restart_window: Duration::from_secs(60),
        }
    }
}

/// Restarts of a crashed sidecar allowed within `Timing::restart_window`.
const RESTARTS: usize = 3;

#[derive(Debug)]
struct Config {
    /// The sidecar's program and its first arguments.
    command: Vec<OsString>,
    endpoint_file: PathBuf,
    log: PathBuf,
    cors_origin: Option<String>,
    timing: Timing,
}

impl Config {
    fn from_context(context: &tauri::Context) -> Result<Self, String> {
        let env = |name: &str| std::env::var_os(name);
        let data_dir = owner::data_dir(env).ok_or("The app's data folder cannot be found")?;
        #[cfg(dev)]
        let cors_origin = context
            .config()
            .build
            .dev_url
            .as_ref()
            .map(|url| url.origin().ascii_serialization());
        #[cfg(not(dev))]
        let cors_origin = None;
        Ok(Self {
            command: sidecar_command(context)?,
            endpoint_file: owner::endpoint_file(&data_dir, env),
            log: data_dir.join("logs").join("sidecar.log"),
            cors_origin,
            timing: Timing::default(),
        })
    }
}

/// `<resources>/sidecar/reframe-server`; in debug builds `REFRAME_DESKTOP_SIDECAR` (a command
/// line split at spaces) runs the server from source instead.
fn sidecar_command(context: &tauri::Context) -> Result<Vec<OsString>, String> {
    #[cfg(debug_assertions)]
    if let Ok(line) = std::env::var("REFRAME_DESKTOP_SIDECAR")
        && !line.trim().is_empty()
    {
        return Ok(line.split_whitespace().map(OsString::from).collect());
    }
    let resources =
        tauri::utils::platform::resource_dir(context.package_info(), &tauri::Env::default())
            .map_err(|error| format!("The app's resources cannot be found: {error}"))?;
    let name = if cfg!(windows) {
        "reframe-server.exe"
    } else {
        "reframe-server"
    };
    Ok(vec![resources.join("sidecar").join(name).into()])
}

type Listener = Box<dyn Fn(&BackendState) + Send + Sync>;

struct Shared {
    config: Result<Config, String>,
    spawner: Result<Spawner, String>,
    runtime: tokio::runtime::Handle,
    state: watch::Sender<BackendState>,
    listener: OnceLock<Listener>,
    /// Set once by `stop`: no supervisor runs after it.
    stopping: watch::Sender<bool>,
    /// A supervisor task is running.
    running: watch::Sender<bool>,
}

/// Tauri managed state.
pub struct Backend(Arc<Shared>);

impl Backend {
    /// Finds the owner or starts the sidecar, on the app's async runtime. Called on the main
    /// thread before the builder.
    pub fn start(context: &tauri::Context) -> Self {
        let runtime = tauri::async_runtime::handle().inner().clone();
        let backend = Self::with_config(Config::from_context(context), runtime);
        backend.run();
        backend
    }

    fn with_config(config: Result<Config, String>, runtime: tokio::runtime::Handle) -> Self {
        let spawner = Spawner::new(runtime.clone())
            .map_err(|error| format!("The server could not be started: {error}"));
        Self(Arc::new(Shared {
            config,
            spawner,
            runtime,
            state: watch::Sender::new(BackendState::Starting),
            listener: OnceLock::new(),
            stopping: watch::Sender::new(false),
            running: watch::Sender::new(false),
        }))
    }

    /// From now on state changes reach the windows as `backend-state` events.
    pub fn attach(&self, app: AppHandle) {
        self.listen(Box::new(move |state| {
            let _ = app.emit(STATE_EVENT, state);
        }));
    }

    fn listen(&self, listener: Listener) {
        if self.0.listener.set(listener).is_ok()
            && let Some(listener) = self.0.listener.get()
        {
            listener(&self.state());
        }
    }

    pub fn state(&self) -> BackendState {
        self.0.state.borrow().clone()
    }

    /// Waits while the backend is starting.
    pub async fn info(&self) -> Result<BackendInfo, BackendError> {
        let mut state = self.0.state.subscribe();
        let state = state
            .wait_for(|state| !matches!(state, BackendState::Starting))
            .await
            .map(|state| state.clone());
        match state {
            Ok(BackendState::Ready { info }) => Ok(info),
            Ok(BackendState::Failed { error }) => Err(error),
            _ => Err(BackendError {
                message: "The server is not running".to_owned(),
                log: None,
            }),
        }
    }

    /// Runs the start order again after a failure; does nothing while it runs.
    pub fn retry(&self) {
        self.run();
    }

    fn run(&self) {
        let shared = &self.0;
        if *shared.stopping.borrow() || shared.running.send_replace(true) {
            return;
        }
        let mut task = Supervisor {
            shared: Arc::clone(shared),
            ended: false,
        };
        shared.runtime.spawn(async move {
            supervise(&task.shared).await;
            task.end();
        });
    }

    /// Sends a request without a body to the current backend; returns the status code.
    pub async fn request(&self, method: &str, path: &str) -> Result<u16, String> {
        self.send(method, path).await.map(|(status, _)| status)
    }

    /// [`Backend::request`] with the answer's body.
    pub async fn send(&self, method: &str, path: &str) -> Result<(u16, Vec<u8>), String> {
        let BackendState::Ready { info } = self.state() else {
            return Err("The server is not ready".to_owned());
        };
        let port = info
            .base_url
            .rsplit(':')
            .next()
            .and_then(|port| port.parse().ok())
            .ok_or("The server's address has no port")?;
        let timeout = Duration::from_secs(2);
        owner::http(port, method, path, Some(&info.token), timeout)
            .await
            .map_err(|error| error.to_string())
    }

    /// Stops a sidecar this app started (the shutdown request, then a kill after 5 s); leaves
    /// any other owner running. Returns when it is gone; at once after the first call.
    pub async fn stop(&self) {
        self.0.stopping.send_replace(true);
        let mut running = self.0.running.subscribe();
        let _ = running.wait_for(|running| !running).await;
    }
}

/// Marks the supervisor task gone, also when it panicked: else `stop` would wait for ever,
/// `retry` would do nothing, and the page would keep a stale state.
struct Supervisor {
    shared: Arc<Shared>,
    ended: bool,
}

impl Supervisor {
    fn end(&mut self) {
        self.ended = true;
    }
}

impl Drop for Supervisor {
    fn drop(&mut self) {
        if !self.ended {
            let log = self.shared.config.as_ref().ok().map(|config| &config.log);
            self.shared.fail(
                "The app stopped watching the server after an error".to_owned(),
                log,
            );
        }
        self.shared.running.send_replace(false);
    }
}

impl Shared {
    fn set(&self, state: BackendState) {
        self.state.send_replace(state.clone());
        if let Some(listener) = self.listener.get() {
            listener(&state);
        }
    }

    fn fail(&self, message: String, log: Option<&PathBuf>) {
        self.set(BackendState::Failed {
            error: BackendError {
                message,
                log: log.map(|log| log.display().to_string()),
            },
        });
    }
}

/// The start order, again after each end, until it fails or the app stops.
async fn supervise(shared: &Shared) {
    let (config, spawner) = match (&shared.config, &shared.spawner) {
        (Ok(config), Ok(spawner)) => (config, spawner),
        (Err(error), _) | (_, Err(error)) => return shared.fail(error.clone(), None),
    };
    let timing = &config.timing;
    let launch = Launch {
        command: &config.command,
        log: &config.log,
        cors_origin: config.cors_origin.as_deref(),
        ready_timeout: timing.ready,
    };
    let endpoint_file = config.endpoint_file.as_path();
    let mut stopping = shared.stopping.subscribe();
    let mut crashes: Vec<Instant> = Vec::new();
    // Exits 75 in a row while `server.json` names no live process: after the first, wait for
    // the winner's endpoint; after the second, the lock is held by something this app cannot use.
    let mut lost_lock = 0;
    loop {
        if !matches!(*shared.state.borrow(), BackendState::Starting) {
            shared.set(BackendState::Starting);
        }
        let Some(found) = or_stop(&mut stopping, owner::find(endpoint_file, timing.health)).await
        else {
            return;
        };
        let private = match found {
            Found::Owner(endpoint) => {
                lost_lock = 0;
                shared.set(BackendState::Ready {
                    info: BackendInfo {
                        base_url: format!("http://127.0.0.1:{}", endpoint.port),
                        token: endpoint.token,
                        instance: endpoint.instance.clone(),
                        owned: false,
                        private_queue: None,
                    },
                });
                let watched = watch_owner(endpoint.port, &endpoint.instance, timing);
                if or_stop(&mut stopping, watched).await.is_none() {
                    return;
                }
                continue;
            }
            Found::Unusable(private) => Some(private),
            Found::Nothing if lost_lock > 1 => Some(PrivateQueue {
                reason: PrivateReason::LockHeld,
                detail: "Another Reframe process holds the queue lock, and no server of it \
                         answers (an in-process `reframe` command has none)"
                    .to_owned(),
            }),
            Found::Nothing => None,
        };
        let note = private
            .as_ref()
            .map(|private| format!("{}: this server runs on a private queue", private.detail));
        let started = sidecar::start(spawner, &launch, private.is_none(), note.as_deref());
        let Some(started) = or_stop(&mut stopping, started).await else {
            return;
        };
        let mut sidecar = match started {
            Ok(sidecar) => sidecar,
            Err(StartError::LostLock) => {
                let waited = if owner::names_live_process(endpoint_file).await {
                    // Its server does not answer yet (starting, stopped or busy): keep trying it.
                    or_stop(&mut stopping, wait_while_alive(endpoint_file, timing)).await
                } else {
                    lost_lock += 1;
                    let starting = wait_for_owner(endpoint_file, timing);
                    if lost_lock == 1 {
                        or_stop(&mut stopping, starting).await
                    } else {
                        Some(())
                    }
                };
                if waited.is_none() {
                    return;
                }
                continue;
            }
            Err(StartError::Failed(message)) => return shared.fail(message, Some(&config.log)),
        };
        lost_lock = 0;
        let Some(health) = owner::health(sidecar.port, timing.health).await else {
            sidecar.stop(timing.stop).await;
            return shared.fail(
                "The server did not answer after it started".to_owned(),
                Some(&config.log),
            );
        };
        let instance = health["instance"].as_str().unwrap_or_default().to_owned();
        // The other owner may have ended since: the sidecar then took the lock and wrote
        // `server.json`, and its queue is the shared one.
        let private_queue = match private {
            Some(_) if owner::names_instance(endpoint_file, &instance).await => None,
            private => private,
        };
        shared.set(BackendState::Ready {
            info: BackendInfo {
                base_url: format!("http://127.0.0.1:{}", sidecar.port),
                token: sidecar.token.clone(),
                instance,
                owned: true,
                private_queue,
            },
        });
        tokio::select! {
            status = sidecar.wait() => {
                let _ = sidecar::append_log(&config.log, &format!("the server ended ({status})"));
                let now = Instant::now();
                crashes.retain(|crash| now.duration_since(*crash) < timing.restart_window);
                if crashes.len() >= RESTARTS {
                    return shared.fail(
                        format!(
                            "The server ended {} times within {} s ({status})",
                            RESTARTS + 1,
                            timing.restart_window.as_secs()
                        ),
                        Some(&config.log),
                    );
                }
                crashes.push(now);
            }
            () = stopped(&mut stopping) => {
                return sidecar.stop(timing.stop).await;
            }
        }
    }
}

/// `None` when the app stops first; `future` is then dropped (a starting sidecar is killed).
async fn or_stop<F: Future>(stopping: &mut watch::Receiver<bool>, future: F) -> Option<F::Output> {
    tokio::select! {
        output = future => Some(output),
        () = stopped(stopping) => None,
    }
}

async fn stopped(stopping: &mut watch::Receiver<bool>) {
    let _ = stopping.wait_for(|stopping| *stopping).await;
}

/// Returns when the owner no longer answers with its `instance`.
async fn watch_owner(port: u16, instance: &str, timing: &Timing) {
    while owner::alive(port, instance, timing.health).await {
        tokio::time::sleep(timing.owner_poll).await;
    }
}

/// Returns when `server.json` names a server, or after `held_wait`.
async fn wait_for_owner(endpoint_file: &Path, timing: &Timing) {
    let deadline = Instant::now() + timing.held_wait;
    while Instant::now() < deadline {
        if !matches!(
            owner::find(endpoint_file, timing.health).await,
            Found::Nothing
        ) {
            return;
        }
        tokio::time::sleep(timing.poll).await;
    }
}

/// Returns when `server.json` names a server that answers, or no longer names a live process.
async fn wait_while_alive(endpoint_file: &Path, timing: &Timing) {
    while matches!(
        owner::find(endpoint_file, timing.health).await,
        Found::Nothing
    ) && owner::names_live_process(endpoint_file).await
    {
        tokio::time::sleep(timing.owner_poll).await;
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
