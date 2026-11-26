# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller --onedir spec for the margin Windows desktop application.

Builds ``build/desktop/dist/margin/margin.exe`` with:
- the compiled React UI (ui/dist -> margin_ui/)
- every bundled margin-* package's dist-info metadata so ``importlib.metadata.entry_points``
  discovers agents identically to a regular Python install
- all agent data files (methodology/markers TOMLs, etc.), pandas, duckdb, scipy, and pywebview
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
UI_DIST = ROOT / "ui" / "dist"
ICON_PATH = ROOT / "desktop" / "assets" / "margin.ico"

if not (UI_DIST / "index.html").is_file():
    raise SystemExit(f"Built UI not found at {UI_DIST}. Run desktop/build_windows.py instead.")

datas: list[tuple[str, str]] = [
    (str(UI_DIST), "margin_ui"),
]
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    # uvicorn dynamic loaders
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "sse_starlette",
    # agent entry-point targets
    "data_storyteller.agent",
    "ai_code_detector.agent",
    "commit_graph.agent",
    "secret_leaks.agent",
]

# Copy package metadata so importlib.metadata.entry_points(group="margin.agents") works when frozen.
for dist_name in (
    "margin-core",
    "margin-api",
    "margin-cli",
    "margin-data-storyteller",
    "margin-ai-code-detector",
    "margin-commit-graph",
    "margin-secret-leaks",
):
    datas += copy_metadata(dist_name)

# Collect workspace agent packages (data files such as TOML configs + all submodules).
for pkg in (
    "margin_core",
    "margin_api",
    "data_storyteller",
    "ai_code_detector",
    "commit_graph",
    "secret_leaks",
):
    datas += collect_data_files(pkg)
    hiddenimports += collect_submodules(pkg)

# Collect native/runtime assets for pywebview (Edge WebView2 interop) and duckdb.
for pkg in ("webview", "clr_loader", "pythonnet", "duckdb"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(ROOT / "desktop" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "jupyter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="margin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON_PATH) if ICON_PATH.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="margin",
)
