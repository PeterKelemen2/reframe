//! The AppImage's entry in the user's application menu: the desktop entry of the .deb, pointing
//! at the AppImage file. With it the desktop knows the window's app (taskbar progress) and offers
//! the app for video files. Only an entry this app wrote is changed or removed.

use std::ffi::OsString;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use serde::Serialize;
use tauri::AppHandle;

/// The name the .deb and .rpm install their entry under.
const FILE_NAME: &str = crate::progress::DESKTOP_ENTRY;
/// Marks an entry this app wrote.
const MARKER: &str = "X-Reframe-AppImage=true";
const ICONS: [(&str, &[u8]); 2] = [
    ("128x128", include_bytes!("../icons/128x128.png")),
    ("256x256", include_bytes!("../icons/128x128@2x.png")),
];

#[derive(Clone, Debug, Default, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MenuEntry {
    /// The AppImage the app runs from; `None` outside one (no entry is offered).
    pub appimage: Option<String>,
    /// This app's entry is in the menu.
    pub added: bool,
    /// Another entry of the same name (an installed package's, or the user's own): this app
    /// adds none, since one would hide the other.
    pub other: Option<PathBuf>,
    /// The AppImage's path has a `%`, which GLib's desktops (GNOME, Xfce, Cinnamon) cannot start
    /// from an entry: this app adds none.
    pub percent_in_path: bool,
}

/// What the entry says about the app.
#[derive(Clone, Debug, PartialEq)]
pub struct AppInfo {
    pub name: String,
    /// The window's app id and the icon's name.
    pub binary: String,
    pub mime_types: Vec<String>,
}

