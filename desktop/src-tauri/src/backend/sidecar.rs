//! The sidecar: `reframe-server` in desktop mode as this app's direct child, its ready line,
//! its log, and its stop (the shutdown request, then a kill).

use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::{ExitStatus, Stdio};
use std::sync::{Mutex, mpsc};
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, BufReader, Lines};
use tokio::process::{Child, ChildStdout, Command};
use tokio::sync::oneshot;

use super::owner;

/// The exit code of an `--owner-only` server that another process beat to the queue lock.
pub const EXIT_STORE_BUSY: i32 = 75;
/// Above this size the log is moved to `sidecar.log.1` when a sidecar starts.
pub const LOG_LIMIT: u64 = 1 << 20;

/// The server's `REFRAME_<name>` options that would change how the sidecar runs; the app sets
/// them on the command line, so a value in the user's environment must not reach it.
const SERVER_OPTIONS: [&str; 13] = [
    "ALLOWED_HOSTS",
    "AUTH",
    "CORS_ORIGINS",
    "HOST",
    "IDLE_EXIT",
    "MEDIA_ROOTS",
    "MODE",
    "OUTPUT_ROOTS",
    "OWNER_ONLY",
    "PARENT_PID",
    "PORT",
    "STATIC_DIR",
    "TOKEN",
];

type Spawn = (Command, oneshot::Sender<io::Result<Child>>);

/// Forks every sidecar on one thread that lives as long as the app: on Linux the death signal
/// follows the thread that forked, so a sidecar forked by a worker thread that ends would get
/// SIGTERM with it.
pub struct Spawner(Mutex<mpsc::Sender<Spawn>>);

impl Spawner {
    pub fn new(runtime: tokio::runtime::Handle) -> io::Result<Self> {
        let (requests, received) = mpsc::channel::<Spawn>();
        std::thread::Builder::new()
            .name("reframe-sidecar-spawner".to_owned())
            .spawn(move || {
                // The child's pipes are registered with this runtime.
                let _runtime = runtime.enter();
                for (mut command, reply) in received {
                    let _ = reply.send(command.spawn());
                }
            })?;
        Ok(Self(Mutex::new(requests)))
    }

    pub async fn spawn(&self, command: Command) -> io::Result<Child> {
        let (reply, child) = oneshot::channel();
        let gone = || io::Error::other("the sidecar spawner thread ended");
        self.0
            .lock()
            .map_err(|_| gone())?
            .send((command, reply))
            .map_err(|_| gone())?;
        child.await.map_err(|_| gone())?
    }
}

/// A sidecar that printed its ready line.
pub struct Sidecar {
    child: Child,
    pub port: u16,
    pub token: String,
    // Kept open: a closed stdout could end the server at its next write.
    _stdout: Lines<BufReader<ChildStdout>>,
    #[cfg(windows)]
    _job: Option<super::job::Job>,
}

/// Why a sidecar did not get ready.
#[derive(Debug)]
pub enum StartError {
    /// `--owner-only` exited 75: another process owns the queue.
    LostLock,
    Failed(String),
}

/// What [`start`] needs besides the per-start choices.
pub struct Launch<'a> {
    pub command: &'a [OsString],
    pub log: &'a Path,
    pub cors_origin: Option<&'a str>,
    pub ready_timeout: Duration,
}

/// Starts the sidecar and waits for its ready line. `note` goes to the log first.
pub async fn start(
    spawner: &Spawner,
    launch: &Launch<'_>,
    owner_only: bool,
    note: Option<&str>,
) -> Result<Sidecar, StartError> {
    let failed =
        |error: io::Error| StartError::Failed(format!("The server could not be started: {error}"));
    let stderr = open_log(launch.log, note).map_err(failed)?;
    let token = make_token().map_err(failed)?;
    let command = command(launch, &token, owner_only, stderr);
    let mut child = spawner.spawn(command).await.map_err(failed)?;
    #[cfg(windows)]
    let job = contain(&child, launch.log);
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| failed(io::Error::other("no stdout pipe")))?;
    let mut lines = BufReader::new(stdout).lines();
    match tokio::time::timeout(launch.ready_timeout, ready_port(&mut lines)).await {
        Ok(Some(port)) => Ok(Sidecar {
            child,
            port,
            token,
            _stdout: lines,
            #[cfg(windows)]
            _job: job,
        }),
        Ok(None) => {
            let status = child.wait().await;
            if owner_only && matches!(&status, Ok(status) if status.code() == Some(EXIT_STORE_BUSY))
            {
                return Err(StartError::LostLock);
            }
            Err(StartError::Failed(format!(
                "The server ended before it was ready ({})",
                show(&status)
            )))
        }
        Err(_) => {
            // Killed and reaped here: a dropped child goes to tokio's orphan reaper, which left
            // a zombie in the app.
            let _ = child.kill().await;
            Err(StartError::Failed(format!(
                "The server was not ready within {} s",
                launch.ready_timeout.as_secs()
            )))
        }
    }
}

impl Sidecar {
    /// Waits until the process ends.
    pub async fn wait(&mut self) -> String {
        show(&self.child.wait().await)
    }

