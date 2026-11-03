//! The start order and the sidecar's life, with shell scripts as fake sidecars and a tokio
//! listener as the fake server they point to.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio::task::JoinHandle;

use super::*;

/// A folder under the system's temporary folder, removed on drop.
struct Temp(PathBuf);

impl Temp {
    fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let name = format!(
            "reframe-backend-test-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::SeqCst)
        );
        let path = std::env::temp_dir().join(name);
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }

    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }

    fn read(&self, name: &str) -> String {
        fs::read_to_string(self.path(name)).unwrap_or_default()
    }

    fn lines(&self, name: &str) -> Vec<String> {
        self.read(name).lines().map(str::to_owned).collect()
    }

    /// A fake sidecar: `body` after lines that record its arguments, token and pid.
    fn script(&self, body: &str) -> PathBuf {
        let path = self.path("sidecar.sh");
        let dir = self.0.display();
        let script = format!(
            "#!/bin/sh\nD='{dir}'\necho \"$*\" >> \"$D/args\"\n\
             echo \"$REFRAME_TOKEN\" >> \"$D/tokens\"\necho $$ > \"$D/pid\"\n{body}\n"
        );
        fs::write(&path, script).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
        path
    }

    fn endpoint(&self, port: u16, instance: &str, token: &str) {
        self.endpoint_of(DEAD_PID, port, instance, token);
    }

    fn endpoint_of(&self, pid: u32, port: u16, instance: &str, token: &str) {
        let json = endpoint_json_of(pid, port, instance, token);
        fs::write(self.path("server.json"), json).unwrap();
    }

    fn pid(&self) -> u32 {
        self.read("pid").trim().parse().unwrap()
    }
}

impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

/// Above Linux's largest `pid_max`: no process has it.
const DEAD_PID: u32 = 0x7fff_fff0;

fn endpoint_json(port: u16, instance: &str, token: &str) -> String {
    endpoint_json_of(DEAD_PID, port, instance, token)
}

fn endpoint_json_of(pid: u32, port: u16, instance: &str, token: &str) -> String {
    serde_json::json!({
        "pid": pid, "instance": instance, "port": port, "token": token,
        "version": "0.0.test", "api_version": 1, "started_at": "2026-11-03T00:00:00Z",
    })
    .to_string()
}

fn ready(port: u16) -> String {
    format!("printf '{{\"event\":\"ready\",\"port\":{port}}}\\n'")
}

/// Prints the ready line, then runs until the fake server gets the shutdown request.
fn until_shutdown(port: u16) -> String {
    format!(
        "echo 'stderr of the server' >&2\necho 'not the ready line'\n{}\n\
         while [ ! -e \"$D/stop\" ]; do sleep 0.02; done\necho bye > \"$D/bye\"",
        ready(port)
    )
}

/// A server that answers `GET /api/health` and `GET /api/system` and records every request as
/// `METHOD PATH AUTHORIZATION`; the shutdown request creates `stop`. While `silent` it takes
/// connections and answers nothing, as a stopped or busy server does.
struct FakeServer {
    port: u16,
    requests: Arc<Mutex<Vec<String>>>,
    silent: Arc<AtomicBool>,
    task: JoinHandle<()>,
}

impl FakeServer {
    async fn start(instance: &str, api_version: u64, stop: Option<PathBuf>) -> Self {
        Self::start_in(instance, api_version, "desktop", stop).await
    }

