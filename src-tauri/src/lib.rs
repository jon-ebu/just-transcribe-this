use std::sync::Mutex;
use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

type BackendChild = Mutex<Option<tauri_plugin_shell::process::CommandChild>>;

fn kill_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<BackendChild>() {
        if let Some(child) = state.lock().unwrap().take() {
            let _ = child.kill();
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let (mut rx, child) = handle
                    .shell()
                    .sidecar("backend")
                    .expect("backend sidecar not found")
                    .spawn()
                    .expect("failed to spawn backend sidecar");

                handle.manage(Mutex::new(Some(child)));

                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            println!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Error(e) => {
                            eprintln!("[backend error] {e}");
                        }
                        CommandEvent::Terminated(status) => {
                            eprintln!("[backend] process exited: {status:?}");
                            break;
                        }
                        _ => {}
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| match event {
            // Clean up on normal exit.
            RunEvent::Exit => kill_backend(app),
            // On macOS, closing the window hides rather than quits the app by default.
            // For this single-window utility that means the backend keeps running and
            // blocks the port the next time the user opens the app. Treat window close
            // as a full quit instead.
            RunEvent::WindowEvent {
                event: WindowEvent::CloseRequested { .. },
                ..
            } => {
                kill_backend(app);
                app.exit(0);
            }
            _ => {}
        });
}
