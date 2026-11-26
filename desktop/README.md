# margin Windows desktop app

Wraps the existing web UI (`ui/`) and local API (`margin-api`) in a native Windows window using
`pywebview` (Microsoft Edge WebView2), bundled with Python and all agent packages via PyInstaller
(`--onedir`) and packaged into a Windows installer with Inno Setup.

## How it works

- `desktop/launcher.py` starts `margin-api` on a free `127.0.0.1` port in a background thread,
  stores uploads and run outputs in `%LOCALAPPDATA%\margin\files`, opens a WebView2 window, and
  shuts the server down cleanly when the window closes.
- Repository agents (`ai-code-detector`, `commit-graph`, `secret-leaks`) use the system `git` on
  `PATH`. If `git` is missing, the UI shows a banner with an install link and disables only the
  git-dependent agents while `data-storyteller` continues to work normally.

## Build locally on Windows

Prerequisites: Python 3.11+, `uv`, Node 20+, and [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`) for the `.exe` installer.

```powershell
uv run python desktop/build_windows.py
```

Outputs:

- Standalone folder: `build/desktop/dist/margin/margin.exe`
- Windows installer: `build/desktop/installer/margin-setup-<version>.exe`

Useful flags:

- `--skip-ui` — reuse an existing `ui/dist` build
- `--skip-installer` — build and smoke-test `margin.exe` only
