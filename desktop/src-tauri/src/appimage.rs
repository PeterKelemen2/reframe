//! What AppRun changes for the app inside an AppImage: it starts the app in `$APPDIR/usr`
//! (the user's folder is in `OWD`), and points `PATH`, `LD_LIBRARY_PATH`, the GTK and GIO
//! variables and more into the image (`APPDIR`). Outside an AppImage these change nothing.

use std::ffi::OsString;
use std::path::PathBuf;

/// The folder the user started the AppImage from.
pub fn launch_folder(vars: impl Fn(&str) -> Option<OsString>) -> Option<PathBuf> {
    vars("APPIMAGE")?;
    let folder = PathBuf::from(vars("OWD")?);
    folder.is_absolute().then_some(folder)
}

/// Makes the user's folder the working folder until [`leave_launch_folder`]: a relative
/// argument, and the folder a second launch hands to the first, are the user's. Returns the
/// image's folder.
pub fn enter_launch_folder() -> Option<PathBuf> {
    let folder = launch_folder(|name| std::env::var_os(name))?;
    let image = std::env::current_dir().ok()?;
    std::env::set_current_dir(folder).ok()?;
    Some(image)
}

/// Back to the image's folder before any webview starts: WebKit finds its helper processes by
/// paths relative to it.
pub fn leave_launch_folder(image: Option<PathBuf>) {
    if let Some(image) = image {
        let _ = std::env::set_current_dir(image);
    }
}

/// Set for the image with values that do not name it: the runtime's own, the GTK hook's forced
/// theme, AppRun's Python switch.
#[cfg(unix)]
const IMAGE_ONLY: [&str; 5] = [
    "APPIMAGE",
    "ARGV0",
    "OWD",
    "GTK_THEME",
    "PYTHONDONTWRITEBYTECODE",
];

