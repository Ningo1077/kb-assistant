#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{
    AppHandle, Emitter, Manager, RunEvent, WindowEvent,
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

struct Backend(Mutex<Option<Child>>);

fn tcp_ready(port: u16) -> bool {
    TcpStream::connect(("127.0.0.1", port)).is_ok()
}

fn backend_dir() -> Option<PathBuf> {
    // 1) 显式环境变量
    if let Ok(dir) = std::env::var("KB_BACKEND_DIR") {
        let p = PathBuf::from(dir);
        if p.join("app").exists() {
            return Some(p);
        }
    }
    // 2) 打包后：资源目录下的 backend/
    #[cfg(not(debug_assertions))]
    if let Ok(exe) = std::env::current_exe() {
        // 安装目录 = exe 所在目录；资源目录由 tauri 配置决定
        if let Some(root) = exe.parent() {
            let p = root.join("backend");
            if p.join("app").exists() {
                return Some(p);
            }
        }
    }
    // 3) 开发期：源码相对路径
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../backend");
    if p.join("app").exists() {
        return Some(p);
    }
    None
}

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn spawn_backend(dir: &PathBuf, port: u16) -> Result<Child, String> {
    let venv_python = dir.join(".venv/Scripts/python.exe");
    let python = if venv_python.exists() {
        venv_python
    } else {
        PathBuf::from("python")
    };
    let mut cmd = Command::new(&python);
    cmd.args([
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        &port.to_string(),
    ])
    .current_dir(dir);
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd.spawn()
        .map_err(|e| format!("启动后端失败 ({}): {}", python.display(), e))
}

/// 拉起后端并等待端口就绪；8000 已有服务则直接复用（Web 端同开场景）
fn ensure_backend(app: &AppHandle) {
    let port: u16 = std::env::var("KB_BACKEND_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8000);

    let already = tcp_ready(port);
    if !already {
        let dir = match backend_dir() {
            Some(d) => d,
            None => {
                eprintln!("[kb] 未找到 backend 目录，跳过后端拉起");
                return;
            }
        };
        match spawn_backend(&dir, port) {
            Ok(child) => {
                *app.state::<Backend>().0.lock().unwrap() = Some(child);
                eprintln!("[kb] 后端进程已启动: {}", dir.display());
            }
            Err(e) => {
                eprintln!("[kb] {}", e);
                return;
            }
        }
    }

    let deadline = Instant::now() + Duration::from_secs(if already { 5 } else { 60 });
    while Instant::now() < deadline {
        if tcp_ready(port) {
            eprintln!("[kb] 后端就绪 (127.0.0.1:{})", port);
            break;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    // 无论是否就绪都显示窗口；未就绪时前端接口报错可见
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
        let _ = app.emit("backend-ready", port);
    }
}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn main() {
    tauri::Builder::default()
        .manage(Backend(Mutex::new(None)))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    // 只注册了 Ctrl+Shift+K 一个快捷键，按下即切换窗口
                    if event.state() == ShortcutState::Pressed {
                        if let Some(w) = app.get_webview_window("main") {
                            if w.is_visible().unwrap_or(false) && w.is_focused().unwrap_or(false) {
                                let _ = w.hide(); // 已聚焦 → 隐藏
                            } else {
                                show_main(app);
                            }
                        }
                    }
                })
                .build(),
        )
        .setup(|app| {
            // 系统托盘
            let show = MenuItem::with_id(app, "show", "显示窗口", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::with_id("main-tray")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("AI 知识库问答助手")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let tauri::tray::TrayIconEvent::DoubleClick { .. } = event {
                        show_main(tray.app_handle());
                    }
                })
                .build(app)?;

            // 全局快捷键 Ctrl+Shift+K 唤起/隐藏
            app.global_shortcut().register("ctrl+shift+K")?;

            // 后端拉起放后台线程，避免阻塞主线程
            let handle = app.handle().clone();
            std::thread::spawn(move || ensure_backend(&handle));

            Ok(())
        })
        .on_window_event(|window, event| {
            // 点关闭 → 隐藏到托盘；真正退出走托盘菜单
            if let WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                // 退出时杀掉后端子进程
                if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
