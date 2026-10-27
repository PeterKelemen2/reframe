//! The sidecar: `reframe-server` in desktop mode, started with the shell and stopped with it.

use std::fs::{self, DirBuilder, File};
use std::io::{self, Write};
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::json;
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader, Lines};
use tokio::net::TcpStream;
use tokio::process::{Child, ChildStdout, Command};
use tokio::sync::{oneshot, watch};

pub const READY_TIMEOUT: Duration = Duration::from_secs(20);
pub const STOP_TIMEOUT: Duration = Duration::from_secs(5);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(2);

/// The frozen onedir next to this crate; `REFRAME_SPIKE_SIDECAR` replaces it with a command
/// line split at spaces (for example `uv run --project <repository> reframe-server`).
const FROZEN: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../dist/reframe-server/reframe-server"
);

#[derive(Clone, Debug)]
pub enum Backend {
    Starting,
    Ready { base_url: String, token: String },
    Failed(String),
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendInfo {
    pub base_url: String,
    pub token: String,
}

type StopReply = oneshot::Sender<()>;

pub struct Sidecar {
    state: watch::Receiver<Backend>,
    stop: Mutex<Option<oneshot::Sender<StopReply>>>,
    app: Arc<OnceLock<AppHandle>>,
}

impl Sidecar {
    fn failed(message: String) -> Self {
        let (_, state) = watch::channel(Backend::Failed(message));
        Self {
            state,
            stop: Mutex::new(None),
            app: Arc::default(),
        }
    }

    /// The app that hears of the sidecar's end; it does not exist yet when the sidecar starts.
    pub fn attach(&self, app: AppHandle) {
        let _ = self.app.set(app);
    }

    /// Waits until the sidecar is ready or has failed.
    pub async fn info(&self) -> Result<BackendInfo, String> {
        let mut state = self.state.clone();
        let backend = state
            .wait_for(|backend| !matches!(backend, Backend::Starting))
            .await
            .map_err(|error| error.to_string())?
            .clone();
        match backend {
            Backend::Ready { base_url, token } => Ok(BackendInfo { base_url, token }),
            Backend::Failed(message) => Err(message),
            Backend::Starting => unreachable!("wait_for returned a starting backend"),
        }
    }