/// The environment for a program opened for the user (a player, a browser): every entry under
/// `APPDIR` is dropped from every variable (a variable left empty is removed), and so are the
/// variables set only for the image. Unchanged unless `exe` is inside `APPDIR`.
#[cfg(unix)]
pub fn user_environ(
    vars: impl IntoIterator<Item = (OsString, OsString)>,
    exe: &std::path::Path,
) -> Vec<(OsString, OsString)> {
    use std::os::unix::ffi::{OsStrExt, OsStringExt};

    let vars: Vec<_> = vars.into_iter().collect();
    let appdir = vars
        .iter()
        .find(|(name, _)| name == "APPDIR")
        .map(|(_, value)| {
            let mut dir = value.as_bytes();
            while let Some(rest) = dir.strip_suffix(b"/") {
                dir = rest;
            }
            dir
        });
    let appdir = match appdir {
        Some(dir) if dir.starts_with(b"/") => dir.to_vec(),
        _ => return vars,
    };
    if !exe.starts_with(std::ffi::OsStr::from_bytes(&appdir)) {
        return vars;
    }
    let inside = |entry: &[u8]| {
        entry
            .strip_prefix(appdir.as_slice())
            .is_some_and(|rest| rest.is_empty() || rest.starts_with(b"/"))
    };
    vars.into_iter()
        .filter(|(name, _)| !IMAGE_ONLY.iter().any(|only| name == only))
        .filter_map(|(name, value)| {
            let entries: Vec<&[u8]> = value.as_bytes().split(|byte| *byte == b':').collect();
            if !entries.iter().any(|entry| inside(entry)) {
                return Some((name, value));
            }
            // An empty entry in a search path means the working folder.
            let kept: Vec<&[u8]> = entries
                .into_iter()
                .filter(|entry| !entry.is_empty() && !inside(entry))
                .collect();
            (!kept.is_empty()).then(|| (name, OsString::from_vec(kept.join(&b':'))))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn vars(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<OsString> {
        let pairs: HashMap<String, OsString> = pairs
            .iter()
            .map(|(name, value)| ((*name).to_owned(), OsString::from(value)))
            .collect();
        move |name| pairs.get(name).cloned()
    }

    // An AppImage exists only on Linux; `/home/u/films` is not an absolute path on Windows.
    #[cfg(unix)]
    #[test]
    fn an_appimage_started_from_a_folder_works_in_that_folder() {
        let image = vars(&[
            ("APPIMAGE", "/home/u/Apps/Reframe.AppImage"),
            ("APPDIR", "/tmp/.mount_ab12/"),
            ("OWD", "/home/u/films"),
        ]);
        assert_eq!(launch_folder(image), Some(PathBuf::from("/home/u/films")));
    }

    #[test]
    fn without_the_appimage_runtime_the_folder_stays() {
        assert_eq!(launch_folder(vars(&[("OWD", "/home/u/films")])), None);
        assert_eq!(launch_folder(vars(&[("APPIMAGE", "/a/R.AppImage")])), None);
        let relative = vars(&[("APPIMAGE", "/a/R.AppImage"), ("OWD", "films")]);
        assert_eq!(launch_folder(relative), None);
    }

    #[cfg(unix)]
    mod environ {
        use super::*;
        use std::path::Path;

        const APPDIR: &str = "/tmp/.mount_ab12";

        fn user(pairs: &[(&str, &str)], exe: &str) -> HashMap<String, String> {
            let pairs = pairs
                .iter()
                .map(|(name, value)| (OsString::from(name), OsString::from(value)));
            user_environ(pairs, Path::new(exe))
                .into_iter()
                .map(|(name, value)| (name.into_string().unwrap(), value.into_string().unwrap()))
                .collect()
        }

        /// What the AppImage runtime, AppRun and its GTK hook give the app (read from the built
        /// AppImage), on top of the user's own variables.
        fn image_env() -> Vec<(&'static str, String)> {
            let d = APPDIR;
            vec![
                ("APPDIR", d.to_owned()),
                ("APPIMAGE", "/home/u/Apps/Reframe.AppImage".to_owned()),
                ("ARGV0", "./Reframe.AppImage".to_owned()),
                ("OWD", "/home/u/films".to_owned()),
                (
                    "PATH",
                    format!("{d}/usr/bin/:{d}/usr/sbin/:{d}/bin/:/usr/bin:/home/u/bin"),
                ),
                (
                    "LD_LIBRARY_PATH",
                    format!("{d}/usr/lib/:{d}/usr/lib/x86_64-linux-gnu/:{d}/lib64/:"),
                ),
                (
                    "XDG_DATA_DIRS",
                    format!("{d}/usr/share:/usr/share:{d}/usr/share/:/usr/local/share"),
                ),
                ("GTK_PATH", format!("{d}//usr/lib/gtk-3.0")),
                ("GTK_DATA_PREFIX", d.to_owned()),
                ("GIO_MODULE_DIR", format!("{d}//usr/lib/gio/modules")),
                ("PYTHONHOME", format!("{d}/usr/")),
                ("PYTHONDONTWRITEBYTECODE", "1".to_owned()),
                ("GTK_THEME", "Adwaita:dark".to_owned()),
                ("HOME", "/home/u".to_owned()),
                ("LANG", "hu_HU.UTF-8".to_owned()),
                ("WAYLAND_DISPLAY", "wayland-0".to_owned()),
            ]
        }

        fn run(exe: &str) -> HashMap<String, String> {
            let pairs = image_env();
            let pairs: Vec<(&str, &str)> = pairs.iter().map(|(n, v)| (*n, v.as_str())).collect();
            user(&pairs, exe)
        }

        #[test]
        fn a_program_opened_from_the_appimage_gets_the_users_environment() {
            let env = run(&format!("{APPDIR}/usr/bin/reframe-desktop"));
            let expected: HashMap<String, String> = [
                ("PATH", "/usr/bin:/home/u/bin"),
                ("XDG_DATA_DIRS", "/usr/share:/usr/local/share"),
                ("HOME", "/home/u"),
                ("LANG", "hu_HU.UTF-8"),
                ("WAYLAND_DISPLAY", "wayland-0"),
            ]
            .into_iter()
            .map(|(name, value)| (name.to_owned(), value.to_owned()))
            .collect();
            assert_eq!(env, expected);
        }

        #[test]
        fn a_folder_next_to_the_image_is_not_inside_it() {
            let env = user(
                &[
                    ("APPDIR", "/tmp/.mount_ab12//"),
                    (
                        "PATH",
                        "/tmp/.mount_ab12x/bin:/tmp/.mount_ab12/usr/bin:/usr/bin",
                    ),
                ],
                "/tmp/.mount_ab12/usr/bin/reframe-desktop",
            );
            assert_eq!(env["PATH"], "/tmp/.mount_ab12x/bin:/usr/bin");
        }

        #[test]
        fn outside_the_image_nothing_changes() {
            for exe in [
                "/usr/bin/reframe-desktop",
                "/tmp/.mount_ab12x/usr/bin/reframe-desktop",
            ] {
                let env = run(exe);
                assert_eq!(env.len(), image_env().len(), "{exe}");
                assert_eq!(env["GTK_THEME"], "Adwaita:dark");
            }
            let relative = user(
                &[("APPDIR", "squashfs-root"), ("GTK_THEME", "a")],
                "squashfs-root/x",
            );
            assert_eq!(relative["GTK_THEME"], "a");
        }

        #[test]
        fn a_value_that_is_not_unicode_keeps_its_bytes() {
            use std::os::unix::ffi::OsStringExt;
            let bad = OsString::from_vec(b"/tmp/.mount_ab12/usr/x:/media/\xff".to_vec());
            let env = user_environ(
                [
                    (OsString::from("APPDIR"), OsString::from(APPDIR)),
                    (OsString::from("MY_PATH"), bad),
                ],
                Path::new("/tmp/.mount_ab12/usr/bin/reframe-desktop"),
            );
            let kept = OsString::from_vec(b"/media/\xff".to_vec());
            assert_eq!(env, [(OsString::from("MY_PATH"), kept)]);
        }
    }
}
