//! The windows: the main window (its size, place and maximised state kept between runs) and the
//! detached preview window.

use tauri::plugin::TauriPlugin;
use tauri::{AppHandle, Manager, Runtime, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_window_state::StateFlags;

const PREVIEW: &str = "preview";

/// wry's own WebView2 switches, used when none are given (wry 0.57 `webview2/mod.rs`).
const WRY_BROWSER_ARGS: &str = "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection";

/// Under `tauri-driver`, the switches msedgedriver asks for (its DevTools port) on top of wry's.
/// wry always passes its own switches to WebView2, which then ignores
/// `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`, so WebDriver could not attach. Only an automated
/// run changes the switches, never a user's environment.
fn automation_browser_args(automation: Option<&str>, extra: Option<&str>) -> Option<String> {
    match (automation, extra) {
        (Some("true"), Some(extra)) if !extra.trim().is_empty() => {
            Some(format!("{WRY_BROWSER_ARGS} {extra}"))
        }
        _ => None,
    }
}

fn with_automation_args<'a, R: Runtime, M: Manager<R>>(
    builder: WebviewWindowBuilder<'a, R, M>,
) -> WebviewWindowBuilder<'a, R, M> {
    let automation = std::env::var("TAURI_WEBVIEW_AUTOMATION").ok();
    let extra = std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS").ok();
    match automation_browser_args(automation.as_deref(), extra.as_deref()) {
        Some(args) => builder.additional_browser_args(&args),
        None => builder,
    }
}

/// Keeps the size, the place and the maximised state of each window. Not whether it was
/// visible: an app quit from the tray would start hidden.
pub fn window_state<R: Runtime>() -> TauriPlugin<R> {
    tauri_plugin_window_state::Builder::new()
        .with_state_flags(StateFlags::SIZE | StateFlags::POSITION | StateFlags::MAXIMIZED)
        .build()
}

// Each window is built hidden and shown after: the plugin restores its state while it is
// built, and a window shown first would jump there.

pub fn create_main_window(app: &AppHandle) -> tauri::Result<()> {
    let builder = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()));
    let window = with_automation_args(builder)
        .title("Reframe")
        .inner_size(1280.0, 800.0)
        .min_inner_size(1100.0, 700.0)
        .visible(false)
        .build()?;
    #[cfg(windows)]
    fit_into_work_area(&window)?;
    window.show()
}

/// A window's or a work area's place and size, in physical pixels.
#[cfg(any(windows, test))]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Rect {
    x: i32,
    y: i32,
    width: u32,
    height: u32,
}

/// `window` shrunk and moved into `area`, or `None` when it is inside already.
#[cfg(any(windows, test))]
fn fit(window: Rect, area: Rect) -> Option<Rect> {
    let width = window.width.min(area.width);
    let height = window.height.min(area.height);
    let clamp = |at: i32, start: i32, room: u32, size: u32| {
        let last = start.saturating_add(i32::try_from(room - size).unwrap_or(i32::MAX));
        at.clamp(start, last)
    };
    let fitted = Rect {
        x: clamp(window.x, area.x, area.width, width),
        y: clamp(window.y, area.y, area.height, height),
        width,
        height,
    };
    (fitted != window).then_some(fitted)
}

/// Windows places a new window without regard to the taskbar, and a saved place may be from a
/// larger screen: the status bar would be under the taskbar or off the screen.
#[cfg(windows)]
fn fit_into_work_area<R: Runtime>(window: &tauri::WebviewWindow<R>) -> tauri::Result<()> {
    use tauri::{PhysicalPosition, PhysicalSize};

    if window.is_maximized()? {
        return Ok(());
    }
    let Some(monitor) = window.current_monitor()? else {
        return Ok(());
    };
    let work = monitor.work_area();
    let area = Rect {
        x: work.position.x,
        y: work.position.y,
        width: work.size.width,
        height: work.size.height,
    };
    let (outer, inner, at) = (
        window.outer_size()?,
        window.inner_size()?,
        window.outer_position()?,
    );
    let frame = (outer.width - inner.width, outer.height - inner.height);
    let current = Rect {
        x: at.x,
        y: at.y,
        width: outer.width,
        height: outer.height,
    };
    let Some(fitted) = fit(current, area) else {
        return Ok(());
    };
    let scale = monitor.scale_factor();
    let min = PhysicalSize::new(
        ((1100.0 * scale) as u32).min(fitted.width - frame.0),
        ((700.0 * scale) as u32).min(fitted.height - frame.1),
    );
    window.set_min_size(Some(min))?;
    window.set_size(PhysicalSize::new(
        fitted.width - frame.0,
        fitted.height - frame.1,
    ))?;
    window.set_position(PhysicalPosition::new(fitted.x, fitted.y))
}

