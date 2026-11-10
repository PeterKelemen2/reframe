//! Finding a running owner of the queue: the server that `server.json` names, if it answers
//! `GET /api/health` with the file's `instance` and this app's `api_version`, in desktop mode.
//! The folders follow the core's rules, so the app and a `reframe` CLI read the same file.

use std::ffi::OsString;
use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::Deserialize;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;

use super::{PrivateQueue, PrivateReason};

/// The server API this app speaks (`GET /api/health`'s `api_version`).
pub const API_VERSION: u64 = 1;

const DATA_DIR_ENV: &str = "REFRAME_DATA_DIR";
const ENDPOINT_ENV: &str = "REFRAME_ENDPOINT_FILE";
const ANSWER_LIMIT: u64 = 1 << 16;

/// `<data dir>/server.json`, written by the server that owns the queue.
#[derive(Clone, Debug, Deserialize)]
pub struct Endpoint {
    pub pid: u32,
    pub instance: String,
    pub port: u16,
    pub token: String,
    pub version: String,
}

/// What `server.json` led to.
#[derive(Debug)]
pub enum Found {
    Owner(Endpoint),
    /// An owner runs that this app cannot use.
    Unusable(PrivateQueue),
    /// No file, a stale one, or its server does not answer.
    Nothing,
}

/// The core's data folder: `REFRAME_DATA_DIR` (blank is unset, `~` expanded, made absolute),
/// else the platform folder. `None` when the platform has no home folder.
pub fn data_dir(env: impl Fn(&str) -> Option<OsString>) -> Option<PathBuf> {
    if let Some(value) = set(&env, DATA_DIR_ENV) {
        return std::path::absolute(expand_home(Path::new(&value), &env)?).ok();
    }
    platform_data_dir(&env)
}

/// `REFRAME_ENDPOINT_FILE` (blank is unset, made absolute), else `<data dir>/server.json`.
pub fn endpoint_file(data_dir: &Path, env: impl Fn(&str) -> Option<OsString>) -> PathBuf {
    match set(&env, ENDPOINT_ENV) {
        Some(value) => std::path::absolute(&value).unwrap_or_else(|_| PathBuf::from(value)),
        None => data_dir.join("server.json"),
    }
}

/// The value with blanks around it cut; `None` when it is blank or not set.
fn set(env: &impl Fn(&str) -> Option<OsString>, name: &str) -> Option<String> {
    let value = env(name)?.to_string_lossy().trim().to_owned();
    (!value.is_empty()).then_some(value)
}

fn expand_home(path: &Path, env: &impl Fn(&str) -> Option<OsString>) -> Option<PathBuf> {
    match path.strip_prefix("~") {
        Ok(rest) => Some(home_dir(env)?.join(rest)),
        Err(_) => Some(path.to_owned()),
    }
}

#[cfg(not(windows))]
fn home_dir(env: &impl Fn(&str) -> Option<OsString>) -> Option<PathBuf> {
    env("HOME").map(PathBuf::from)
}

#[cfg(windows)]
fn home_dir(_env: &impl Fn(&str) -> Option<OsString>) -> Option<PathBuf> {
    dirs::home_dir()
}

/// platformdirs' `user_data_path("reframe")`: a non-blank `XDG_DATA_HOME` as it is, else
/// `~/.local/share`.
#[cfg(not(windows))]
fn platform_data_dir(env: &impl Fn(&str) -> Option<OsString>) -> Option<PathBuf> {
    let base = match env("XDG_DATA_HOME") {
        Some(value) if !value.to_string_lossy().trim().is_empty() => PathBuf::from(value),
        _ => PathBuf::from(env("HOME")?).join(".local").join("share"),
    };
    Some(base.join("reframe"))
}

/// platformdirs' `user_data_path("Reframe")`: the local application data folder.
#[cfg(windows)]
fn platform_data_dir(_env: &impl Fn(&str) -> Option<OsString>) -> Option<PathBuf> {
    Some(dirs::data_local_dir()?.join("Reframe"))
}