    /// Asks the server to shut down, waits up to `STOP_TIMEOUT`, then kills it. Returns when
    /// the process is gone (at once when it already was).
    pub async fn stop(&self) {
        let Some(stop) = self.stop.lock().expect("stop lock").take() else {
            return;
        };
        let (reply, done) = oneshot::channel();
        if stop.send(reply).is_ok() {
            let _ = tokio::time::timeout(STOP_TIMEOUT + REQUEST_TIMEOUT * 2, done).await;
        }
    }
}

/// Prints one JSON line on stdout for the measurement scripts.
pub fn report(event: &str, started: Instant, extra: serde_json::Value) {
    let mut line = json!({ "event": event, "ms": started.elapsed().as_secs_f64() * 1000.0 });
    if let (Some(line), Some(extra)) = (line.as_object_mut(), extra.as_object()) {
        line.extend(extra.clone());
    }
    print_line(&line.to_string());
}

/// Writes one line on stdout. A closed stdout loses the line: Rust ignores SIGPIPE, so
/// `println!` would panic there instead.
pub fn print_line(line: &str) {
    let mut stdout = io::stdout().lock();
    let _ = writeln!(stdout, "{line}").and_then(|()| stdout.flush());
}

/// The folder of this run: the sidecar's config, data and cache, and the web view's data.
/// `REFRAME_SPIKE_HOME`, or a new private folder in the temporary directory.
pub fn make_home() -> io::Result<PathBuf> {
    let home = match std::env::var_os("REFRAME_SPIKE_HOME") {
        Some(home) => PathBuf::from(home),
        None => private_folder(&std::env::temp_dir())?,
    };
    for name in ["config", "data", "cache"] {
        fs::create_dir_all(home.join(name))?;
    }
    Ok(home)
}

/// A new folder with a random name and mode 0700. `create` fails when the name exists, so a
/// folder that someone else made first is never used.
fn private_folder(parent: &Path) -> io::Result<PathBuf> {
    loop {
        let folder = parent.join(format!("reframe-spike-{}", &make_token()?[..16]));
        match DirBuilder::new().mode(0o700).create(&folder) {
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            created => return created.map(|()| folder),
        }
    }
}

/// Starts the sidecar in `home` (the error of [`make_home`] fails it). Call it on the main
/// thread: on Linux the death signal follows the thread that forks, and the main thread lives
/// as long as the shell.
pub fn spawn(started: Instant, home: &Result<PathBuf, String>) -> Sidecar {
    let sidecar = home
        .clone()
        .and_then(|home| start(started, &home).map_err(|error| error.to_string()));
    sidecar.unwrap_or_else(|error| {
        Sidecar::failed(format!("The server could not be started: {error}"))
    })
}

fn start(started: Instant, home: &Path) -> io::Result<Sidecar> {
    let log = home.join("data").join("sidecar.log");
    let token = make_token()?;
    let mut argv: Vec<String> = match std::env::var("REFRAME_SPIKE_SIDECAR") {
        Ok(line) => line.split_whitespace().map(str::to_owned).collect(),
        Err(_) => vec![FROZEN.to_owned()],
    };
    let parent = std::process::id();
    argv.extend(["--mode", "desktop", "--port", "0", "--auth", "token"].map(str::to_owned));
    if std::env::var_os("REFRAME_SPIKE_NO_PARENT_PID").is_none() {
        argv.extend(["--parent-pid".to_owned(), parent.to_string()]);
    }
    let mut command = Command::new(&argv[0]);
    command
        .args(&argv[1..])
        .env("REFRAME_TOKEN", &token)
        .env("REFRAME_CONFIG_DIR", home.join("config"))
        .env("REFRAME_DATA_DIR", home.join("data"))
        .env("REFRAME_CACHE_DIR", home.join("cache"))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(File::create(&log)?);
    if std::env::var_os("REFRAME_SPIKE_NO_DEATH_SIGNAL").is_none() {
        // SAFETY: the closure only makes async-signal-safe calls (prctl, getppid, kill).
        unsafe {
            command.pre_exec(move || death_signal(parent));
        }
    }
    // The pipes are registered with the runtime; the fork itself happens on this thread.
    let _runtime = tauri::async_runtime::handle().inner().enter();
    let mut child = command.spawn()?;
    report(
        "sidecar_spawned",
        started,
        json!({
            "pid": child.id(),
            "thread": unsafe { libc::gettid() },
            "main_thread": parent,
            "argv": argv,
            "log": log,
        }),
    );
    let stdout = child.stdout.take().expect("stdout is piped");
    let (state_tx, state) = watch::channel(Backend::Starting);
    let (stop_tx, stop) = oneshot::channel();
    let app = Arc::new(OnceLock::new());
    let supervisor = Supervisor {
        app: app.clone(),
        started,
        token,
        log,
        state: state_tx,
    };
    tauri::async_runtime::spawn(supervisor.run(child, stdout, stop));
    Ok(Sidecar {
        state,
        stop: Mutex::new(Some(stop_tx)),
        app,
    })
}

/// Runs in the child between fork and exec. SIGTERM lets the server stop the way a shutdown
/// request does (its jobs end interrupted, their `.part` files are removed).
fn death_signal(parent: u32) -> io::Result<()> {
    // SAFETY: prctl, getppid and kill are async-signal-safe.
    unsafe {
        if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) != 0 {
            return Err(io::Error::last_os_error());
        }
        // The shell died before prctl took effect: do what the death signal would have done.
        if libc::getppid() as u32 != parent {
            libc::kill(libc::getpid(), libc::SIGTERM);
        }
    }
    Ok(())
}

