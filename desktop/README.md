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
- **Auto-updater:** On startup, the UI checks `GET /updates` against GitHub Releases (cached for
  15 minutes). When a newer release exists, an **Update** button appears in the top bar; hovering
  shows the release notes, and clicking downloads the verified `.exe` installer (checking its
  `.sha256` file when present), launches it silently, and restarts margin.

## Build locally on Windows

Prerequisites: Python 3.11+, `uv`, Node 20+, and [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`) for the `.exe` installer.

```powershell
uv run python desktop/build_windows.py
```

Outputs:

- Standalone folder: `build/desktop/dist/margin/margin.exe`
- Windows installer: `build/desktop/installer/margin-setup-<version>.exe`
- SHA-256 checksum: `build/desktop/installer/margin-setup-<version>.exe.sha256`

Useful flags:

- `--skip-ui` — reuse an existing `ui/dist` build
- `--skip-installer` — build and smoke-test `margin.exe` only
- `--version 0.1.5` — override the installer version string

## Code signing (optional)

`desktop/build_windows.py` automatically signs both `margin.exe` and `margin-setup-<version>.exe`
with `signtool.exe` (SHA-256 + DigiCert RFC 3161 timestamp) when either of these is configured:

- **PFX certificate file:** set `WINDOWS_CERT_PFX_PATH` and `WINDOWS_CERT_PASSWORD`
- **Windows certificate store:** set `WINDOWS_CERT_SHA1` (thumbprint)

### In GitHub Actions (`.github/workflows/release.yml`)

Add these two repository secrets (**Settings → Secrets and variables → Actions**):

- `WINDOWS_CERT_BASE64` — base64-encoded `.pfx` file (`[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))`)
- `WINDOWS_CERT_PASSWORD` — password for the `.pfx` file

If those secrets are not set, the release workflow still builds and publishes the installer
(unsigned) along with its `.sha256` checksum.

### Free signing options for open-source projects

- **SignPath Foundation:** Free Authenticode signing for qualifying MIT open-source repositories.
- **Microsoft Store:** Free individual developer registration (no credit card); Store MSIX packages
  are signed by Microsoft automatically with zero SmartScreen warning.