/// The types of a desktop entry's `MimeType=` line.
fn mime_types_of(entry: &str) -> Vec<String> {
    entry
        .lines()
        .find_map(|line| line.trim().strip_prefix("MimeType="))
        .map(|types| {
            types
                .split(';')
                .filter(|kind| !kind.is_empty())
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

impl AppInfo {
    fn of(app: &AppHandle) -> Self {
        let config = app.config();
        // The bundler writes them into the image's own entry; the app's config has no bundle
        // settings at run time.
        let mime_types = std::env::var_os("APPDIR")
            .map(|appdir| {
                PathBuf::from(appdir)
                    .join("usr/share/applications")
                    .join(FILE_NAME)
            })
            .and_then(|entry| fs::read_to_string(entry).ok())
            .map(|entry| mime_types_of(&entry))
            .unwrap_or_default();
        AppInfo {
            name: config
                .product_name
                .clone()
                .unwrap_or_else(|| "Reframe".into()),
            binary: config
                .main_binary_name
                .clone()
                .unwrap_or_else(|| "reframe-desktop".into()),
            mime_types,
        }
    }
}

/// Where the entry goes, and the AppImage it starts.
#[derive(Clone, Debug, PartialEq)]
pub struct Places {
    pub appimage: String,
    pub data_home: PathBuf,
    /// The system's data folders, without the image's own.
    pub data_dirs: Vec<PathBuf>,
}

/// `None` outside an AppImage, and for an AppImage path a desktop entry cannot hold.
#[cfg_attr(not(target_os = "linux"), allow(dead_code))]
pub fn places(vars: impl Fn(&str) -> Option<OsString>) -> Option<Places> {
    let appimage = PathBuf::from(vars("APPIMAGE")?);
    let appimage = appimage
        .is_absolute()
        .then_some(appimage)?
        .into_os_string()
        .into_string()
        .ok()
        .filter(|path| !path.chars().any(char::is_control))?;
    let absolute = |value: OsString| Some(PathBuf::from(value)).filter(|path| path.is_absolute());
    let data_home = vars("XDG_DATA_HOME")
        .and_then(absolute)
        .or_else(|| absolute(vars("HOME")?).map(|home| home.join(".local/share")))?;
    let appdir = vars("APPDIR").and_then(absolute);
    let mut data_dirs: Vec<PathBuf> = vars("XDG_DATA_DIRS")
        .map(|dirs| std::env::split_paths(&dirs).collect())
        .unwrap_or_default();
    data_dirs.retain(|dir| {
        dir.is_absolute()
            && !appdir
                .as_ref()
                .is_some_and(|appdir| dir.starts_with(appdir))
    });
    if data_dirs.is_empty() {
        data_dirs = vec!["/usr/local/share".into(), "/usr/share".into()];
    }
    Some(Places {
        appimage,
        data_home,
        data_dirs,
    })
}

impl Places {
    fn applications(&self) -> PathBuf {
        self.data_home.join("applications")
    }

    fn entry(&self) -> PathBuf {
        self.applications().join(FILE_NAME)
    }

    fn icons(&self, info: &AppInfo) -> impl Iterator<Item = (PathBuf, &'static [u8])> {
        let hicolor = self.data_home.join("icons/hicolor");
        let file = format!("{}.png", info.binary);
        ICONS
            .into_iter()
            .map(move |(size, png)| (hicolor.join(size).join("apps").join(&file), png))
    }
}

fn is_ours(text: &str) -> bool {
    text.lines().any(|line| line.trim() == MARKER)
}

/// The entry's state on disk.
pub fn state(places: &Places) -> MenuEntry {
    let own = places.entry();
    let added = fs::read_to_string(&own).is_ok_and(|text| is_ours(&text));
    let other = if own.exists() {
        (!added).then_some(own)
    } else {
        places
            .data_dirs
            .iter()
            .map(|dir| dir.join("applications").join(FILE_NAME))
            .find(|path| path.exists())
    };
    MenuEntry {
        appimage: Some(places.appimage.clone()),
        added,
        other,
        percent_in_path: has_percent(&places.appimage),
    }
}

/// GLib looks for `Exec=`'s program before it turns the spec's `%%` into `%`, so it never finds
/// a program whose path has a `%` and skips the entry.
fn has_percent(appimage: &str) -> bool {
    appimage.contains('%')
}

/// `path` as one argument of `Exec=`: quoted when it has a reserved character, with `%` doubled,
/// and then written as a desktop entry string, which doubles each backslash.
fn exec_argument(path: &str) -> String {
    const RESERVED: &str = " \t\n\"'\\><~|&;$*?#()`";
    let mut argument = String::new();
    let quoted = path.chars().any(|c| RESERVED.contains(c));
    if quoted {
        argument.push('"');
    }
    for c in path.chars() {
        match c {
            '"' | '`' | '$' | '\\' if quoted => {
                argument.push('\\');
                argument.push(c);
            }
            '%' => argument.push_str("%%"),
            _ => argument.push(c),
        }
    }
    if quoted {
        argument.push('"');
    }
    argument.replace('\\', "\\\\")
}

/// The entry for the AppImage at `appimage`: the .deb's, with the AppImage as the program.
pub fn contents(appimage: &str, info: &AppInfo) -> String {
    let mut lines = vec![
        "[Desktop Entry]".to_owned(),
        "Type=Application".to_owned(),
        format!("Name={}", info.name),
        "Categories=AudioVideo;Video;".to_owned(),
        format!("Exec={} %F", exec_argument(appimage)),
        // A menu hides the entry while the file is gone.
        format!("TryExec={}", appimage.replace('\\', "\\\\")),
        format!("Icon={}", info.binary),
        format!("StartupWMClass={}", info.binary),
        "Terminal=false".to_owned(),
    ];
    if !info.mime_types.is_empty() {
        lines.push(format!("MimeType={};", info.mime_types.join(";")));
    }
    lines.push(MARKER.to_owned());
    lines.join("\n") + "\n"
}

fn write_file(path: &Path, bytes: &[u8]) -> io::Result<()> {
    if let Some(folder) = path.parent() {
        fs::create_dir_all(folder)?;
    }
    let partial = path.with_extension("part");
    let written = fs::write(&partial, bytes).and_then(|()| fs::rename(&partial, path));
    if written.is_err() {
        let _ = fs::remove_file(&partial);
    }
    written
}

fn remove_file(path: &Path) -> io::Result<()> {
    match fs::remove_file(path) {
        Err(error) if error.kind() != io::ErrorKind::NotFound => Err(error),
        _ => Ok(()),
    }
}

/// Writes the entry and its icons, or leaves neither when one cannot be written; refused while
/// another entry of the name exists or the AppImage's path has a `%`.
pub fn add(places: &Places, info: &AppInfo) -> io::Result<()> {
    if let Some(other) = state(places).other {
        return Err(io::Error::other(format!(
            "the application menu already has {}",
            other.display()
        )));
    }
    if has_percent(&places.appimage) {
        return Err(io::Error::other(
            "the AppImage's path has a %, which the desktop cannot start from a menu entry",
        ));
    }
    write_file(&places.entry(), contents(&places.appimage, info).as_bytes())?;
    let icons = places
        .icons(info)
        .try_for_each(|(path, png)| write_file(&path, png));
    if icons.is_err() {
        let _ = remove_entry_and_icons(places, info);
    }
    icons
}

/// Removes this app's entry and icons; another entry stays.
pub fn remove(places: &Places, info: &AppInfo) -> io::Result<()> {
    if !state(places).added {
        return Ok(());
    }
    remove_entry_and_icons(places, info)
}

fn remove_entry_and_icons(places: &Places, info: &AppInfo) -> io::Result<()> {
    remove_file(&places.entry())?;
    for (path, _) in places.icons(info) {
        remove_file(&path)?;
    }
    Ok(())
}

/// Points this app's entry at the AppImage the app runs from, when it pointed at another (the
/// file was moved, or another copy wrote it). `true` when it was rewritten; never to a path
/// with a `%`.
pub fn follow(places: &Places, info: &AppInfo) -> io::Result<bool> {
    if has_percent(&places.appimage) {
        return Ok(false);
    }
    let wanted = contents(&places.appimage, info);
    match fs::read_to_string(places.entry()) {
        Ok(text) if is_ours(&text) && text != wanted => {
            write_file(&places.entry(), wanted.as_bytes())?;
            Ok(true)
        }
        _ => Ok(false),
    }
}

#[cfg(target_os = "linux")]
fn current() -> Option<Places> {
    places(|name| std::env::var_os(name))
}

#[cfg(not(target_os = "linux"))]
fn current() -> Option<Places> {
    None
}

/// Rebuilds the desktop's cache of which app opens which file type, where the tool exists. Run
/// with the user's environment: the image's libraries break the system's programs.
#[cfg(target_os = "linux")]
fn update_database(app: &AppHandle, places: &Places) {
    use std::process::{Command, Stdio};
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    let env = crate::appimage::user_environ(std::env::vars_os(), &exe, &app.config().identifier);
    let _ = Command::new("update-desktop-database")
        .arg("-q")
        .arg(places.applications())
        .env_clear()
        .envs(env)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

#[cfg(not(target_os = "linux"))]
fn update_database(_app: &AppHandle, _places: &Places) {}

#[tauri::command]
pub fn menu_entry() -> MenuEntry {
    current().map(|places| state(&places)).unwrap_or_default()
}

/// Adds (`add`) or removes this app's entry.
#[tauri::command]
pub async fn set_menu_entry(app: AppHandle, add: bool) -> Result<MenuEntry, String> {
    let places = current().ok_or("the app does not run from an AppImage")?;
    tauri::async_runtime::spawn_blocking(move || {
        let info = AppInfo::of(&app);
        let done = if add {
            self::add(&places, &info)
        } else {
            remove(&places, &info)
        };
        update_database(&app, &places);
        done.map_err(|error| error.to_string())?;
        Ok(state(&places))
    })
    .await
    .map_err(|error| error.to_string())?
}

/// At start: an entry this app wrote follows the AppImage to where it now is.
pub fn follow_at_start(app: &AppHandle) {
    let Some(places) = current() else {
        return;
    };
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        if follow(&places, &AppInfo::of(&app)).unwrap_or(false) {
            update_database(&app, &places);
        }
    });
}

#[cfg(all(test, unix))]
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

    fn info() -> AppInfo {
        AppInfo {
            name: "Reframe".into(),
            binary: "reframe-desktop".into(),
            mime_types: vec!["video/x-matroska".into(), "video/mp4".into()],
        }
    }

    struct Temp(PathBuf);

    impl Temp {
        fn new(name: &str) -> Self {
            let dir = std::env::temp_dir()
                .join(format!("reframe-menu-entry-{name}-{}", std::process::id()));
            let _ = fs::remove_dir_all(&dir);
            fs::create_dir_all(&dir).unwrap();
            Self(dir)
        }

        fn places(&self, appimage: &str) -> Places {
            Places {
                appimage: appimage.into(),
                data_home: self.0.join("home"),
                data_dirs: vec![self.0.join("system")],
            }
        }
    }

    impl Drop for Temp {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn the_entry_goes_into_the_users_data_folder_and_skips_the_images() {
        let image = vars(&[
            ("APPIMAGE", "/home/u/Apps/Reframe.AppImage"),
            ("APPDIR", "/tmp/.mount_ab12"),
            ("HOME", "/home/u"),
            (
                "XDG_DATA_DIRS",
                "/tmp/.mount_ab12/usr/share:/usr/share:/tmp/.mount_ab12/usr/share/:data",
            ),
        ]);
        assert_eq!(
            places(image),
            Some(Places {
                appimage: "/home/u/Apps/Reframe.AppImage".into(),
                data_home: "/home/u/.local/share".into(),
                data_dirs: vec!["/usr/share".into()],
            })
        );
        let xdg = vars(&[
            ("APPIMAGE", "/a/R.AppImage"),
            ("HOME", "/home/u"),
            ("XDG_DATA_HOME", "/data"),
        ]);
        let xdg = places(xdg).unwrap();
        assert_eq!(xdg.data_home, PathBuf::from("/data"));
        assert_eq!(
            xdg.data_dirs,
            [PathBuf::from("/usr/local/share"), "/usr/share".into()]
        );
    }

    #[test]
    fn without_an_appimage_there_is_no_entry() {
        assert_eq!(places(vars(&[("HOME", "/home/u")])), None);
        let relative = vars(&[("APPIMAGE", "R.AppImage"), ("HOME", "/home/u")]);
        assert_eq!(places(relative), None);
        let newline = vars(&[("APPIMAGE", "/a/R\n.AppImage"), ("HOME", "/home/u")]);
        assert_eq!(places(newline), None);
        let no_home = vars(&[("APPIMAGE", "/a/R.AppImage")]);
        assert_eq!(places(no_home), None);
    }

    #[test]
    fn the_entry_is_the_packages_with_the_appimage_as_the_program() {
        assert_eq!(
            contents("/home/u/Apps/Reframe.AppImage", &info()),
            "[Desktop Entry]\n\
             Type=Application\n\
             Name=Reframe\n\
             Categories=AudioVideo;Video;\n\
             Exec=/home/u/Apps/Reframe.AppImage %F\n\
             TryExec=/home/u/Apps/Reframe.AppImage\n\
             Icon=reframe-desktop\n\
             StartupWMClass=reframe-desktop\n\
             Terminal=false\n\
             MimeType=video/x-matroska;video/mp4;\n\
             X-Reframe-AppImage=true\n"
        );
    }

    #[test]
    fn the_file_types_come_from_the_images_own_entry() {
        let entry = "[Desktop Entry]\nName=Reframe\nMimeType=video/x-matroska;video/mp4\n";
        assert_eq!(mime_types_of(entry), ["video/x-matroska", "video/mp4"]);
        assert_eq!(mime_types_of("MimeType=video/webm;\n"), ["video/webm"]);
        assert!(mime_types_of("[Desktop Entry]\nName=Reframe\n").is_empty());
    }

    #[test]
    fn an_appimage_path_with_reserved_characters_is_quoted() {
        assert_eq!(
            exec_argument("/a/Re frame.AppImage"),
            "\"/a/Re frame.AppImage\""
        );
        assert_eq!(exec_argument("/a/100%.AppImage"), "/a/100%%.AppImage");
        assert_eq!(
            exec_argument(r#"/a/"$x`\.AppImage"#),
            r#""/a/\\"\\$x\\`\\\\.AppImage""#
        );
        assert_eq!(
            exec_argument("/a/Árvíztűrő.AppImage"),
            "/a/Árvíztűrő.AppImage"
        );
    }

    #[test]
    fn an_entry_is_added_and_removed_with_its_icons() {
        let temp = Temp::new("add");
        let places = temp.places("/a/Reframe.AppImage");
        assert_eq!(
            state(&places),
            MenuEntry {
                appimage: Some("/a/Reframe.AppImage".into()),
                added: false,
                other: None,
                percent_in_path: false,
            }
        );
        add(&places, &info()).unwrap();
        assert!(state(&places).added);
        let entry = temp.0.join("home/applications/Reframe.desktop");
        assert_eq!(
            fs::read_to_string(&entry).unwrap(),
            contents("/a/Reframe.AppImage", &info())
        );
        let icon = temp
            .0
            .join("home/icons/hicolor/256x256/apps/reframe-desktop.png");
        assert_eq!(fs::read(&icon).unwrap(), ICONS[1].1);
        remove(&places, &info()).unwrap();
        assert!(!entry.exists() && !icon.exists());
        assert!(temp.0.join("home/applications").is_dir());
        assert!(!state(&places).added);
    }

    #[test]
    fn another_entry_of_the_name_is_never_replaced_or_removed() {
        let temp = Temp::new("other");
        let places = temp.places("/a/Reframe.AppImage");
        let system = temp.0.join("system/applications/Reframe.desktop");
        write_file(&system, b"[Desktop Entry]\nExec=reframe-desktop %F\n").unwrap();
        assert_eq!(state(&places).other, Some(system.clone()));
        assert!(add(&places, &info()).is_err());
        assert!(!places.entry().exists());

        let users = places.entry();
        write_file(&users, b"[Desktop Entry]\nExec=/opt/my-reframe %F\n").unwrap();
        assert_eq!(state(&places).other, Some(users.clone()));
        assert!(add(&places, &info()).is_err());
        remove(&places, &info()).unwrap();
        assert!(!follow(&places, &info()).unwrap());
        assert_eq!(
            fs::read_to_string(&users).unwrap(),
            "[Desktop Entry]\nExec=/opt/my-reframe %F\n"
        );
    }

    #[test]
    fn a_failed_add_leaves_no_entry_and_no_icons() {
        let temp = Temp::new("blocked-entry");
        let places = temp.places("/a/Reframe.AppImage");
        // A file where the applications folder goes: the entry cannot be written.
        write_file(&places.applications(), b"").unwrap();
        assert!(add(&places, &info()).is_err());
        assert!(!temp.0.join("home/icons").exists());

        let temp = Temp::new("blocked-icons");
        let places = temp.places("/a/Reframe.AppImage");
        write_file(&temp.0.join("home/icons/hicolor/256x256"), b"").unwrap();
        assert!(add(&places, &info()).is_err());
        assert!(!places.entry().exists());
        let icons: Vec<_> = places.icons(&info()).map(|(path, _)| path).collect();
        assert!(icons.iter().all(|icon| !icon.exists()), "{icons:?}");
        assert_eq!(
            fs::read_dir(places.applications()).unwrap().count(),
            0,
            "no partial file is left"
        );
    }

    #[test]
    fn an_appimage_path_with_a_percent_gets_no_entry() {
        let temp = Temp::new("percent");
        let places = temp.places("/a/100%/Reframe.AppImage");
        assert!(state(&places).percent_in_path);
        assert!(add(&places, &info()).is_err());
        assert!(!places.entry().exists());
        assert!(!temp.0.join("home/icons").exists());

        add(&temp.places("/a/Reframe.AppImage"), &info()).unwrap();
        assert!(!follow(&places, &info()).unwrap());
        assert_eq!(
            fs::read_to_string(places.entry()).unwrap(),
            contents("/a/Reframe.AppImage", &info())
        );
        let state = state(&places);
        assert!(state.added && state.percent_in_path);
        remove(&places, &info()).unwrap();
        assert!(!places.entry().exists());
    }

    #[test]
    fn the_entry_follows_the_appimage_that_runs() {
        let temp = Temp::new("follow");
        add(&temp.places("/old/Reframe.AppImage"), &info()).unwrap();
        let moved = temp.places("/new/Reframe.AppImage");
        assert!(follow(&moved, &info()).unwrap());
        assert_eq!(
            fs::read_to_string(moved.entry()).unwrap(),
            contents("/new/Reframe.AppImage", &info())
        );
        assert!(!follow(&moved, &info()).unwrap());
        assert!(!follow(&Temp::new("none").places("/a/R.AppImage"), &info()).unwrap());
    }
}
