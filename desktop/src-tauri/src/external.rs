//! Opens a preview clip in the user's player: its cached file, since the system gives a URL to
//! the browser. Inside an AppImage the opener plugin's launcher would inherit the image's
//! environment, whose libraries break the user's programs, so there the launcher is started
//! here with the user's environment.

#[cfg(target_os = "linux")]
use std::ffi::OsString;
use std::path::PathBuf;

use crate::backend::Backend;

/// Only the server's preview clips may be opened.
fn is_preview_clip(url: &str) -> bool {
    tauri::Url::parse(url).is_ok_and(|url| {
        url.scheme() == "http"
            && url.host_str() == Some("127.0.0.1")
            && url.path().starts_with("/api/preview/clips/")
    })
}

/// The id of a clip link (`/api/preview/clips/<32 hex digits>`).
fn clip_id(url: &str) -> Option<String> {
    let url = tauri::Url::parse(url).ok()?;
    let id = url.path().strip_prefix("/api/preview/clips/")?;
    let hex = |byte: u8| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte);
    (id.len() == 32 && id.bytes().all(hex)).then(|| id.to_owned())
}

/// The file in the server's answer to `GET /api/preview/clips/<id>/file`.
fn clip_file_of(status: u16, body: &[u8]) -> Option<PathBuf> {
    #[derive(serde::Deserialize)]
    struct ClipFile {
        path: PathBuf,
    }
    if status != 200 {
        return None;
    }
    let file: ClipFile = serde_json::from_slice(body).ok()?;
    file.path.is_absolute().then_some(file.path)
}

/// `None` from a web-mode owner, which does not give the file.
async fn clip_file(backend: &Backend, url: &str) -> Option<PathBuf> {
    let id = clip_id(url)?;
    let path = format!("/api/preview/clips/{id}/file");
    let (status, body) = backend.send("GET", &path).await.ok()?;
    clip_file_of(status, &body).filter(|file| file.is_file())
}

#[tauri::command]
pub async fn open_external(url: String, backend: tauri::State<'_, Backend>) -> Result<(), String> {
    if !is_preview_clip(&url) {
        return Err(format!("Not a preview clip: {url}"));
    }
    let file = clip_file(&backend, &url).await;
    #[cfg(target_os = "linux")]
    if let Some((env, folder)) = appimage_user_side() {
        let commands = match &file {
            Some(file) => open::commands(file),
            None => open::commands(&url),
        };
        return tauri::async_runtime::spawn_blocking(move || launch(commands, &env, &folder))
            .await
            .map_err(|error| error.to_string())?
            .map_err(|error| error.to_string());
    }
    match file {
        Some(file) => tauri_plugin_opener::open_path(file, None::<&str>),
        None => tauri_plugin_opener::open_url(url, None::<&str>),
    }
    .map_err(|error| error.to_string())
}

/// The user's environment and folder; `None` outside an AppImage. The app's own working folder
/// is inside the image, which goes away when the app quits.
#[cfg(target_os = "linux")]
fn appimage_user_side() -> Option<(Vec<(OsString, OsString)>, std::path::PathBuf)> {
    std::env::var_os("APPDIR")?;
    let exe = std::env::current_exe().ok()?;
    let env = crate::appimage::user_environ(std::env::vars_os(), &exe);
    let folder = crate::appimage::launch_folder(|name| std::env::var_os(name))
        .filter(|folder| folder.is_dir())
        .unwrap_or_else(|| "/".into());
    Some((env, folder))
}