    /// The shutdown request (running jobs end interrupted, their `.part` files are removed),
    /// then a kill when the process still runs after `timeout`.
    pub async fn stop(mut self, timeout: Duration) {
        let asked = async {
            let _ = owner::http(
                self.port,
                "POST",
                "/api/system/shutdown",
                Some(&self.token),
                timeout,
            )
            .await;
            self.child.wait().await
        };
        if tokio::time::timeout(timeout, asked).await.is_err() {
            let _ = self.child.kill().await;
        }
    }
}

fn command(launch: &Launch<'_>, token: &str, owner_only: bool, stderr: File) -> Command {
    let mut command = Command::new(&launch.command[0]);
    command
        .args(&launch.command[1..])
        .args(["--mode", "desktop", "--port", "0", "--auth", "token"]);
    if owner_only {
        command.arg("--owner-only");
    }
    let parent = std::process::id();
    command.arg("--parent-pid").arg(parent.to_string());
    for name in SERVER_OPTIONS {
        command.env_remove(format!("REFRAME_{name}"));
    }
    // Not on the command line, where every user of the machine could read it.
    command.env("REFRAME_TOKEN", token);
    if let Some(origin) = launch.cors_origin {
        command.env("REFRAME_CORS_ORIGINS", format!("[\"{origin}\"]"));
    }
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(stderr)
        .kill_on_drop(true);
    #[cfg(target_os = "linux")]
    // SAFETY: the closure only makes async-signal-safe calls (prctl, getppid, getpid, kill).
    unsafe {
        command.pre_exec(move || death_signal(parent));
    }
    #[cfg(windows)]
    command.creation_flags(windows::Win32::System::Threading::CREATE_NO_WINDOW.0);
    command
}

/// Runs in the child between fork and exec. SIGTERM lets the server stop as a shutdown request
/// does (its jobs end interrupted, their `.part` files are removed).
#[cfg(target_os = "linux")]
fn death_signal(parent: u32) -> io::Result<()> {
    // SAFETY: prctl, getppid, getpid and kill are async-signal-safe.
    unsafe {
        if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) != 0 {
            return Err(io::Error::last_os_error());
        }
        // The app died before prctl took effect: do what the death signal would have done.
        if libc::getppid() as u32 != parent {
            libc::kill(libc::getpid(), libc::SIGTERM);
        }
    }
    Ok(())
}

/// A failed job leaves the sidecar running: its parent watch still ends it after a crash.
#[cfg(windows)]
fn contain(child: &Child, log: &Path) -> Option<super::job::Job> {
    let process = child.raw_handle()?;
    match super::job::contain(&super::job::System, process) {
        Ok(job) => Some(job),
        Err(error) => {
            let _ = append_log(log, &format!("the server is not in a Job Object: {error}"));
            None
        }
    }
}

/// The log for the sidecar's stderr: moved to `sidecar.log.1` when it is over [`LOG_LIMIT`],
/// else appended to, so the log of the run that failed is still there.
fn open_log(path: &Path, note: Option<&str>) -> io::Result<File> {
    if let Some(folder) = path.parent() {
        fs::create_dir_all(folder)?;
    }
    if fs::metadata(path).is_ok_and(|meta| meta.len() > LOG_LIMIT) {
        let mut old = path.as_os_str().to_owned();
        old.push(".1");
        fs::rename(path, PathBuf::from(old))?;
    }
    let mut file = OpenOptions::new().create(true).append(true).open(path)?;
    if let Some(note) = note {
        writeln!(file, "reframe-desktop: {note}")?;
    }
    Ok(file)
}

/// One line of the app's own in the sidecar's log.
pub fn append_log(path: &Path, line: &str) -> io::Result<()> {
    let mut file = OpenOptions::new().create(true).append(true).open(path)?;
    writeln!(file, "reframe-desktop: {line}")
}