/// Reads `server.json` and asks its server who it is. Never fails: every problem is data.
pub async fn find(endpoint_file: &Path, timeout: Duration) -> Found {
    let Some(endpoint) = read_endpoint(endpoint_file).await else {
        return Found::Nothing;
    };
    let Some(health) = health(endpoint.port, timeout).await else {
        return Found::Nothing;
    };
    if health["instance"] != endpoint.instance.as_str() {
        return Found::Nothing; // another program on that port, or another run: the file is stale
    }
    let version = health["version"].as_str().unwrap_or(&endpoint.version);
    let unusable = |reason, why: String| {
        Found::Unusable(PrivateQueue {
            reason,
            detail: format!(
                "Reframe {version} (pid {}) owns the queue, and {why}",
                endpoint.pid
            ),
        })
    };
    if health["api_version"] != API_VERSION {
        let why = format!(
            "it speaks API version {}, not {API_VERSION} as this app does",
            health["api_version"]
        );
        return unusable(PrivateReason::OtherVersion, why);
    }
    if !usable_token(&endpoint.token) {
        let why = format!(
            "the token in {} cannot be sent in an HTTP header",
            endpoint_file.display()
        );
        return unusable(PrivateReason::UnusableToken, why);
    }
    // A web-mode server's CORS refuses the app's page.
    let Some(mode) = mode(&endpoint, timeout).await else {
        return Found::Nothing;
    };
    if mode != "desktop" {
        let why = format!("it is a server in {mode} mode, which this app cannot use");
        return unusable(PrivateReason::WebServer, why);
    }
    Found::Owner(endpoint)
}

/// `GET /api/system`'s `mode`; `None` without an answer in time (it waits for a running tool
/// discovery).
async fn mode(endpoint: &Endpoint, timeout: Duration) -> Option<String> {
    let token = Some(endpoint.token.as_str());
    let Ok((200, body)) = http(endpoint.port, "GET", "/api/system", token, timeout).await else {
        return None;
    };
    let system: serde_json::Value = serde_json::from_slice(&body).ok()?;
    system["mode"].as_str().map(str::to_owned)
}

/// `server.json` was written by the server run `instance`.
pub async fn names_instance(endpoint_file: &Path, instance: &str) -> bool {
    read_endpoint(endpoint_file)
        .await
        .is_some_and(|endpoint| endpoint.instance == instance)
}

/// `server.json` names a process that runs, whether or not its server answers.
pub async fn names_live_process(endpoint_file: &Path) -> bool {
    read_endpoint(endpoint_file)
        .await
        .is_some_and(|endpoint| process_alive(endpoint.pid))
}

#[cfg(unix)]
fn process_alive(pid: u32) -> bool {
    // 0 and negative values name process groups.
    let Ok(pid @ 1..) = libc::pid_t::try_from(pid) else {
        return false;
    };
    // SAFETY: signal 0 only checks that the process exists.
    let sent = unsafe { libc::kill(pid, 0) } == 0;
    sent || io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
}

#[cfg(windows)]
fn process_alive(pid: u32) -> bool {
    use windows::Win32::Foundation::{CloseHandle, STILL_ACTIVE};
    use windows::Win32::System::Threading::{
        GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    // SAFETY: the handle is used only after OpenProcess succeeded, and closed once.
    unsafe {
        let Ok(process) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) else {
            return false;
        };
        let mut code = 0u32;
        let read = GetExitCodeProcess(process, &mut code).is_ok();
        let _ = CloseHandle(process);
        read && code == STILL_ACTIVE.0 as u32
    }
}

/// The server on `port` still answers with `instance`.
pub async fn alive(port: u16, instance: &str, timeout: Duration) -> bool {
    health(port, timeout)
        .await
        .is_some_and(|health| health["instance"] == instance)
}

async fn read_endpoint(path: &Path) -> Option<Endpoint> {
    let raw = tokio::fs::read(path).await.ok()?;
    serde_json::from_slice(&raw).ok()
}

/// The answer of `GET /api/health`, when it is 200 and JSON.
pub async fn health(port: u16, timeout: Duration) -> Option<serde_json::Value> {
    match http(port, "GET", "/api/health", None, timeout).await {
        Ok((200, body)) => serde_json::from_slice(&body).ok(),
        _ => None,
    }
}

/// Visible ASCII, with spaces only inside: what a `Bearer` header can carry.
fn usable_token(token: &str) -> bool {
    !token.is_empty()
        && !token.starts_with(' ')
        && !token.ends_with(' ')
        && token
            .bytes()
            .all(|byte| byte == b' ' || byte.is_ascii_graphic())
}

/// One HTTP/1.1 request without a body to `127.0.0.1:port`; returns the status and the body.
pub async fn http(
    port: u16,
    method: &str,
    path: &str,
    token: Option<&str>,
    timeout: Duration,
) -> io::Result<(u16, Vec<u8>)> {
    let exchange = async {
        let mut stream = TcpStream::connect(("127.0.0.1", port)).await?;
        let authorization = token
            .map(|token| format!("Authorization: Bearer {token}\r\n"))
            .unwrap_or_default();
        let request = format!(
            "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{authorization}\
             Content-Length: 0\r\nConnection: close\r\n\r\n"
        );
        stream.write_all(request.as_bytes()).await?;
        let mut answer = Vec::new();
        stream.take(ANSWER_LIMIT).read_to_end(&mut answer).await?;
        parse_answer(&answer)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "not an HTTP answer"))
    };
    tokio::time::timeout(timeout, exchange)
        .await
        .unwrap_or_else(|_| Err(io::Error::new(io::ErrorKind::TimedOut, "no answer")))
}

