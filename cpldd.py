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

    cpldd myapp.exe --force-system-dlls
    cpldd myapp.exe --force-overwrite
    cpldd myapp.exe --no-qt
    cpldd myapp.exe --verbose

Exit codes:
    0  Success.
    2  Input executable not found.
    3  ldd failed or produced no usable output.
    4  One or more dependencies were missing.
    5  A file copy failed.
    6  Invalid output directory (e.g. resolves to the input directory).
    7  windeployqt was found but Qt deployment failed.
    8  Unresolved dependencies found while --strict was enabled.
"""

from __future__ import annotations

import argparse
import enum
import hashlib
import ntpath
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

class DepStatus(str, enum.Enum):
    """Classification of a single ldd-reported dependency."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    NOT_FOUND = "not found"


@dataclass(frozen=True)
class Dependency:
    """One dependency reported by ldd."""

    name: str
    raw_path: str | None
    windows_path: Path | None
    status: DepStatus


class CopyResult(enum.Enum):
    """Outcome of a copy_file() call."""

    COPIED = "copied"
    ALREADY_PRESENT = "already_present"
    SAME_FILE = "same_file"


class QtDeployResult(enum.Enum):
    """Outcome of an optional windeployqt invocation."""

    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

def strike(text: str) -> str:
    """Return text with a Unicode strike-through overlay."""
    return "".join(f"{char}\u0336" for char in text)


def info(message: str = "") -> None:
    print(message)


def warn(message: str) -> None:
    print(message, file=sys.stderr)