    async fn start_in(instance: &str, api_version: u64, mode: &str, stop: Option<PathBuf>) -> Self {
        let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let requests = Arc::new(Mutex::new(Vec::new()));
        let recorded = requests.clone();
        let silent = Arc::new(AtomicBool::new(false));
        let quiet = silent.clone();
        let health = serde_json::json!({
            "version": "0.0.test", "api_version": api_version, "instance": instance, "uptime": 1.0,
        })
        .to_string();
        // No mode: `GET /api/system` is not found.
        let system = (!mode.is_empty())
            .then(|| serde_json::json!({"mode": mode, "auth": "token"}).to_string());
        let task = tokio::spawn(async move {
            let mut held = Vec::new();
            while let Ok((mut stream, _)) = listener.accept().await {
                if quiet.load(Ordering::SeqCst) {
                    held.push(stream);
                    continue;
                }
                let mut head = Vec::new();
                let mut buffer = [0u8; 1024];
                while !head.windows(4).any(|window| window == b"\r\n\r\n") {
                    match stream.read(&mut buffer).await {
                        Ok(0) | Err(_) => break,
                        Ok(read) => head.extend_from_slice(&buffer[..read]),
                    }
                }
                let head = String::from_utf8_lossy(&head).into_owned();
                let line = head.lines().next().unwrap_or_default();
                let mut parts = line.split(' ');
                let (method, path) = (parts.next().unwrap_or(""), parts.next().unwrap_or(""));
                let authorization = head
                    .lines()
                    .find_map(|line| line.strip_prefix("Authorization: "))
                    .unwrap_or("-");
                recorded
                    .lock()
                    .unwrap()
                    .push(format!("{method} {path} {authorization}"));
                let body = match path {
                    "/api/health" => Some(&health),
                    "/api/system" => system.as_ref(),
                    _ => None,
                };
                let answer = if let Some(body) = body {
                    format!(
                        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{body}",
                        body.len()
                    )
                } else if path == "/api/system" {
                    "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n".to_owned()
                } else {
                    if path == "/api/system/shutdown"
                        && let Some(stop) = &stop
                    {
                        fs::write(stop, "").unwrap();
                    }
                    "HTTP/1.1 204 No Content\r\n\r\n".to_owned()
                };
                let _ = stream.write_all(answer.as_bytes()).await;
            }
        });
        Self {
            port,
            requests,
            silent,
            task,
        }
    }

    fn silent(&self, silent: bool) {
        self.silent.store(silent, Ordering::SeqCst);
    }

    fn requests(&self) -> Vec<String> {
        self.requests.lock().unwrap().clone()
    }

    fn shutdowns(&self) -> usize {
        let requests = self.requests();
        requests
            .iter()
            .filter(|request| request.starts_with("POST /api/system/shutdown"))
            .count()
    }
}

fn timing() -> Timing {
    Timing {
        ready: Duration::from_secs(5),
        stop: Duration::from_secs(3),
        held_wait: Duration::from_millis(300),
        poll: Duration::from_millis(20),
        owner_poll: Duration::from_millis(50),
        health: Duration::from_millis(500),
        restart_window: Duration::from_secs(60),
    }
}

struct Run {
    backend: Backend,
    states: Arc<Mutex<Vec<BackendState>>>,
}

impl Run {
    fn start(temp: &Temp, script: PathBuf, timing: Timing) -> Self {
        Self::start_command(temp, vec![script.into()], timing)
    }

    fn start_command(temp: &Temp, command: Vec<OsString>, timing: Timing) -> Self {
        let config = Config {
            command,
            endpoint_file: temp.path("server.json"),
            log: temp.path("logs/sidecar.log"),
            cors_origin: None,
            timing,
        };
        let backend = Backend::with_config(Ok(config), tokio::runtime::Handle::current());
        let states = Arc::new(Mutex::new(Vec::new()));
        let recorded = states.clone();
        backend.listen(Box::new(move |state| {
            recorded.lock().unwrap().push(state.clone());
        }));
        backend.run();
        Self { backend, states }
    }

    fn states(&self) -> Vec<BackendState> {
        self.states.lock().unwrap().clone()
    }

    /// Waits until the backend's state passes `test`; panics after 15 s.
    async fn until(&self, test: impl Fn(&BackendState) -> bool) -> BackendState {
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            let state = self.backend.state();
            if test(&state) {
                return state;
            }
            assert!(Instant::now() < deadline, "still {state:?}");
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }

    async fn ready(&self) -> BackendInfo {
        match self
            .until(|state| !matches!(state, BackendState::Starting))
            .await
        {
            BackendState::Ready { info } => info,
            other => panic!("not ready: {other:?}"),
        }
    }

    async fn failed(&self) -> BackendError {
        match self
            .until(|state| matches!(state, BackendState::Failed { .. }))
            .await
        {
            BackendState::Failed { error } => error,
            _ => unreachable!(),
        }
    }
}

fn reason(info: &BackendInfo) -> Option<PrivateReason> {
    info.private_queue.as_ref().map(|private| private.reason)
}

/// The process is gone (reaped), not only killed.
fn gone(pid: u32) -> bool {
    !Path::new(&format!("/proc/{pid}")).exists()
}