fn parse_answer(answer: &[u8]) -> Option<(u16, Vec<u8>)> {
    let end = answer.windows(4).position(|window| window == b"\r\n\r\n")?;
    let head = std::str::from_utf8(&answer[..end]).ok()?;
    let status = head.split(' ').nth(1)?.parse().ok()?;
    Some((status, answer[end + 4..].to_vec()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(not(windows))]
    fn env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<OsString> {
        use std::collections::HashMap;
        let pairs: HashMap<String, OsString> = pairs
            .iter()
            .map(|(name, value)| ((*name).to_owned(), OsString::from(value)))
            .collect();
        move |name| pairs.get(name).cloned()
    }

    #[test]
    fn this_api_version_is_the_servers() {
        let api = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../packages/reframe-server/src/reframe_server/api.py"
        );
        let source = std::fs::read_to_string(api).unwrap();
        let line = source
            .lines()
            .find(|line| line.starts_with("API_VERSION = "))
            .unwrap();
        assert_eq!(line, format!("API_VERSION = {API_VERSION}"));
    }

    #[cfg(not(windows))]
    #[test]
    fn the_data_folder_follows_the_cores_rule() {
        let home = [("HOME", "/home/u")];
        assert_eq!(
            data_dir(env(&home)),
            Some(PathBuf::from("/home/u/.local/share/reframe"))
        );
        assert_eq!(
            data_dir(env(&[("HOME", "/home/u"), ("XDG_DATA_HOME", "/x")])),
            Some(PathBuf::from("/x/reframe"))
        );
        assert_eq!(
            data_dir(env(&[("HOME", "/home/u"), ("REFRAME_DATA_DIR", "  ")])),
            Some(PathBuf::from("/home/u/.local/share/reframe"))
        );
        assert_eq!(
            data_dir(env(&[("HOME", "/home/u"), ("REFRAME_DATA_DIR", " ~/d ")])),
            Some(PathBuf::from("/home/u/d"))
        );
        let relative = data_dir(env(&[("REFRAME_DATA_DIR", "rel")])).unwrap();
        assert_eq!(relative, std::env::current_dir().unwrap().join("rel"));
    }

    #[cfg(not(windows))]
    #[test]
    fn a_home_folder_in_the_data_folder_is_expanded_as_the_core_does() {
        let data = |value| data_dir(env(&[("HOME", "/home/u"), ("REFRAME_DATA_DIR", value)]));
        assert_eq!(data("~"), Some(PathBuf::from("/home/u")));
        assert_eq!(data("~/"), Some(PathBuf::from("/home/u")));
        assert_eq!(data("~/d/e"), Some(PathBuf::from("/home/u/d/e")));
        // Another user's home folder is not looked up (the core's expanduser does).
        let cwd = std::env::current_dir().unwrap();
        assert_eq!(data("~other/d"), Some(cwd.join("~other/d")));
        assert_eq!(data("a/~/b"), Some(cwd.join("a/~/b")));
    }

    #[cfg(unix)]
    #[test]
    fn a_process_is_alive_until_it_is_reaped() {
        assert!(process_alive(std::process::id()));
        let mut child = std::process::Command::new("true").spawn().unwrap();
        let pid = child.id();
        child.wait().unwrap();
        assert!(!process_alive(pid));
        // init: another user's process, which this one may not signal.
        assert!(process_alive(1));
        // Process groups, not processes.
        assert!(!process_alive(0));
        assert!(!process_alive(u32::MAX));
    }

    #[cfg(not(windows))]
    #[test]
    fn the_endpoint_file_follows_the_cores_rule() {
        let data = Path::new("/d");
        assert_eq!(endpoint_file(data, env(&[])), data.join("server.json"));
        assert_eq!(
            endpoint_file(data, env(&[("REFRAME_ENDPOINT_FILE", " ")])),
            data.join("server.json")
        );
        assert_eq!(
            endpoint_file(data, env(&[("REFRAME_ENDPOINT_FILE", " /e/s.json ")])),
            PathBuf::from("/e/s.json")
        );
    }

    #[test]
    fn a_token_with_a_line_break_cannot_be_used() {
        assert!(usable_token("abc-DEF_123 x"));
        assert!(!usable_token("abc\r\nX-Evil: 1"));
        assert!(!usable_token(" abc"));
        assert!(!usable_token(""));
    }
}
