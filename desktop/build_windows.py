"""Build the standalone margin Windows desktop app and Inno Setup installer (.exe).

Usage::

    uv run python desktop/build_windows.py                 # full build + smoke test + installer
    uv run python desktop/build_windows.py --skip-ui       # reuse existing ui/dist
    uv run python desktop/build_windows.py --skip-installer # build + smoke-test margin.exe only

Outputs:
- ``build/desktop/dist/margin/margin.exe`` — standalone bundled app folder
- ``build/desktop/installer/margin-setup-<version>.exe`` — Inno Setup installer
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

TIMESTAMP_URL = "http://timestamp.digicert.com"

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
UI = ROOT / "ui"
BUILD_ROOT = ROOT / "build" / "desktop"
BUILD_VENV = BUILD_ROOT / "venv"
WORK_DIR = BUILD_ROOT / "work"
DIST_DIR = BUILD_ROOT / "dist"
INSTALLER_DIR = BUILD_ROOT / "installer"
ICON_PATH = DESKTOP / "assets" / "margin.ico"

WORKSPACE_PACKAGES = (
    ROOT / "packages" / "core",
    ROOT / "packages" / "api",
    ROOT / "packages" / "cli",
    ROOT / "agents" / "data_storyteller",
    ROOT / "agents" / "ai_code_detector",
    ROOT / "agents" / "commit_graph",
    ROOT / "agents" / "secret_leaks",
)

DESKTOP_DEPS = (
    "pywebview>=5.3",
    "pyinstaller>=6.11",
)


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, text=True, cwd=cwd, env=env)


def read_app_version() -> str:
    data = tomllib.loads((ROOT / "packages" / "api" / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def find_iscc() -> Path | None:
    on_path = shutil.which("ISCC") or shutil.which("iscc")
    if on_path:
        return Path(on_path)
    pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [
        pf86 / "Inno Setup 6" / "ISCC.exe",
        pf / "Inno Setup 6" / "ISCC.exe",
        local / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_icon() -> None:
    from make_icon import write_ico

    write_ico(ICON_PATH)
    print(f"Generated icon: {ICON_PATH.relative_to(ROOT)}")


def build_ui() -> None:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    env = {**os.environ, "VITE_API_URL": ""}
    if not (UI / "node_modules").is_dir():
        run([npm, "install"], cwd=UI, env=env)
    run([npm, "run", "build"], cwd=UI, env=env)


def prepare_build_venv() -> Path:
    python = BUILD_VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        BUILD_ROOT.mkdir(parents=True, exist_ok=True)
        run(["uv", "venv", str(BUILD_VENV), "--python", "3.12"], cwd=ROOT)
    # Install workspace packages non-editably so their dist-info & entry_points copy cleanly.
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--reinstall-package",
            "margin-core",
            "--reinstall-package",
            "margin-api",
            "--reinstall-package",
            "margin-cli",
            "--reinstall-package",
            "margin-data-storyteller",
            "--reinstall-package",
            "margin-ai-code-detector",
            "--reinstall-package",
            "margin-commit-graph",
            "--reinstall-package",
            "margin-secret-leaks",
            *map(str, WORKSPACE_PACKAGES),
            *DESKTOP_DEPS,
        ],
        cwd=ROOT,
    )
    return python


def build_pyinstaller(python: Path) -> Path:
    shutil.rmtree(DIST_DIR / "margin", ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    run(
        [
            str(python),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--workpath",
            str(WORK_DIR),
            "--distpath",
            str(DIST_DIR),
            str(DESKTOP / "margin.spec"),
        ],
        cwd=ROOT,
    )
    exe = DIST_DIR / "margin" / "margin.exe"
    if not exe.is_file():
        raise RuntimeError(f"Expected bundled executable at {exe}")
    return exe


def smoke_test_exe(exe: Path) -> None:
    print(f"Smoke testing {exe.relative_to(ROOT)} ...")
    out_file = WORK_DIR / "smoke-test.txt"
    out_file.unlink(missing_ok=True)
    proc = subprocess.run(
        [str(exe), "--smoke-test", "--smoke-test-out", str(out_file)],
        cwd=exe.parent,
        text=True,
        timeout=45,
    )
    if out_file.is_file():
        print(out_file.read_text(encoding="utf-8").strip())
    if proc.returncode != 0:
        raise RuntimeError(f"Smoke test failed with exit code {proc.returncode}")


def find_signtool() -> Path | None:
    on_path = shutil.which("signtool")
    if on_path:
        return Path(on_path)
    kits = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Windows Kits"
        / "10"
        / "bin"
    )
    if kits.is_dir():
        matches = sorted(kits.glob("10.*/x64/signtool.exe"), reverse=True)
        if matches:
            return matches[0]
    return None


def sign_binary(path: Path) -> bool:
    """Sign ``path`` with Authenticode when certificate env vars are configured.

    Supports either a PFX file (``WINDOWS_CERT_PFX_PATH`` + optional ``WINDOWS_CERT_PASSWORD``)
    or a certificate thumbprint in the Windows store (``WINDOWS_CERT_SHA1``).
    """
    pfx = os.environ.get("WINDOWS_CERT_PFX_PATH", "").strip()
    sha1 = os.environ.get("WINDOWS_CERT_SHA1", "").strip()
    if not pfx and not sha1:
        print(
            f"Skipping code signing for {path.name} "
            "(set WINDOWS_CERT_PFX_PATH or WINDOWS_CERT_SHA1 to sign)."
        )
        return False

    signtool = find_signtool()
    if signtool is None:
        raise RuntimeError(
            "Code signing was requested, but signtool.exe was not found. "
            "Install the Windows 10/11 SDK or add signtool.exe to PATH."
        )

    cmd = [str(signtool), "sign", "/fd", "SHA256", "/tr", TIMESTAMP_URL, "/td", "SHA256"]
    if pfx:
        cmd += ["/f", pfx]
        password = os.environ.get("WINDOWS_CERT_PASSWORD", "")
        if password:
            cmd += ["/p", password]
    else:
        cmd += ["/sha1", sha1]
    cmd.append(str(path))

    # Avoid printing the certificate password to CI logs.
    print(f"$ signtool sign /fd SHA256 ... {path.name}", flush=True)
    subprocess.run(cmd, check=True, text=True)
    return True


def write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = path.with_suffix(path.suffix + ".sha256")
    checksum.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    print(f"Wrote checksum: {checksum.name} ({digest[:12]}...)")
    return checksum


def build_installer(version: str) -> Path | None:
    iscc = find_iscc()
    if iscc is None:
        print(
            "\nInno Setup (ISCC.exe) was not found. The standalone app is ready at:\n"
            f"  {DIST_DIR / 'margin' / 'margin.exe'}\n\n"
            "To compile the Windows installer (.exe), install Inno Setup 6:\n"
            "  winget install JRSoftware.InnoSetup\n"
            "then re-run:\n"
            "  uv run python desktop/build_windows.py --skip-ui\n"
        )
        return None
    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
    run(
        [
            str(iscc),
            f"/DMyAppVersion={version}",
            f"/DSourceDir={DIST_DIR / 'margin'}",
            f"/DOutputDir={INSTALLER_DIR}",
            str(DESKTOP / "margin.iss"),
        ],
        cwd=DESKTOP,
    )
    installer = INSTALLER_DIR / f"margin-setup-{version}.exe"
    sign_binary(installer)
    write_sha256(installer)
    print(f"\nBuilt Windows installer: {installer}")
    return installer


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "win32":
        print("desktop/build_windows.py must be run on Windows.", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--skip-ui",
        action="store_true",
        help="Reuse the UI already built in ui/dist.",
    )
    parser.add_argument(
        "--skip-installer",
        action="store_true",
        help="Build and smoke-test margin.exe without running Inno Setup.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Override installer version (defaults to packages/api/pyproject.toml version).",
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(DESKTOP))
    version = str(args.version).lstrip("vV") if args.version else read_app_version()
    print(f"Building margin desktop {version} for Windows...")

    build_icon()
    if not args.skip_ui:
        build_ui()
    python = prepare_build_venv()
    exe = build_pyinstaller(python)
    smoke_test_exe(exe)
    sign_binary(exe)
    if not args.skip_installer:
        build_installer(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
