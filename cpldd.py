#!/usr/bin/env python3
"""
cpldd - Portable Windows DLL deployment helper.

Originally created by Harsh Kumar Narula.
Modernized for Python 3.12+ and WinDev.

The tool uses the active `ldd` and, optionally, `windeployqt` from the
current environment. It copies the input executable and its non-system
DLL dependencies into a deployment directory.

Typical usage:

    cpldd myapp.exe
    cpldd myapp.exe deploy

    cpldd myapp.exe --force
    cpldd myapp.exe --no-qt
    cpldd myapp.exe --verbose
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Dependency:
    """One dependency reported by ldd."""

    name: str
    raw_path: str | None
    windows_path: Path | None
    status: str


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

def strike(text: str) -> str:
    """Return text with a Unicode strike-through overlay."""
    return "".join(f"{char}\u0336" for char in text)


def info(message: str = "") -> None:
    print(message)


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(f" {title}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Path conversion
# ---------------------------------------------------------------------------

def cygpath_to_windows(path: str) -> Path | None:
    """
    Convert an MSYS/Cygwin path to a native Windows path.

    Supports paths such as:
        /cygdrive/c/foo/bar.dll
        /c/foo/bar.dll

    `cygpath -m` is used when available because it handles the active
    MSYS/Cygwin environment correctly.
    """
    path = path.strip()

    if not path or path in {"?", "??"}:
        return None

    # Already a native Windows path.
    if re.match(r"^[A-Za-z]:[\\/]", path):
        return Path(path)

    cygpath = shutil.which("cygpath")
    if cygpath:
        try:
            result = subprocess.run(
                [cygpath, "-m", path],
                capture_output=True,
                text=True,
                check=True,
            )
            converted = result.stdout.strip()
            if converted:
                return Path(converted)
        except (OSError, subprocess.SubprocessError):
            pass

    # Fallback for common MSYS/Cygwin formats.
    match = re.match(r"^/cygdrive/([A-Za-z])/(.*)$", path)
    if match:
        return Path(f"{match.group(1).upper()}:/{match.group(2)}")

    match = re.match(r"^/([A-Za-z])/(.*)$", path)
    if match:
        return Path(f"{match.group(1).upper()}:/{match.group(2)}")

    return None


# ---------------------------------------------------------------------------
# ldd handling
# ---------------------------------------------------------------------------

_LDD_RE = re.compile(
    r"^\s*(?P<name>\S+)\s*=>\s*(?P<path>.+?)\s+\([0-9A-Fa-fx]+\)\s*$"
)


def run_ldd(executable: Path) -> str:
    """Run ldd against an executable and return its stdout/stderr."""
    ldd = shutil.which("ldd")

    if not ldd:
        raise RuntimeError(
            "ldd was not found on PATH. Load the MSYS2/WinDev environment "
            "that provides ldd before running cpldd."
        )

    try:
        result = subprocess.run(
            [ldd, str(executable)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise RuntimeError(f"Unable to execute ldd: {exc}") from exc

    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    if not output.strip():
        raise RuntimeError("ldd returned no dependency information.")

    return output


def parse_ldd_output(output: str) -> list[Dependency]:
    """
    Parse common MSYS/Cygwin ldd output.

    Examples handled:

        libgomp-1.dll => /c/foo/libgomp-1.dll (0x...)
        KERNEL32.dll => /cygdrive/c/Windows/System32/KERNEL32.dll (0x...)
        foo.dll => not found
        foo.dll => /path/foo.dll (0x...)
    """
    dependencies: list[Dependency] = []
    seen: set[tuple[str, str | None]] = set()

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        match = _LDD_RE.match(line)

        if not match:
            # Keep useful "not found" diagnostics.
            if "=>" in line:
                name, _, rhs = line.partition("=>")
                name = name.strip()
                rhs = rhs.strip()

                key = (name, None)
                if key not in seen:
                    dependencies.append(
                        Dependency(
                            name=name,
                            raw_path=None,
                            windows_path=None,
                            status="not found",
                        )
                    )
                    seen.add(key)
            continue

        name = match.group("name")
        raw_path = match.group("path").strip()

        if raw_path.lower() == "not found":
            key = (name, None)
            if key not in seen:
                dependencies.append(
                    Dependency(
                        name=name,
                        raw_path=None,
                        windows_path=None,
                        status="not found",
                    )
                )
                seen.add(key)
            continue

        windows_path = cygpath_to_windows(raw_path)

        key = (name.lower(), str(windows_path).lower() if windows_path else raw_path)
        if key in seen:
            continue

        dependencies.append(
            Dependency(
                name=name,
                raw_path=raw_path,
                windows_path=windows_path,
                status="resolved" if windows_path else "unresolved",
            )
        )
        seen.add(key)

    return dependencies


# ---------------------------------------------------------------------------
# System DLL classification
# ---------------------------------------------------------------------------

def is_system_dll(path: Path) -> bool:
    """
    Determine whether a dependency belongs to Windows system locations.

    System32 and SysWOW64 are skipped by default.
    """
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))

    system_dirs = [
        windows / "System32",
        windows / "SysWOW64",
        windows / "WinSxS",
    ]

    try:
        resolved = resolved.resolve()
    except OSError:
        pass

    resolved_str = str(resolved).casefold()

    for system_dir in system_dirs:
        try:
            root = str(system_dir.resolve()).casefold()
        except OSError:
            root = str(system_dir.absolute()).casefold()

        if resolved_str == root or resolved_str.startswith(root + os.sep):
            return True

    return False


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def copy_file(
    source: Path,
    destination_dir: Path,
    *,
    label: str,
    verbose: bool = False,
) -> Path:
    """Copy a file while preserving metadata and report the operation."""
    if not source.is_file():
        raise FileNotFoundError(f"Dependency does not exist: {source}")

    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name

    if destination.exists():
        try:
            if source.resolve() == destination.resolve():
                if verbose:
                    info(f"Already in deployment directory: {source}")
                return destination
        except OSError:
            pass

        # Do not silently overwrite a different file.
        if source.stat().st_size == destination.stat().st_size:
            if verbose:
                info(f"Already present: {destination.name}")
            return destination

        raise FileExistsError(
            f"Destination already contains a different file: {destination}"
        )

    shutil.copy2(source, destination)
    info(f"{label}: {source}")
    return destination


# ---------------------------------------------------------------------------
# Qt deployment
# ---------------------------------------------------------------------------

def run_windeployqt(executable: Path, output_dir: Path, verbose: bool) -> bool:
    """Run windeployqt if available. Return True when it ran successfully."""
    windeployqt = shutil.which("windeployqt.exe") or shutil.which("windeployqt")

    if not windeployqt:
        info("windeployqt not found. Qt deployment skipped.")
        return False

    command = [
        windeployqt,
        "--release",
        str(output_dir),
        str(executable),
    ]

    if verbose:
        info("Running: " + subprocess.list2cmdline(command))

    try:
        result = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        info(f"Unable to execute windeployqt: {exc}")
        return False

    if result.returncode != 0:
        info(f"windeployqt failed with exit code {result.returncode}.")
        return False

    info("Qt deployment completed.")
    return True


# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------

def deploy(
    executable: Path,
    output_dir: Path,
    *,
    force_system: bool,
    no_qt: bool,
    verbose: bool,
) -> int:
    executable = executable.resolve()
    output_dir = output_dir.resolve()

    if not executable.is_file():
        print(f"ERROR: executable not found: {executable}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)

    section("Copying Executable")
    copied_exe = copy_file(
        executable,
        output_dir,
        label="Copied executable",
        verbose=verbose,
    )
    info(f"Destination: {copied_exe}")

    section("Searching Dependencies")

    try:
        raw_ldd = run_ldd(executable)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    dependencies = parse_ldd_output(raw_ldd)

    info(f"Total dependencies found: {len(dependencies)}")

    copied = 0
    skipped_system = 0
    missing = 0
    unresolved = 0

    for index, dep in enumerate(dependencies, start=1):
        progress = f"[{index}/{len(dependencies)}]"

        if dep.status == "not found":
            missing += 1
            info(f"{progress} NOT FOUND: {dep.name}")
            continue

        if dep.windows_path is None:
            unresolved += 1
            info(f"{progress} UNRESOLVED: {dep.name} -> {dep.raw_path}")
            continue

        dll = dep.windows_path

        if not dll.is_file():
            missing += 1
            info(f"{progress} MISSING: {dll}")
            continue

        if not force_system and is_system_dll(dll):
            skipped_system += 1
            info(f"{progress} System DLL ignored: {strike(str(dll))}")
            continue

        try:
            copy_file(
                dll,
                output_dir,
                label=f"{progress} Copied DLL",
                verbose=verbose,
            )
            copied += 1
        except (OSError, shutil.Error) as exc:
            info(f"{progress} COPY FAILED: {dll} ({exc})")

    section("Dependency Summary")
    info(f"Non-system DLLs copied : {copied}")
    info(f"System DLLs skipped    : {skipped_system}")
    info(f"Missing dependencies   : {missing}")
    info(f"Unresolved dependencies: {unresolved}")

    if not no_qt:
        section("Searching For Qt Dependencies")
        run_windeployqt(executable, output_dir, verbose)

    section("Deployment Finished")
    info(f"Executable : {executable}")
    info(f"Output     : {output_dir}")

    # Missing dependencies are useful diagnostics and should produce a
    # non-zero status, while unresolved parser lines alone do not necessarily
    # mean the executable cannot run.
    if missing:
        return 4

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cpldd",
        description="Copy Windows DLL dependencies reported by ldd.",
    )

    parser.add_argument(
        "inputexe",
        type=Path,
        help="Input Windows executable.",
    )

    parser.add_argument(
        "outputfolder",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "Deployment/output directory. "
            "Defaults to the executable name without extension."
        ),
    )

    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        dest="force_system",
        help="Also copy Windows System32/SysWOW64 DLLs.",
    )

    parser.add_argument(
        "--no-qt",
        action="store_true",
        help="Do not run windeployqt.",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show additional diagnostic information.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_exe = args.inputexe
    output_dir = args.outputfolder

    # Default: MyApplication.exe -> MyApplication/
    if output_dir is None:
        output_dir = input_exe.with_suffix("")

    info()
    info("============================================================")
    info("  cpldd :: Windows DLL Deployment Helper")
    info("============================================================")
    info(f"  Executable : {input_exe}")
    info(f"  Output     : {output_dir}")
    info(f"  Force system DLLs : {'yes' if args.force_system else 'no'}")
    info()

    return deploy(
        input_exe,
        output_dir,
        force_system=args.force_system,
        no_qt=args.no_qt,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    raise SystemExit(main())