/// Tries each launcher in turn, as the opener does: the first that exits 0, or still runs after
/// a moment (`xdg-open` may wait for the program it starts), has opened it.
#[cfg(target_os = "linux")]
fn launch(
    commands: Vec<std::process::Command>,
    env: &[(OsString, OsString)],
    folder: &std::path::Path,
) -> std::io::Result<()> {
    use std::io;
    use std::os::unix::process::CommandExt;
    use std::process::Stdio;
    use std::time::{Duration, Instant};

    let mut failed = None;
    let mut not_started = None;
    for mut command in commands {
        command
            .env_clear()
            .current_dir(folder)
            .envs(env.iter().map(|(name, value)| (name, value)))
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        // SAFETY: setsid is async-signal-safe. The program outlives the app, in its own session.
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() == -1 {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let mut child = match command.spawn() {
            Ok(child) => child,
            Err(error) => {
                not_started = Some(error);
                continue;
            }
        };
        let start = Instant::now();
        let status = loop {
            match child.try_wait()? {
                Some(status) => break Some(status),
                None if start.elapsed() >= Duration::from_millis(250) => break None,
                None => std::thread::sleep(Duration::from_millis(10)),
            }
        };
        match status {
            Some(status) if status.success() => return Ok(()),
            Some(status) => {
                let program = command.get_program().to_string_lossy().into_owned();
                failed.get_or_insert(io::Error::other(format!("{program}: {status}")));
            }
            None => {
                std::thread::spawn(move || child.wait());
                return Ok(());
            }
        }
    }
    Err(failed
        .or(not_started)
        .unwrap_or_else(|| io::Error::other("no launcher")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_a_preview_clip_of_the_local_server_is_opened() {
        assert!(is_preview_clip(
            "http://127.0.0.1:8731/api/preview/clips/c1?sig=x"
        ));
        for url in [
            "https://127.0.0.1:8731/api/preview/clips/c1",
            "http://localhost:8731/api/preview/clips/c1",
            "http://127.0.0.1:1@evil.example/api/preview/clips/c1",
            "http://127.0.0.1:8731/api/preview/clips/../../system",
            "http://127.0.0.1:8731/api/jobs",
            "http://127.0.0.1:8731/other/api/preview/clips/c1",
            "file:///etc/passwd",
            "/api/preview/clips/c1",
        ] {
            assert!(!is_preview_clip(url), "{url}");
        }
    }

    #[test]
    fn the_clip_id_is_the_last_part_of_a_clip_link() {
        let id = "0123456789abcdef0123456789abcdef";
        let link = format!("http://127.0.0.1:8731/api/preview/clips/{id}?exp=1&sig=x");
        assert_eq!(clip_id(&link), Some(id.to_owned()));
        for url in [
            "http://127.0.0.1:8731/api/preview/clips/c1",
            &format!("http://127.0.0.1:8731/api/preview/clips/{id}/frames"),
            "http://127.0.0.1:8731/api/preview/clips/0123456789ABCDEF0123456789ABCDEF",
        ] {
            assert_eq!(clip_id(url), None, "{url}");
        }
    }

    #[cfg(unix)]
    #[test]
    fn the_clip_file_is_the_servers_absolute_path() {
        let ok = br#"{"path": "/home/u/.cache/reframe/clips/c.mkv"}"#;
        assert_eq!(
            clip_file_of(200, ok),
            Some(std::path::PathBuf::from(
                "/home/u/.cache/reframe/clips/c.mkv"
            ))
        );
        let web = br#"{"code": "preview.no_clip_file"}"#;
        assert_eq!(clip_file_of(404, web), None);
        assert_eq!(clip_file_of(200, b"not json"), None);
        assert_eq!(clip_file_of(200, br#"{"path": "clips/c.mkv"}"#), None);
    }

    #[cfg(target_os = "linux")]
    mod launch {
        use super::*;
        use std::path::{Path, PathBuf};
        use std::process::Command;

        struct Temp(PathBuf);

        impl Temp {
            fn new(name: &str) -> Self {
                let dir = std::env::temp_dir()
                    .join(format!("reframe-external-{name}-{}", std::process::id()));
                let _ = std::fs::remove_dir_all(&dir);
                std::fs::create_dir_all(&dir).unwrap();
                Self(dir)
            }
        }

        impl Drop for Temp {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }

        fn sh(script: &str, arg: &PathBuf) -> Command {
            let mut command = Command::new("sh");
            command.arg("-c").arg(script).arg(arg);
            command
        }

        fn env() -> Vec<(OsString, OsString)> {
            [("PATH", "/usr/bin:/bin"), ("LANG", "hu_HU.UTF-8")]
                .into_iter()
                .map(|(name, value)| (name.into(), value.into()))
                .collect()
        }

        fn wait_for(file: &PathBuf) -> String {
            for _ in 0..200 {
                if let Ok(text) = std::fs::read_to_string(file)
                    && text.ends_with("END\n")
                {
                    return text;
                }
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            panic!("{} was not written", file.display());
        }

        #[test]
        fn the_launcher_gets_only_the_given_environment() {
            let temp = Temp::new("env");
            let out = temp.0.join("env");
            launch(
                vec![sh(r#"env > "$0"; echo END >> "$0""#, &out)],
                &env(),
                Path::new("/"),
            )
            .unwrap();
            let shell_own = ["PWD=", "SHLVL=", "_="];
            let mut seen: Vec<String> = wait_for(&out)
                .lines()
                .filter(|line| *line != "END" && !shell_own.iter().any(|own| line.starts_with(own)))
                .map(str::to_owned)
                .collect();
            seen.sort();
            assert_eq!(seen, ["LANG=hu_HU.UTF-8", "PATH=/usr/bin:/bin"]);
        }

        #[test]
        fn the_launcher_starts_in_the_given_folder() {
            let temp = Temp::new("folder");
            let out = temp.0.join("pwd");
            launch(
                vec![sh(r#"pwd -P > "$0"; echo END >> "$0""#, &out)],
                &env(),
                &temp.0,
            )
            .unwrap();
            let folder = std::fs::canonicalize(&temp.0).unwrap();
            assert_eq!(wait_for(&out), format!("{}\nEND\n", folder.display()));
        }

        #[test]
        fn a_failed_or_missing_launcher_hands_over_to_the_next() {
            let temp = Temp::new("next");
            let out = temp.0.join("ran");
            let missing = Command::new("/nonexistent/xdg-open");
            let failing = sh("exit 4", &out);
            let working = sh(r#"echo END > "$0""#, &out);
            launch(vec![missing, failing, working], &env(), Path::new("/")).unwrap();
            assert_eq!(wait_for(&out), "END\n");
        }

        #[test]
        fn a_launcher_still_running_has_opened_it() {
            let temp = Temp::new("running");
            let out = temp.0.join("ran");
            let started = std::time::Instant::now();
            let waiting = sh(r#"sleep 2; echo END > "$0""#, &out);
            launch(vec![waiting, sh("exit 1", &out)], &env(), Path::new("/")).unwrap();
            assert!(started.elapsed() < std::time::Duration::from_secs(1));
        }

        #[test]
        fn the_first_failure_is_reported_when_none_opens_it() {
            let temp = Temp::new("none");
            let out = temp.0.join("ran");
            let error = launch(
                vec![sh("exit 3", &out), Command::new("/nonexistent/gio")],
                &env(),
                Path::new("/"),
            )
            .unwrap_err();
            assert_eq!(error.to_string(), "sh: exit status: 3");
            let missing = launch(
                vec![Command::new("/nonexistent/gio")],
                &env(),
                Path::new("/"),
            )
            .unwrap_err();
            assert_eq!(missing.kind(), std::io::ErrorKind::NotFound);
        }
    }
}