fn make_token() -> io::Result<String> {
    let mut bytes = [0u8; 32];
    // SAFETY: the buffer is valid for its length.
    let filled = unsafe { libc::getrandom(bytes.as_mut_ptr().cast(), bytes.len(), 0) };
    if filled != bytes.len() as isize {
        return Err(io::Error::last_os_error());
    }
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

struct Supervisor {
    app: Arc<OnceLock<AppHandle>>,
    started: Instant,
    token: String,
    log: PathBuf,
    state: watch::Sender<Backend>,
}

impl Supervisor {
    async fn run(
        self,
        mut child: Child,
        stdout: ChildStdout,
        mut stop: oneshot::Receiver<StopReply>,
    ) {
        let mut lines = BufReader::new(stdout).lines();
        let ready = tokio::select! {
            ready = tokio::time::timeout(READY_TIMEOUT, ready_port(&mut lines)) => ready,
            reply = &mut stop => {
                let _ = child.kill().await;
                if let Ok(reply) = reply {
                    let _ = reply.send(());
                }
                return;
            }
        };
        let port = match ready {
            Ok(Some(port)) => port,
            Ok(None) => {
                let status = child.wait().await;
                return self.fail(format!(
                    "The server ended before it was ready ({})",
                    show(status)
                ));
            }
            Err(_) => {
                let _ = child.kill().await;
                return self.fail(format!(
                    "The server was not ready within {} s",
                    READY_TIMEOUT.as_secs()
                ));
            }
        };
        let mut ready = json!({ "port": port });
        // The cleanup scripts drive an encode through the sidecar's API.
        if std::env::var_os("REFRAME_SPIKE_REPORT_TOKEN").is_some() {
            ready["token"] = json!(self.token);
        }
        report("sidecar_ready", self.started, ready);
        let base_url = format!("http://127.0.0.1:{port}");
        let token = self.token.clone();
        self.state.send_replace(Backend::Ready { base_url, token });
        tokio::select! {
            status = child.wait() => {
                self.fail(format!("The server ended ({})", show(status)));
            }
            reply = stop => {
                let asked = Instant::now();
                let answer = request_shutdown(port, &self.token).await;
                let stopped = tokio::time::timeout(STOP_TIMEOUT, child.wait()).await;
                let killed = stopped.is_err();
                if killed {
                    let _ = child.kill().await;
                }
                report(
                    "sidecar_stopped",
                    self.started,
                    json!({
                        "shutdown_answer": answer.unwrap_or_else(|error| error.to_string()),
                        "after_ms": asked.elapsed().as_secs_f64() * 1000.0,
                        "killed": killed,
                    }),
                );
                if let Ok(reply) = reply {
                    let _ = reply.send(());
                }
            }
        }
        drop(lines);
    }

    fn fail(&self, message: String) {
        let message = format!("{message}. Log: {}", self.log.display());
        report(
            "sidecar_failed",
            self.started,
            json!({ "message": message }),
        );
        self.state.send_replace(Backend::Failed(message.clone()));
        if let Some(app) = self.app.get() {
            let _ = app.emit("sidecar-ended", message);
        }
    }
}

fn show(status: io::Result<std::process::ExitStatus>) -> String {
    match status {
        Ok(status) => status.to_string(),
        Err(error) => error.to_string(),
    }
}

/// The port of the ready line `{"event":"ready","port":N}`; `None` when stdout closes first.
async fn ready_port(lines: &mut Lines<BufReader<ChildStdout>>) -> Option<u16> {
    while let Ok(Some(line)) = lines.next_line().await {
        let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) else {
            continue;
        };
        if value["event"] == "ready"
            && let Some(port) = value["port"]
                .as_u64()
                .and_then(|port| u16::try_from(port).ok())
        {
            return Some(port);
        }
    }
    None
}

/// `POST /api/system/shutdown`; returns the status line.
async fn request_shutdown(port: u16, token: &str) -> io::Result<String> {
    let exchange = async {
        let mut stream = TcpStream::connect(("127.0.0.1", port)).await?;
        let request = format!(
            "POST /api/system/shutdown HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\
             Authorization: Bearer {token}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        );
        stream.write_all(request.as_bytes()).await?;
        let mut answer = Vec::new();
        stream.take(4096).read_to_end(&mut answer).await?;
        let answer = String::from_utf8_lossy(&answer);
        Ok(answer.lines().next().unwrap_or_default().to_owned())
    };
    tokio::time::timeout(REQUEST_TIMEOUT, exchange)
        .await
        .unwrap_or_else(|_| Err(io::Error::new(io::ErrorKind::TimedOut, "no answer")))
}

#[cfg(test)]
mod tests {
    use std::os::unix::fs::PermissionsExt;

    use super::*;

    #[test]
    fn a_new_home_is_private_and_new() {
        let parent = std::env::temp_dir();
        let first = private_folder(&parent).unwrap();
        let second = private_folder(&parent).unwrap();
        let mode = fs::metadata(&first).unwrap().permissions().mode();
        fs::remove_dir(&first).unwrap();
        fs::remove_dir(&second).unwrap();
        assert_eq!(mode & 0o777, 0o700);
        assert_ne!(first, second);
    }
}