#[tokio::test(flavor = "multi_thread")]
async fn without_an_owner_the_sidecar_starts_and_stops_on_the_shutdown_request() {
    let temp = Temp::new();
    let server = FakeServer::start("run-1", 1, Some(temp.path("stop"))).await;
    let run = Run::start(&temp, temp.script(&until_shutdown(server.port)), timing());
    let info = run.ready().await;
    let token = temp.read("tokens").trim().to_owned();
    assert_eq!(
        info,
        BackendInfo {
            base_url: format!("http://127.0.0.1:{}", server.port),
            token: token.clone(),
            instance: "run-1".to_owned(),
            owned: true,
            private_queue: None,
        }
    );
    assert_eq!(token.len(), 64);
    let args = format!(
        "--mode desktop --port 0 --auth token --owner-only --parent-pid {}",
        std::process::id()
    );
    assert_eq!(temp.lines("args"), [args]);
    assert!(
        temp.read("logs/sidecar.log")
            .contains("stderr of the server")
    );
    assert_eq!(run.states(), [BackendState::Starting, run.backend.state()]);

    let asked = Instant::now();
    run.backend.stop().await;
    assert!(asked.elapsed() < timing().stop, "killed, not stopped");
    assert_eq!(temp.read("bye"), "bye\n");
    assert!(
        server
            .requests()
            .contains(&format!("POST /api/system/shutdown Bearer {token}"))
    );
    run.backend.stop().await; // a second stop returns at once
    assert_eq!(server.shutdowns(), 1);
}

#[tokio::test(flavor = "multi_thread")]
async fn a_sidecar_that_ignores_the_shutdown_request_is_killed_after_the_stop_time() {
    let temp = Temp::new();
    let server = FakeServer::start("run-1", 1, None).await;
    let script = temp.script(&format!("{}\nexec sleep 30", ready(server.port)));
    let timing = Timing {
        stop: Duration::from_millis(400),
        ..timing()
    };
    let run = Run::start(&temp, script, timing);
    run.ready().await;
    let asked = Instant::now();
    run.backend.stop().await;
    let took = asked.elapsed();
    assert!(gone(temp.pid()));
    assert_eq!(server.shutdowns(), 1);
    assert!(
        took >= Duration::from_millis(400),
        "killed at once: {took:?}"
    );
    assert!(took < Duration::from_secs(3), "{took:?}");
}