fn make_token() -> io::Result<String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(io::Error::other)?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn show(status: &io::Result<ExitStatus>) -> String {
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

#[cfg(all(test, unix))]
mod tests {
    use std::ffi::OsStr;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;

    use super::*;

    fn temp(name: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "reframe-sidecar-test-{name}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).unwrap();
        path
    }

    fn launch<'a>(command: &'a [OsString], log: &'a Path) -> Launch<'a> {
        Launch {
            command,
            log,
            cors_origin: Some("http://127.0.0.1:5173"),
            ready_timeout: Duration::from_secs(5),
        }
    }

    #[test]
    fn the_token_and_the_server_options_are_kept_off_the_command_line() {
        let folder = temp("command");
        let program = [OsString::from("reframe-server")];
        let log = folder.join("sidecar.log");
        let stderr = File::create(&log).unwrap();
        let command = command(&launch(&program, &log), "secret", true, stderr);
        let std = command.as_std();
        let args: Vec<&OsStr> = std.get_args().collect();
        assert!(!args.contains(&OsStr::new("secret")));
        let envs: Vec<(&OsStr, Option<&OsStr>)> = std.get_envs().collect();
        assert!(envs.contains(&(OsStr::new("REFRAME_TOKEN"), Some(OsStr::new("secret")))));
        assert!(envs.contains(&(
            OsStr::new("REFRAME_CORS_ORIGINS"),
            Some(OsStr::new("[\"http://127.0.0.1:5173\"]"))
        )));
        for name in ["REFRAME_HOST", "REFRAME_IDLE_EXIT", "REFRAME_MEDIA_ROOTS"] {
            assert!(envs.contains(&(OsStr::new(name), None)), "{name}");
        }
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn a_log_over_the_limit_is_moved_aside_and_a_small_one_is_appended_to() {
        let folder = temp("log");
        let log = folder.join("logs").join("sidecar.log");
        drop(open_log(&log, Some("first")).unwrap());
        drop(open_log(&log, Some("second")).unwrap());
        assert_eq!(
            fs::read_to_string(&log).unwrap(),
            "reframe-desktop: first\nreframe-desktop: second\n"
        );
        fs::write(&log, vec![b'x'; LOG_LIMIT as usize + 1]).unwrap();
        drop(open_log(&log, Some("third")).unwrap());
        assert_eq!(
            fs::read_to_string(&log).unwrap(),
            "reframe-desktop: third\n"
        );
        let old = folder.join("logs").join("sidecar.log.1");
        assert_eq!(fs::metadata(old).unwrap().len(), LOG_LIMIT + 1);
        fs::remove_dir_all(&folder).unwrap();
    }

    /// Alive and not a zombie, by `/proc/<pid>/stat`.
    fn running(pid: u32) -> bool {
        let stat = fs::read_to_string(format!("/proc/{pid}/stat")).unwrap_or_default();
        stat.rsplit(')')
            .next()
            .is_some_and(|rest| rest.trim_start().starts_with(['S', 'R']))
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn a_sidecar_started_for_a_thread_that_ends_keeps_running() {
        let folder = temp("spawner");
        let script = folder.join("sidecar.sh");
        fs::write(
            &script,
            "#!/bin/sh\nprintf '{\"event\":\"ready\",\"port\":9}\\n'\nexec sleep 30\n",
        )
        .unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();
        let runtime = tokio::runtime::Handle::current();
        let spawner = Arc::new(Spawner::new(runtime.clone()).unwrap());
        let log = folder.join("sidecar.log");
        let asking = {
            let (spawner, log) = (spawner.clone(), log.clone());
            std::thread::spawn(move || {
                let program = [script.into_os_string()];
                runtime.block_on(start(&spawner, &launch(&program, &log), true, None))
            })
        };
        let Ok(sidecar) = asking.join().unwrap() else {
            panic!("not started");
        };
        let pid = sidecar.child.id().unwrap();
        tokio::time::sleep(Duration::from_millis(300)).await;
        assert!(
            running(pid),
            "the sidecar ended with the thread that asked for it"
        );
        drop(sidecar);
        fs::remove_dir_all(&folder).unwrap();
    }

    #[cfg(target_os = "linux")]
    #[tokio::test(flavor = "multi_thread")]
    async fn a_sidecar_gets_sigterm_when_the_thread_that_forked_it_ends() {
        let folder = temp("death");
        let script = folder.join("sidecar.sh");
        let term = folder.join("term");
        fs::write(
            &script,
            format!(
                "#!/bin/sh\ntrap 'echo term > \"{}\"; exit 0' TERM\n\
                 printf '{{\"event\":\"ready\",\"port\":9}}\\n'\nwhile :; do sleep 0.02; done\n",
                term.display()
            ),
        )
        .unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();
        let spawner = Spawner::new(tokio::runtime::Handle::current()).unwrap();
        let log = folder.join("sidecar.log");
        let program = [script.into_os_string()];
        let Ok(sidecar) = start(&spawner, &launch(&program, &log), true, None).await else {
            panic!("not started");
        };
        // The spawner's thread ends with its channel, as it does when the app ends.
        drop(spawner);
        for _ in 0..100 {
            if term.exists() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        assert!(
            term.exists(),
            "the sidecar outlived the thread that forked it"
        );
        drop(sidecar);
        fs::remove_dir_all(&folder).unwrap();
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn a_child_whose_parent_ended_before_the_death_signal_was_set_ends_at_once() {
        use std::os::unix::process::{CommandExt, ExitStatusExt};
        let mut child = std::process::Command::new("true");
        // SAFETY: as in `command`; the parent pid is one this child does not have.
        unsafe {
            child.pre_exec(|| death_signal(u32::MAX));
        }
        let status = child.status().unwrap();
        assert_eq!(status.signal(), Some(libc::SIGTERM), "{status}");
    }

    #[test]
    fn the_server_options_kept_from_the_sidecar_are_the_cores() {
        let owner = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../packages/reframe/src/reframe/remote/owner.py"
        );
        let source = fs::read_to_string(owner).unwrap();
        let start = source.find("SERVER_OPTIONS = frozenset(").unwrap();
        let end = start + source[start..].find(')').unwrap();
        let mut cores: Vec<&str> = source[start..end].split('"').skip(1).step_by(2).collect();
        cores.sort_unstable();
        let mut ours = SERVER_OPTIONS.to_vec();
        ours.sort_unstable();
        assert_eq!(ours, cores);
    }
}
