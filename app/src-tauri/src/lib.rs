//! The Tauri shell of the editor: a window for the front end (../src), and
//! the Python backend (../backend/server.py) run as a child process.
//!
//! The front end calls one command, `rpc`, with a request for the backend as
//! a line of JSON, and gets the backend's answer back. Requests are written
//! to the backend's standard input and answers read from its standard
//! output, matched up by their `id`; several can be under way at once.
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{channel, Sender};
use std::sync::{Arc, Mutex};

use tauri::webview::PageLoadEvent;
use tauri::Manager;
use tauri_plugin_log::{Target, TargetKind};
use tauri_plugin_opener::OpenerExt;

type Waiting = Arc<Mutex<HashMap<u64, Sender<String>>>>;

struct Backend {
    child: Mutex<Child>,
    /// None once the window has closed, and the backend been told to finish.
    stdin: Mutex<Option<ChildStdin>>,
    /// Who is waiting for the answer to each request under way.
    waiting: Waiting,
}

/// The Python to run the backend with, and the backend itself: those a
/// packaged app carries among its resources, or else (from a checkout) the
/// machine's Python and this project's own backend/server.py.
/// $RESUME_WORKSHOP_PYTHON names another Python.
fn backend_command(resources: Option<PathBuf>) -> Command {
    // As packaging/build_app.py lays a Python out.
    let python_root = resources.as_ref().map(|folder| folder.join("python"));
    let python_name = if cfg!(windows) { "python.exe" } else { "bin/python3" };
    let bundled_python = python_root.as_ref().map(|root| root.join(python_name)).filter(|path| path.exists());
    let bundled_server = resources.as_ref().map(|folder| folder.join("app").join("backend").join("server.py"));

    let chosen = std::env::var_os("RESUME_WORKSHOP_PYTHON").map(PathBuf::from);
    let carried = chosen.is_none() && bundled_python.is_some();
    let python = chosen
        .or(bundled_python)
        .unwrap_or_else(|| PathBuf::from(if cfg!(windows) { "python" } else { "python3" }));
    let server = bundled_server
        .filter(|path| path.exists())
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("backend").join("server.py"));

    let mut command = Command::new(python);
    // A folder given on the command line is the resume to open.
    if let Some(folder) = std::env::args_os().nth(1).filter(|argument| !argument.to_string_lossy().starts_with('-')) {
        command.env("RESUME_WORKSHOP_ROOT", folder);
    }
    if carried {
        // -s -E: only the packages carried with it, whatever the user's
        // site-packages or PYTHONPATH hold.
        command.arg("-s").arg("-E");
    }
    // -B: a packaged app's files are read-only, and a checkout's are kept clean.
    command.arg("-B").arg(server).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console beside the editor
    }
    command
}

fn start_backend(resources: Option<PathBuf>) -> std::io::Result<Backend> {
    let mut child = backend_command(resources).spawn()?;
    let stdin = child.stdin.take().expect("the backend's input is piped");
    let stdout = child.stdout.take().expect("the backend's output is piped");
    let waiting: Waiting = Arc::new(Mutex::new(HashMap::new()));

    let answers = waiting.clone();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            let id = serde_json::from_str::<serde_json::Value>(&line).ok().and_then(|answer| answer["id"].as_u64());
            if let Some(sender) = id.and_then(|id| answers.lock().unwrap().remove(&id)) {
                let _ = sender.send(line);
            }
        }
        // The backend has stopped: nothing more is coming for whoever is waiting.
        answers.lock().unwrap().clear();
    });

    Ok(Backend { child: Mutex::new(child), stdin: Mutex::new(Some(stdin)), waiting })
}

/// Hands a request to the backend, and returns its answer.
#[tauri::command(async)]
fn rpc(request: String, backend: tauri::State<'_, Backend>) -> Result<String, String> {
    let id = serde_json::from_str::<serde_json::Value>(&request)
        .ok()
        .and_then(|request| request["id"].as_u64())
        .ok_or("the request has no id")?;
    let (sender, receiver) = channel();
    backend.waiting.lock().unwrap().insert(id, sender);
    {
        let mut stdin = backend.stdin.lock().unwrap();
        // One request per line; JSON keeps a line break inside a string as \n.
        let written = match stdin.as_mut() {
            Some(stdin) => writeln!(stdin, "{}", request.replace('\n', " ")).and_then(|_| stdin.flush()),
            None => Err(std::io::Error::new(std::io::ErrorKind::BrokenPipe, "the editor is closing")),
        };
        if let Err(error) = written {
            backend.waiting.lock().unwrap().remove(&id);
            return Err(format!("the editor's backend has stopped: {error}"));
        }
    }
    receiver.recv().map_err(|_| "the editor's backend has stopped".to_string())
}

/// Opens the system's print dialog for what the window is showing (File >
/// Print PDF lays the PDF's pages out first).
#[tauri::command]
fn print(window: tauri::WebviewWindow) -> Result<(), String> {
    window.print().map_err(|error| error.to_string())
}

/// Starts the editor again, as after an update: for an AppImage, the file
/// it was started from, which is the new version by then.
#[tauri::command]
fn restart(app: tauri::AppHandle, backend: tauri::State<'_, Backend>) {
    stop_backend(&backend);
    app.restart();
}

/// Lets the backend finish: with its input closed it stops what it started
/// (the grammar checker's server) and exits. It is killed if it hasn't
/// within a few seconds.
fn stop_backend(backend: &Backend) {
    drop(backend.stdin.lock().unwrap().take());
    let mut child = backend.child.lock().unwrap();
    for _ in 0..50 {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
    let _ = child.kill();
}

fn external_navigation_plugin<R: tauri::Runtime>() -> tauri::plugin::TauriPlugin<R> {
    tauri::plugin::Builder::<R>::new("external-navigation")
        .on_navigation(|webview, url| {
            let is_internal_host = matches!(
                url.host_str(),
                Some("localhost") | Some("127.0.0.1") | Some("tauri.localhost") | Some("::1")
            );

            let is_internal = url.scheme() == "tauri" || is_internal_host;

            if is_internal {
                return true;
            }

            let is_external_link = matches!(url.scheme(), "http" | "https" | "mailto" | "tel");

            if is_external_link {
                log::info!("opening external link in system browser: {}", url);
                let _ = webview.opener().open_url(url.as_str(), None::<&str>);
                return false;
            }

            true
        })
        .build()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::new()
                .targets([
                    Target::new(TargetKind::Stdout),
                    Target::new(TargetKind::LogDir { file_name: None }),
                    Target::new(TargetKind::Webview),
                ])
                .build(),
        )
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(external_navigation_plugin())
        .setup(|app| {
            let backend = start_backend(app.path().resource_dir().ok())
                .map_err(|error| format!("The editor's backend could not be started: {error}"))?;
            app.manage(backend);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![rpc, print, restart])
        .on_page_load(|webview, payload| {
            if webview.label() == "main" && matches!(payload.event(), PageLoadEvent::Finished) {
                log::info!("main webview finished loading");
                let _ = webview.window().show();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                // The backend ends with the window.
                if let Some(backend) = app.try_state::<Backend>() {
                    stop_backend(&backend);
                }
            }
        });
}