#[tokio::test(flavor = "multi_thread")]
async fn a_sidecar_without_a_ready_line_fails_after_the_timeout_and_is_killed() {
    let temp = Temp::new();
    let timing = Timing {
        ready: Duration::from_millis(300),
        ..timing()
    };
    let run = Run::start(&temp, temp.script("exec sleep 30"), timing);
    let error = run.failed().await;
    assert!(error.message.contains("not ready within"), "{error:?}");
    assert_eq!(
        error.log,
        Some(temp.path("logs/sidecar.log").display().to_string())
    );
    assert!(gone(temp.pid()));
    assert_eq!(run.backend.info().await, Err(error));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_sidecar_that_ends_before_its_ready_line_fails_and_its_stderr_is_in_the_log() {
    let temp = Temp::new();
    let run = Run::start(&temp, temp.script("echo boom >&2\nexit 3"), timing());
    let error = run.failed().await;
    assert!(
        error.message.contains("ended before it was ready") && error.message.contains('3'),
        "{error:?}"
    );
    assert!(temp.read("logs/sidecar.log").contains("boom"));
    assert_eq!(
        temp.lines("args").len(),
        1,
        "a start failure is not restarted"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_crashed_sidecar_is_restarted_with_a_new_token_three_times_then_fails() {
    let temp = Temp::new();
    let server = FakeServer::start("run-1", 1, None).await;
    let script = temp.script(&format!("{}\nsleep 0.1\nexit 1", ready(server.port)));
    let run = Run::start(&temp, script, timing());
    let error = run.failed().await;
    assert!(
        error.message.contains("ended 4 times within 60 s"),
        "{error:?}"
    );
    let tokens = temp.lines("tokens");
    assert_eq!(tokens.len(), 4);
    assert!(
        tokens
            .iter()
            .all(|token| tokens.iter().filter(|t| *t == token).count() == 1)
    );
    let shapes: Vec<&str> = run
        .states()
        .iter()
        .map(|state| match state {
            BackendState::Starting => "starting",
            BackendState::Ready { .. } => "ready",
            BackendState::Failed { .. } => "failed",
        })
        .collect();
    let mut expected = ["starting", "ready"].repeat(4);
    expected.push("failed");
    assert_eq!(shapes, expected);
    assert_eq!(
        temp.read("logs/sidecar.log")
            .matches("reframe-desktop: the server ended")
            .count(),
        4
    );

    run.backend.retry();
    run.until(|state| !matches!(state, BackendState::Failed { .. }))
        .await;
    run.failed().await;
    assert_eq!(temp.lines("tokens").len(), 8, "retry starts the count over");
}

#[tokio::test(flavor = "multi_thread")]
async fn crashes_further_apart_than_the_restart_window_are_always_restarted() {
    let temp = Temp::new();
    let server = FakeServer::start("run-1", 1, None).await;
    let script = temp.script(&format!("{}\nsleep 0.15\nexit 1", ready(server.port)));
    let timing = Timing {
        restart_window: Duration::from_millis(100),
        ..timing()
    };
    let run = Run::start(&temp, script, timing);
    let deadline = Instant::now() + Duration::from_secs(10);
    while temp.lines("tokens").len() < 6 && Instant::now() < deadline {
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(temp.lines("tokens").len() >= 6);
    assert!(!matches!(run.backend.state(), BackendState::Failed { .. }));
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn info_waits_while_the_sidecar_starts() {
    let temp = Temp::new();
    let server = FakeServer::start("run-1", 1, Some(temp.path("stop"))).await;
    let script = temp.script(&format!("sleep 0.3\n{}", until_shutdown(server.port)));
    let run = Run::start(&temp, script, timing());
    let info = run.backend.info().await.unwrap();
    assert_eq!(info.instance, "run-1");
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_running_owner_is_used_no_sidecar_starts_and_stop_leaves_it_running() {
    let temp = Temp::new();
    let owner = FakeServer::start("cli-owner", 1, None).await;
    temp.endpoint(owner.port, "cli-owner", "cli-token");
    let run = Run::start(&temp, temp.script("exit 9"), timing());
    let info = run.ready().await;
    assert_eq!(
        info,
        BackendInfo {
            base_url: format!("http://127.0.0.1:{}", owner.port),
            token: "cli-token".to_owned(),
            instance: "cli-owner".to_owned(),
            owned: false,
            private_queue: None,
        }
    );
    assert_eq!(
        run.backend.request("POST", "/api/queue/pause").await,
        Ok(204)
    );
    assert!(
        owner
            .requests()
            .contains(&"POST /api/queue/pause Bearer cli-token".to_owned())
    );
    run.backend.stop().await;
    assert_eq!(owner.shutdowns(), 0);
    assert!(temp.read("args").is_empty());
}

#[tokio::test(flavor = "multi_thread")]
async fn when_the_owner_ends_the_app_starts_its_own_sidecar() {
    let temp = Temp::new();
    let owner = FakeServer::start("cli-owner", 1, None).await;
    temp.endpoint(owner.port, "cli-owner", "cli-token");
    let sidecar = FakeServer::start("app-sidecar", 1, Some(temp.path("stop"))).await;
    let run = Run::start(&temp, temp.script(&until_shutdown(sidecar.port)), timing());
    assert!(!run.ready().await.owned);
    owner.task.abort();
    let info = match run
        .until(|state| matches!(state, BackendState::Ready { info } if info.owned))
        .await
    {
        BackendState::Ready { info } => info,
        _ => unreachable!(),
    };
    assert_eq!(info.instance, "app-sidecar");
    assert!(run.states().contains(&BackendState::Starting));
    run.backend.stop().await;
    assert_eq!(sidecar.shutdowns(), 1);
}

#[tokio::test(flavor = "multi_thread")]
async fn an_endpoint_file_of_another_run_is_stale() {
    let temp = Temp::new();
    let server = FakeServer::start("new-run", 1, Some(temp.path("stop"))).await;
    temp.endpoint(server.port, "old-run", "old-token");
    let run = Run::start(&temp, temp.script(&until_shutdown(server.port)), timing());
    let info = run.ready().await;
    assert!(info.owned);
    assert!(temp.read("args").contains("--owner-only"));
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_owner_of_another_api_version_makes_the_sidecar_use_a_private_queue() {
    let temp = Temp::new();
    let other = FakeServer::start("other", 2, None).await;
    temp.endpoint(other.port, "other", "other-token");
    let sidecar = FakeServer::start("app-sidecar", 1, Some(temp.path("stop"))).await;
    let run = Run::start(&temp, temp.script(&until_shutdown(sidecar.port)), timing());
    let info = run.ready().await;
    assert!(info.owned);
    assert!(!temp.read("args").contains("--owner-only"));
    let detail = format!(
        "Reframe 0.0.test (pid {DEAD_PID}) owns the queue, and it speaks API version 2, not 1 as this app does"
    );
    assert_eq!(
        info.private_queue,
        Some(PrivateQueue {
            reason: PrivateReason::OtherVersion,
            detail: detail.clone()
        })
    );
    let log = temp.read("logs/sidecar.log");
    assert!(
        log.contains(&format!("{detail}: this server runs on a private queue")),
        "{log}"
    );
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_owner_whose_token_cannot_be_sent_makes_the_sidecar_use_a_private_queue() {
    let temp = Temp::new();
    let other = FakeServer::start("other", 1, None).await;
    temp.endpoint(other.port, "other", "bad\ntoken");
    let sidecar = FakeServer::start("app-sidecar", 1, Some(temp.path("stop"))).await;
    let run = Run::start(&temp, temp.script(&until_shutdown(sidecar.port)), timing());
    let info = run.ready().await;
    assert!(info.owned);
    assert_eq!(reason(&info), Some(PrivateReason::UnusableToken));
    assert!(!temp.read("args").contains("--owner-only"));
    assert!(
        other
            .requests()
            .iter()
            .all(|request| !request.contains("bad"))
    );
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_sidecar_that_loses_the_lock_uses_the_winner() {
    let temp = Temp::new();
    let winner = FakeServer::start("winner", 1, None).await;
    let json = endpoint_json(winner.port, "winner", "winner-token");
    // The winner publishes its file just after the sidecar lost.
    let body = format!(
        "case \"$*\" in *--owner-only*) (sleep 0.1; echo '{json}' > \"$D/server.json\") & exit 75;; esac\nexit 9"
    );
    let timing = Timing {
        held_wait: Duration::from_secs(5),
        ..timing()
    };
    let run = Run::start(&temp, temp.script(&body), timing);
    let info = run.ready().await;
    assert_eq!(info.instance, "winner");
    assert!(!info.owned);
    assert_eq!(temp.lines("args").len(), 1);
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_lock_held_without_an_endpoint_makes_the_sidecar_use_a_private_queue() {
    let temp = Temp::new();
    let sidecar = FakeServer::start("app-sidecar", 1, Some(temp.path("stop"))).await;
    let body = format!(
        "case \"$*\" in *--owner-only*) exit 75;; esac\n{}",
        until_shutdown(sidecar.port)
    );
    let timing = Timing {
        held_wait: Duration::from_secs(1),
        ..timing()
    };
    let asked = Instant::now();
    let run = Run::start(&temp, temp.script(&body), timing.clone());
    let info = run.ready().await;
    assert!(info.owned);
    assert_eq!(reason(&info), Some(PrivateReason::LockHeld));
    let took = asked.elapsed();
    assert!(took >= timing.held_wait, "did not wait for the winner");
    assert!(took < timing.held_wait * 2, "waited twice: {took:?}");
    let args = temp.lines("args");
    assert_eq!(args.len(), 3, "{args:?}");
    assert!(args[0].contains("--owner-only") && args[1].contains("--owner-only"));
    assert!(!args[2].contains("--owner-only"));
    assert!(
        temp.read("logs/sidecar.log")
            .contains("holds the queue lock")
    );
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn stop_while_the_sidecar_starts_kills_it() {
    let temp = Temp::new();
    let run = Run::start(&temp, temp.script("exec sleep 30"), timing());
    while temp.read("pid").is_empty() {
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let asked = Instant::now();
    run.backend.stop().await;
    let took = asked.elapsed();
    assert!(
        took < Duration::from_secs(1),
        "waited for the ready line: {took:?}"
    );
    let pid = temp.pid();
    let deadline = Instant::now() + Duration::from_secs(2);
    while !gone(pid) && Instant::now() < deadline {
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert!(gone(pid));
    run.backend.retry();
    assert!(!*run.backend.0.running.borrow(), "a start after the stop");
}

#[tokio::test(flavor = "multi_thread")]
async fn the_child_that_missed_the_ready_line_is_reaped_before_the_failure_is_shown() {
    let temp = Temp::new();
    let timing = Timing {
        ready: Duration::from_millis(300),
        ..timing()
    };
    let run = Run::start(&temp, temp.script("exec sleep 30"), timing);
    let pid_file = temp.path("pid");
    // Checked as the state changes: in the app nothing else makes tokio reap an orphan.
    let reaped = Arc::new(Mutex::new(None));
    let seen = reaped.clone();
    let mut states = run.backend.0.state.subscribe();
    let watcher = tokio::spawn(async move {
        let _ = states
            .wait_for(|state| matches!(state, BackendState::Failed { .. }))
            .await;
        let pid: u32 = fs::read_to_string(&pid_file)
            .unwrap()
            .trim()
            .parse()
            .unwrap();
        *seen.lock().unwrap() = Some(gone(pid));
    });
    run.failed().await;
    watcher.await.unwrap();
    assert_eq!(*reaped.lock().unwrap(), Some(true), "a zombie is left");
}

#[tokio::test(flavor = "multi_thread")]
async fn a_web_mode_owner_is_not_used_and_the_sidecar_runs_on_a_private_queue() {
    let temp = Temp::new();
    let web = FakeServer::start_in("web", 1, "web", None).await;
    temp.endpoint(web.port, "web", "web-token");
    let sidecar = FakeServer::start("app-sidecar", 1, Some(temp.path("stop"))).await;
    let run = Run::start(&temp, temp.script(&until_shutdown(sidecar.port)), timing());
    let info = run.ready().await;
    assert!(info.owned, "{info:?}");
    assert_eq!(
        info.private_queue.map(|private| private.detail),
        Some(format!(
            "Reframe 0.0.test (pid {DEAD_PID}) owns the queue, and it is a server in web mode, \
             which this app cannot use"
        ))
    );
    assert!(!temp.read("args").contains("--owner-only"));
    assert!(
        web.requests()
            .contains(&"GET /api/system Bearer web-token".to_owned())
    );
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_owner_that_does_not_say_its_mode_is_not_used() {
    let temp = Temp::new();
    let unknown = FakeServer::start_in("unknown", 1, "", None).await;
    temp.endpoint(unknown.port, "unknown", "unknown-token");
    let sidecar = FakeServer::start("app-sidecar", 1, Some(temp.path("stop"))).await;
    let run = Run::start(&temp, temp.script(&until_shutdown(sidecar.port)), timing());
    let info = run.ready().await;
    assert_eq!((info.instance.as_str(), info.owned), ("app-sidecar", true));
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_private_sidecar_that_got_the_lock_after_all_reports_a_shared_queue() {
    let temp = Temp::new();
    let other = FakeServer::start("other", 2, None).await;
    temp.endpoint(other.port, "other", "other-token");
    let sidecar = FakeServer::start("app-sidecar", 1, Some(temp.path("stop"))).await;
    // The other owner ended while the sidecar started: the sidecar owns the queue.
    let mine = endpoint_json(sidecar.port, "app-sidecar", "t");
    let body = format!(
        "echo '{mine}' > \"$D/server.json\"\n{}",
        until_shutdown(sidecar.port)
    );
    let run = Run::start(&temp, temp.script(&body), timing());
    let info = run.ready().await;
    assert!(info.owned);
    assert!(!temp.read("args").contains("--owner-only"));
    assert_eq!(info.private_queue, None);
    run.backend.stop().await;
}

#[test]
fn backend_info_is_sent_to_the_page_in_camel_case_with_its_private_queue() {
    let mut info = BackendInfo {
        base_url: "http://127.0.0.1:1".to_owned(),
        token: "t".to_owned(),
        instance: "i".to_owned(),
        owned: true,
        private_queue: None,
    };
    let json = serde_json::to_value(&info).unwrap();
    assert_eq!(json["baseUrl"], "http://127.0.0.1:1");
    assert_eq!(json["privateQueue"], serde_json::Value::Null);
    let reasons = [
        (PrivateReason::OtherVersion, "otherVersion"),
        (PrivateReason::WebServer, "webServer"),
        (PrivateReason::LockHeld, "lockHeld"),
        (PrivateReason::UnusableToken, "unusableToken"),
    ];
    for (reason, name) in reasons {
        info.private_queue = Some(PrivateQueue {
            reason,
            detail: "who".to_owned(),
        });
        let state = serde_json::to_value(BackendState::Ready { info: info.clone() }).unwrap();
        assert_eq!(
            state["info"]["privateQueue"],
            serde_json::json!({"reason": name, "detail": "who"})
        );
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn an_owner_that_stops_answering_is_waited_for_and_used_again() {
    let temp = Temp::new();
    let owner = FakeServer::start("cli-owner", 1, None).await;
    temp.endpoint_of(std::process::id(), owner.port, "cli-owner", "cli-token");
    let sidecar = FakeServer::start("app-sidecar", 1, Some(temp.path("stop"))).await;
    // The owner holds the queue lock.
    let body = format!(
        "case \"$*\" in *--owner-only*) exit 75;; esac\n{}",
        until_shutdown(sidecar.port)
    );
    let run = Run::start(&temp, temp.script(&body), timing());
    assert!(!run.ready().await.owned);
    owner.silent(true);
    run.until(|state| matches!(state, BackendState::Starting))
        .await;
    tokio::time::sleep(Duration::from_secs(3)).await;
    assert_eq!(run.backend.state(), BackendState::Starting);
    owner.silent(false);
    let info = run.ready().await;
    assert_eq!((info.instance.as_str(), info.owned), ("cli-owner", false));
    assert!(
        temp.lines("args")
            .iter()
            .all(|args| args.contains("--owner-only")),
        "a sidecar on a private queue ran"
    );
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn an_owner_that_does_not_answer_at_start_is_waited_for_while_it_runs() {
    let temp = Temp::new();
    let owner = FakeServer::start("cli-owner", 1, None).await;
    owner.silent(true);
    temp.endpoint_of(std::process::id(), owner.port, "cli-owner", "cli-token");
    let sidecar = FakeServer::start("app-sidecar", 1, Some(temp.path("stop"))).await;
    let body = format!(
        "case \"$*\" in *--owner-only*) exit 75;; esac\n{}",
        until_shutdown(sidecar.port)
    );
    let run = Run::start(&temp, temp.script(&body), timing());
    tokio::time::sleep(Duration::from_secs(3)).await;
    assert_eq!(run.backend.state(), BackendState::Starting);
    assert_eq!(temp.lines("args").len(), 1, "the lock was tried once");
    owner.silent(false);
    let info = run.ready().await;
    assert_eq!((info.instance.as_str(), info.owned), ("cli-owner", false));
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_waited_for_owner_that_ends_is_replaced_by_the_sidecar() {
    let temp = Temp::new();
    let owner = FakeServer::start("cli-owner", 1, None).await;
    owner.silent(true);
    let mut process = std::process::Command::new("sleep")
        .arg("30")
        .spawn()
        .unwrap();
    temp.endpoint_of(process.id(), owner.port, "cli-owner", "cli-token");
    fs::write(temp.path("locked"), "").unwrap();
    let sidecar = FakeServer::start("app-sidecar", 1, Some(temp.path("stop"))).await;
    let body = format!(
        "case \"$*\" in *--owner-only*) [ -e \"$D/locked\" ] && exit 75;; esac\n{}",
        until_shutdown(sidecar.port)
    );
    let run = Run::start(&temp, temp.script(&body), timing());
    while temp.lines("args").is_empty() {
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    tokio::time::sleep(Duration::from_millis(500)).await;
    assert_eq!(run.backend.state(), BackendState::Starting);
    // The owner ends, and its lock is free.
    fs::remove_file(temp.path("locked")).unwrap();
    process.kill().unwrap();
    process.wait().unwrap();
    let info = run.ready().await;
    assert_eq!((info.instance.as_str(), info.owned), ("app-sidecar", true));
    assert_eq!(info.private_queue, None);
    run.backend.stop().await;
}

#[tokio::test(flavor = "multi_thread")]
async fn a_panic_in_the_supervisor_ends_failed_and_the_app_can_still_quit() {
    let temp = Temp::new();
    // No program: indexing the empty command panics in the supervisor task.
    let run = Run::start_command(&temp, Vec::new(), timing());
    let error = run.failed().await;
    assert_eq!(
        error.log,
        Some(temp.path("logs/sidecar.log").display().to_string())
    );
    run.backend.retry();
    let failures = || {
        run.states()
            .iter()
            .filter(|state| matches!(state, BackendState::Failed { .. }))
            .count()
    };
    let deadline = Instant::now() + Duration::from_secs(5);
    while failures() < 2 && Instant::now() < deadline {
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    assert_eq!(failures(), 2, "retry did not run the order again");
    tokio::time::timeout(Duration::from_secs(2), run.backend.stop())
        .await
        .expect("stop waits for a supervisor that is gone");
}