def section(title: str) -> None:
    print()
    print("=" * 60)
    print(f" {title}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Path conversion
# ---------------------------------------------------------------------------

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_CYGDRIVE_RE = re.compile(r"^/cygdrive/([A-Za-z])/(.*)$")
_MSYS_DRIVE_RE = re.compile(r"^/([A-Za-z])/(.*)$")


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
    if _WINDOWS_DRIVE_RE.match(path):
        return Path(path)

    cygpath = shutil.which("cygpath")
    if cygpath:
        try:
            result = subprocess.run(
                [cygpath, "-m", path],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            converted = result.stdout.strip()
            if converted:
                return Path(converted)
        except (OSError, subprocess.SubprocessError):
            pass

    # Fallback for common MSYS/Cygwin formats.
    match = _CYGDRIVE_RE.match(path)
    if match:
        return Path(f"{match.group(1).upper()}:/{match.group(2)}")

    match = _MSYS_DRIVE_RE.match(path)
    if match:
        return Path(f"{match.group(1).upper()}:/{match.group(2)}")

    return None


# ---------------------------------------------------------------------------
# ldd handling
# ---------------------------------------------------------------------------

# Tolerant regex: the trailing "(0x...)" segment is optional, and the
# path may contain spaces. We split on " => " rather than trying to
# capture everything with a single rigid pattern.
_LDD_LINE_RE = re.compile(
    r"^\s*(?P<name>\S+)\s+=>\s+(?P<rest>.+?)\s*$"
)
# Lines that carry a base address but no "=>": treat as informational only.
_LDD_BARE_ADDR_RE = re.compile(r"^\s*\S+\s+\(0x[0-9A-Fa-f]+\)\s*$")
_LDD_BASE_ADDR_RE = re.compile(r"\s*\([0-9A-Fa-fx]+\)\s*$")


def run_ldd(executable: Path, *, verbose: bool = False) -> str:
    """
    Run ldd against an executable and return its stdout/stderr.

    MSYS2/Cygwin ldd commonly exits non-zero *with valid output* when one
    dependency is "not found". We treat usable output as success and let
    the caller decide what to do via the parsed dependency list. Only an
    empty result is a hard failure.
    """
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
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ldd timed out after {exc.timeout}s.") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to execute ldd: {exc}") from exc

    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    if not output.strip():
        raise RuntimeError(
            f"ldd returned no dependency information "
            f"(exit code {result.returncode})."
        )

    if result.returncode != 0:
        # Non-zero exit with usable output is expected when dependencies
        # are missing; do not abort the deployment over it.
        if verbose:
            warn(
                f"  [ldd] exited with code {result.returncode}; "
                f"parsing output anyway."
            )

    return output


def _make_not_found(name: str) -> Dependency:
    return Dependency(
        name=name,
        raw_path=None,
        windows_path=None,
        status=DepStatus.NOT_FOUND,
    )


def parse_ldd_output(
    output: str,
    *,
    verbose: bool = False,
) -> list[Dependency]:
    """
    Parse common MSYS/Cygwin ldd output.

    Examples handled:

        libgomp-1.dll => /c/foo/libgomp-1.dll (0x...)
        KERNEL32.dll => /cygdrive/c/Windows/System32/KERNEL32.dll (0x...)
        foo.dll => not found
        foo.dll => /path/foo.dll (0x...)
        foo.dll => /path/foo.dll

    Only lines containing "=>" yield dependencies. Bare base-address lines
    (e.g. the main executable's own entry on some ldd variants) are
    informational and are reported only under ``verbose``.
    """
    dependencies: list[Dependency] = []
    seen: set[tuple[str, str | None]] = set()

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        match = _LDD_LINE_RE.match(line)

        if not match:
            if verbose:
                if _LDD_BARE_ADDR_RE.match(line):
                    info(f"  [ldd] informational: {line}")
                else:
                    warn(f"  [ldd] unparsed: {line}")
            continue

        name = match.group("name")
        rest = match.group("rest").strip()

        if rest.lower() == "not found":
            key = (name.lower(), None)
            if key not in seen:
                dependencies.append(_make_not_found(name))
                seen.add(key)
            continue

        # Strip an optional trailing base-address "(0x...)" segment.
        raw_path = _LDD_BASE_ADDR_RE.sub("", rest).strip()

        if not raw_path or raw_path.lower() == "not found":
            key = (name.lower(), None)
            if key not in seen:
                dependencies.append(_make_not_found(name))
                seen.add(key)
            continue

        windows_path = cygpath_to_windows(raw_path)

        key = (
            name.lower(),
            str(windows_path).lower() if windows_path else raw_path.lower(),
        )
        if key in seen:
            continue

        dependencies.append(
            Dependency(
                name=name,
                raw_path=raw_path,
                windows_path=windows_path,
                status=DepStatus.RESOLVED if windows_path else DepStatus.UNRESOLVED,
            )
        )
        seen.add(key)

    return dependencies


# ---------------------------------------------------------------------------
# System DLL classification
# ---------------------------------------------------------------------------

def _normcase_normpath(path: Path | str) -> str:
    """Normalize a Windows path independent of the host operating system."""
    return ntpath.normcase(ntpath.normpath(str(path).replace("/", "\\")))


_SYSTEM_ROOTS_CACHE: list[str] | None = None


def _system_roots() -> list[str]:
    """
    Return the normalized Windows system directories to skip.

    Computed once and cached, since resolving these per dependency is
    needlessly expensive for large dependency lists.
    """
    global _SYSTEM_ROOTS_CACHE
    if _SYSTEM_ROOTS_CACHE is not None:
        return _SYSTEM_ROOTS_CACHE

    windir = os.environ.get("WINDIR")
    if not windir:
        # Only fall back to the conventional location on Windows.
        if os.name != "nt":
            _SYSTEM_ROOTS_CACHE = []
            return _SYSTEM_ROOTS_CACHE
        windir = r"C:\Windows"

    windows = Path(windir)
    roots: list[str] = []
    for name in ("System32", "SysWOW64", "WinSxS"):
        candidate = windows / name
        try:
            roots.append(_normcase_normpath(candidate.resolve()))
        except OSError:
            roots.append(_normcase_normpath(candidate.absolute()))

    _SYSTEM_ROOTS_CACHE = roots
    return roots


def is_system_dll(path: Path) -> bool:
    """
    Determine whether a dependency belongs to Windows system locations.

    System32, SysWOW64, and WinSxS are skipped by default.
    """
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    resolved_str = _normcase_normpath(resolved)

    for root in _system_roots():
        if resolved_str == root:
            return True
        if resolved_str.startswith(root + os.sep):
            return True
        # Also accept "/" as a separator (cygpath -m can emit forward slashes).
        if resolved_str.startswith(root + "/"):
            return True

    return False


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _files_equal(a: Path, b: Path) -> bool:
    """Return True if both files exist and have identical contents."""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
    except OSError:
        return False
    return _sha256(a) == _sha256(b)


def copy_file(
    source: Path,
    destination_dir: Path,
    *,
    label: str,
    verbose: bool = False,
    overwrite: bool = False,
) -> CopyResult:
    """
    Copy a file while preserving metadata.

    Returns a ``CopyResult`` describing what happened. Raises
    ``FileNotFoundError`` if the source is missing and ``FileExistsError``
    if the destination exists with different contents and ``overwrite``
    is False.
    """
    if not source.is_file():
        raise FileNotFoundError(f"Dependency does not exist: {source}")

    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name

    if destination.exists():
        try:
            if source.resolve() == destination.resolve():
                if verbose:
                    info(f"Already in deployment directory: {source}")
                return CopyResult.SAME_FILE
        except OSError:
            pass

        if _files_equal(source, destination):
            if verbose:
                info(f"Already present (identical): {destination.name}")
            return CopyResult.ALREADY_PRESENT

        if not overwrite:
            raise FileExistsError(
                f"Destination already contains a different file: {destination} "
                f"(use --force-overwrite to replace it)"
            )
        if verbose:
            info(f"Overwriting: {destination.name}")

    shutil.copy2(source, destination)
    info(f"{label}: {source}")
    return CopyResult.COPIED


# ---------------------------------------------------------------------------
# Qt deployment
# ---------------------------------------------------------------------------

def run_windeployqt(
    executable: Path,
    output_dir: Path,
    verbose: bool,
) -> QtDeployResult:
    """
    Run windeployqt on the executable supplied by the caller.

    A missing tool is an optional skip. If the tool exists but fails,
    return FAILED so the overall deployment can report a non-zero status.
    """
    windeployqt = shutil.which("windeployqt.exe") or shutil.which("windeployqt")

    if not windeployqt:
        info("windeployqt not found. Qt deployment skipped.")
        return QtDeployResult.SKIPPED

    # windeployqt expects the executable as a positional argument and the
    # output directory via --dir.
    command = [
        windeployqt,
        "--release",
        "--dir",
        str(output_dir),
    ]

    if verbose:
        # windeployqt requires a numeric value for --verbose (e.g., --verbose 2).
        # Passing just "--verbose" causes an "Invalid value" error and exit code 1.
        command.extend(["--verbose", "2"])
        
    command.append(str(executable))

    if verbose:
        info("Running: " + subprocess.list2cmdline(command))

    try:
        result = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        warn("windeployqt timed out after 600s.")
        return QtDeployResult.FAILED
    except OSError as exc:
        warn(f"Unable to execute windeployqt: {exc}")
        return QtDeployResult.FAILED

    if result.returncode != 0:
        warn(f"windeployqt failed with exit code {result.returncode}.")
        return QtDeployResult.FAILED

    info("Qt deployment completed.")
    return QtDeployResult.SUCCESS
    
# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------

def _default_output_dir(executable: Path) -> Path:
    """
    Choose a safe default output directory.

    ``myapp.exe`` -> ``myapp_deploy/``. We append a suffix rather than
    stripping the extension so we never collide with a same-named
    extension-less file or an existing directory that the user already
    has.
    """
    return executable.with_name(executable.stem + "_deploy")


def deploy(
    executable: Path,
    output_dir: Path,
    *,
    force_system: bool,
    no_qt: bool,
    verbose: bool,
    overwrite: bool,
    strict: bool = False,
) -> int:
    executable = executable.resolve()
    output_dir = output_dir.resolve()

    if not executable.is_file():
        warn(f"ERROR: executable not found: {executable}")
        return 2

    if output_dir == executable.parent:
        warn(
            "ERROR: output directory resolves to the input directory. "
            "Choose a distinct output folder."
        )
        return 6

    output_dir.mkdir(parents=True, exist_ok=True)

    section("Copying Executable")
    try:
        copy_file(
            executable,
            output_dir,
            label="Copied executable",
            verbose=verbose,
            overwrite=overwrite,
        )
    except (OSError, shutil.Error) as exc:
        warn(f"ERROR: failed to copy executable: {exc}")
        return 5
    info(f"Destination: {output_dir / executable.name}")

    section("Searching Dependencies")

    try:
        raw_ldd = run_ldd(executable, verbose=verbose)
    except RuntimeError as exc:
        warn(f"ERROR: {exc}")
        return 3

    dependencies = parse_ldd_output(raw_ldd, verbose=verbose)

    info(f"Total dependencies found: {len(dependencies)}")

    copied = 0
    already_present = 0
    skipped_system = 0
    missing = 0
    unresolved = 0
    copy_failures = 0

    # A flat deployment directory can contain only one file per basename.
    # Track source paths so two different DLLs with the same name are never
    # silently allowed to overwrite one another, even with --force-overwrite.
    basename_sources: dict[str, Path] = {
        executable.name.casefold(): executable
    }

    for index, dep in enumerate(dependencies, start=1):
        progress = f"[{index}/{len(dependencies)}]"

        if dep.status is DepStatus.NOT_FOUND:
            missing += 1
            warn(f"{progress} NOT FOUND: {dep.name}")
            continue

        if dep.windows_path is None:
            unresolved += 1
            warn(f"{progress} UNRESOLVED: {dep.name} -> {dep.raw_path}")
            continue

        dll = dep.windows_path

        if not dll.is_file():
            missing += 1
            warn(f"{progress} MISSING: {dll}")
            continue

        if not force_system and is_system_dll(dll):
            skipped_system += 1
            # Always show system DLLs, struck through, so users can see
            # the full dependency list and what was intentionally skipped.
            info(f"{progress} System DLL (skipped): {strike(str(dll))}")
            continue

        basename_key = dll.name.casefold()
        previous_source = basename_sources.get(basename_key)
        if previous_source is not None:
            try:
                same_source = previous_source.resolve() == dll.resolve()
            except OSError:
                same_source = previous_source == dll

            if not same_source:
                copy_failures += 1
                warn(
                    f"{progress} DLL NAME COLLISION: {dll.name}\\n"
                    f"    First source : {previous_source}\\n"
                    f"    Second source: {dll}\\n"
                    "    Both files cannot safely occupy the same flat "
                    "deployment directory. Resolve this conflict manually."
                )
                continue

        try:
            result = copy_file(
                dll,
                output_dir,
                label=f"{progress} Copied DLL",
                verbose=verbose,
                overwrite=overwrite,
            )
            basename_sources[basename_key] = dll
            if result is CopyResult.COPIED:
                copied += 1
            elif result is CopyResult.ALREADY_PRESENT:
                already_present += 1
        except (OSError, shutil.Error) as exc:
            copy_failures += 1
            warn(f"{progress} COPY FAILED: {dll} ({exc})")

    section("Dependency Summary")
    info(f"Non-system DLLs copied : {copied}")
    info(f"Already present        : {already_present}")
    info(f"System DLLs skipped    : {skipped_system}")
    info(f"Missing dependencies   : {missing}")
    info(f"Unresolved dependencies: {unresolved}")
    if copy_failures:
        info(f"Copy failures          : {copy_failures}")

    qt_result = QtDeployResult.SKIPPED
    if not no_qt:
        section("Searching For Qt Dependencies")
        deployed_executable = output_dir / executable.name
        qt_result = run_windeployqt(
            deployed_executable,
            output_dir,
            verbose,
        )

    section("Deployment Finished")
    info(f"Executable : {executable}")
    info(f"Output     : {output_dir}")

    # Missing dependencies are useful diagnostics and should produce a
    # non-zero status, while unresolved parser lines alone do not
    # necessarily mean the executable cannot run.
    if missing:
        return 4
    if copy_failures:
        return 5
    if qt_result is QtDeployResult.FAILED:
        return 7
    if strict and unresolved:
        return 8

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
            "Defaults to '<exe-stem>_deploy' next to the executable."
        ),
    )

    parser.add_argument(
        "--force-system-dlls",
        action="store_true",
        dest="force_system",
        help="Also copy Windows System32/SysWOW64/WinSxS DLLs.",
    )

    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        dest="overwrite",
        help="Overwrite existing destination files with different contents.",
    )

    parser.add_argument(
        "--no-qt",
        action="store_true",
        help="Do not run windeployqt.",
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Return exit code 8 if one or more dependency paths remain "
            "unresolved."
        ),
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

    if output_dir is None:
        output_dir = _default_output_dir(input_exe)

    info()
    info("============================================================")
    info("  cpldd :: Windows DLL Deployment Helper")
    info("============================================================")
    info(f"  Executable         : {input_exe}")
    info(f"  Output             : {output_dir}")
    info(f"  Force system DLLs  : {'yes' if args.force_system else 'no'}")
    info(f"  Overwrite existing : {'yes' if args.overwrite else 'no'}")
    info(f"  Strict checking    : {'yes' if args.strict else 'no'}")
    info()

    return deploy(
        input_exe,
        output_dir,
        force_system=args.force_system,
        no_qt=args.no_qt,
        verbose=args.verbose,
        overwrite=args.overwrite,
        strict=args.strict,
    )


if __name__ == "__main__":
    raise SystemExit(main())