/// Opens the preview window on `/preview/<source_id>`, or focuses it when it is open.
#[tauri::command]
pub async fn open_preview_window(app: AppHandle, source_id: String) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(PREVIEW) {
        let _ = window.unminimize();
        return window.set_focus().map_err(|error| error.to_string());
    }
    if !is_source_id(&source_id) {
        return Err(format!("Not a source id: {source_id:?}"));
    }
    let url = WebviewUrl::App(format!("preview/{source_id}").into());
    let window = with_automation_args(WebviewWindowBuilder::new(&app, PREVIEW, url))
        .title("Reframe preview")
        .inner_size(960.0, 720.0)
        .min_inner_size(480.0, 360.0)
        .visible(false)
        .build()
        .map_err(|error| error.to_string())?;
    window.show().map_err(|error| error.to_string())
}

/// The server's source ids are hex; anything else would change the route.
fn is_source_id(value: &str) -> bool {
    !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_alphanumeric())
}

#[cfg(test)]
mod tests {
    use super::*;

    const AREA: Rect = Rect {
        x: 0,
        y: 0,
        width: 1600,
        height: 860,
    };

    #[test]
    fn a_window_inside_the_work_area_stays_where_it_is() {
        let window = Rect {
            x: 160,
            y: 20,
            width: 1296,
            height: 839,
        };
        assert_eq!(fit(window, AREA), None);
    }

    #[test]
    fn a_window_that_reaches_under_the_taskbar_moves_up() {
        let window = Rect {
            x: 208,
            y: 61,
            width: 1296,
            height: 839,
        };
        let fitted = Rect { y: 21, ..window };
        assert_eq!(fit(window, AREA), Some(fitted));
    }

    #[test]
    fn a_window_larger_than_the_work_area_shrinks_into_it() {
        let window = Rect {
            x: -8,
            y: -8,
            width: 1616,
            height: 916,
        };
        assert_eq!(fit(window, AREA), Some(AREA));
    }

    #[test]
    fn a_window_on_another_monitor_comes_back_onto_this_one() {
        let area = Rect { x: 1920, ..AREA };
        let window = Rect {
            x: 100,
            y: 100,
            width: 800,
            height: 600,
        };
        let fitted = Rect { x: 1920, ..window };
        assert_eq!(fit(window, area), Some(fitted));
    }

    #[test]
    fn only_an_automated_run_adds_the_drivers_switches_to_wrys() {
        let port = Some("--remote-debugging-port=0");
        assert_eq!(
            automation_browser_args(Some("true"), port).as_deref(),
            Some(
                "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection \
                 --remote-debugging-port=0"
            )
        );
        assert_eq!(automation_browser_args(None, port), None);
        assert_eq!(automation_browser_args(Some("false"), port), None);
        assert_eq!(automation_browser_args(Some("true"), None), None);
        assert_eq!(automation_browser_args(Some("true"), Some(" ")), None);
    }

    #[test]
    fn a_source_id_cannot_leave_the_preview_route() {
        assert!(is_source_id("3f9a0c4e1b2d7a8f6e5c4b3a"));
        for other in ["", "../settings", "a/b", "a?b", "a#b", "a b"] {
            assert!(!is_source_id(other), "{other:?}");
        }
    }
}
