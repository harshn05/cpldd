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
    cpldd myapp.exe --force-qt --windeployqt-arg=--qmldir=qml
    cpldd myapp.exe --verbose

Exit codes:
    0   Success.
    2   Input executable not found.
    3   ldd failed or reported no dependencies.
    4   One or more dependencies were missing.
    5   A file copy failed.
    6   Invalid or unusable output directory.
    7   windeployqt was found but Qt deployment failed.
    8   Unresolved dependencies found while --strict was enabled.
    64  Command-line usage error.

When several problems occur, all of them are listed at the end of the run
and the exit code of the first one (in the order above) is returned.
"""

from __future__ import annotations

import argparse
import enum
import filecmp
import functools
import ntpath
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class ExitCode(enum.IntEnum):
    """Process exit codes (see the module docstring)."""

    OK = 0
    EXE_NOT_FOUND = 2
    LDD_FAILED = 3
    MISSING_DEPS = 4
    COPY_FAILED = 5
    BAD_OUTPUT_DIR = 6
    QT_FAILED = 7
    UNRESOLVED = 8
    USAGE = 64


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

def configure_console() -> None:
    """
    Make console output robust against unencodable characters.

    When stdout/stderr are redirected on Windows they use the locale code
    page (e.g. cp1252), which cannot encode every character in a path.
    Replace such characters instead of crashing mid-deployment.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


def _stdout_can_encode(text: str) -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def strike(text: str) -> str:
    """
    Return text with a Unicode strike-through overlay.

    Falls back to the plain text when the output encoding cannot represent
    the combining character (legacy code pages when output is redirected).
    """
    if not _stdout_can_encode("\u0336"):
        return text
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


def _fallback_windows_path(path: str) -> Path | None:
    """Convert common MSYS/Cygwin drive-letter paths without cygpath."""
    match = _CYGDRIVE_RE.match(path)
    if match:
        return Path(f"{match.group(1).upper()}:/{match.group(2)}")

    match = _MSYS_DRIVE_RE.match(path)
    if match:
        return Path(f"{match.group(1).upper()}:/{match.group(2)}")

    return None


def _cygpath_batch(paths: list[str]) -> list[str | None]:
    """Convert many MSYS/Cygwin paths with one cygpath process.

    Uses UTF-8 explicitly and preserves input order. Returns one None per
    input if cygpath is unavailable, fails, or produces ambiguous output.
    """
    if not paths:
        return []

    failed: list[str | None] = [None] * len(paths)

    # -f consumes newline-delimited input, so embedded newlines are ambiguous.
    if any("\n" in path or "\r" in path for path in paths):
        return failed

    cygpath = shutil.which("cygpath")
    if not cygpath:
        return failed

    try:
        result = subprocess.run(
            [cygpath, "-C", "UTF8", "-m", "-f", "-"],
            input="\n".join(paths) + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=True,
            timeout=30,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return failed

    # Do not strip: whitespace may be part of a valid path component.
    lines = result.stdout.splitlines()
    if len(lines) != len(paths):
        return failed

    return [line if line else None for line in lines]


def convert_paths(paths: Iterable[str]) -> dict[str, Path | None]:
    """
    Convert MSYS/Cygwin paths to native Windows paths.

    Supports paths such as ``/cygdrive/c/foo/bar.dll`` and ``/c/foo/bar.dll``.
    ``cygpath`` is used when available (one process for the whole batch)
    because it handles the active MSYS/Cygwin environment correctly; the
    drive-letter regexes are only a fallback.

    The result maps each (whitespace-stripped) input path to its Windows
    path, or ``None`` if it could not be converted.
    """
    result: dict[str, Path | None] = {}
    pending: list[str] = []

    for raw in dict.fromkeys(p.strip() for p in paths):
        if not raw or raw in {"?", "??"}:
            result[raw] = None
        elif _WINDOWS_DRIVE_RE.match(raw):
            # Already a native Windows path.
            result[raw] = Path(raw)
        else:
            pending.append(raw)

    if pending:
        for raw, converted in zip(pending, _cygpath_batch(pending)):
            if converted:
                result[raw] = Path(converted)
            else:
                result[raw] = _fallback_windows_path(raw)

    return result


def cygpath_to_windows(path: str) -> Path | None:
    """Convert a single MSYS/Cygwin path to a native Windows path."""
    return convert_paths([path]).get(path.strip())


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
# Only a real hexadecimal base address is stripped, never e.g. "(1)".
_LDD_BASE_ADDR_RE = re.compile(r"\s*\(0x[0-9A-Fa-f]+\)\s*$")


def run_ldd(executable: Path, *, verbose: bool = False) -> str:
    """
    Run ldd against an executable and return its stdout/stderr.

    MSYS2/Cygwin ldd commonly exits non-zero *with valid output* when one
    dependency is "not found". We treat usable output as success and let
    the caller decide what to do via the parsed dependency list. Only an
    empty result is a hard failure here; output that parses to zero
    dependencies is rejected by the caller.
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

    if result.returncode != 0 and verbose:
        # Non-zero exit with usable output is expected when dependencies
        # are missing; do not abort the deployment over it.
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
    # Pass 1: split the text into (name, raw_path | None) entries.
    entries: list[tuple[str, str | None]] = []

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
            entries.append((name, None))
            continue

        # Strip an optional trailing base-address "(0x...)" segment.
        raw_path = _LDD_BASE_ADDR_RE.sub("", rest).strip()

        if not raw_path or raw_path.lower() == "not found":
            entries.append((name, None))
        else:
            entries.append((name, raw_path))

    # Pass 2: convert every path in one batch.
    converted = convert_paths(raw for _, raw in entries if raw is not None)

    # Pass 3: build the de-duplicated dependency list, preserving order.
    dependencies: list[Dependency] = []
    seen: set[tuple[str, str | None]] = set()

    for name, raw_path in entries:
        if raw_path is None:
            key = (name.lower(), None)
            if key not in seen:
                dependencies.append(_make_not_found(name))
                seen.add(key)
            continue

        windows_path = converted.get(raw_path)

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


@functools.cache
def _system_roots() -> tuple[str, ...]:
    """
    Return the normalized Windows system directories to skip.

    Computed once and cached, since resolving these per dependency is
    needlessly expensive for large dependency lists. Tests can reset the
    cache with ``_system_roots.cache_clear()``.
    """
    windir = os.environ.get("WINDIR")
    if not windir:
        # Only fall back to the conventional location on Windows.
        if os.name != "nt":
            return ()
        windir = r"C:\Windows"

    roots: list[str] = []
    for name in ("System32", "SysWOW64", "WinSxS"):
        candidate = ntpath.join(windir, name)
        if os.name == "nt":
            # Follow junctions/symlinks so comparisons use real locations.
            try:
                candidate = os.path.realpath(candidate)
            except OSError:
                pass
        roots.append(_normcase_normpath(candidate))

    return tuple(roots)


def is_system_dll(path: Path) -> bool:
    """
    Determine whether a dependency belongs to Windows system locations.

    System32, SysWOW64, and WinSxS are skipped by default.
    """
    resolved: Path | str = path
    if os.name == "nt":
        try:
            resolved = path.resolve()
        except OSError:
            pass

    # _normcase_normpath always yields backslash-separated paths.
    resolved_str = _normcase_normpath(resolved)

    for root in _system_roots():
        if resolved_str == root or resolved_str.startswith(root + "\\"):
            return True

    return False


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def _files_equal(a: Path, b: Path) -> bool:
    """Return True if both files exist and have identical contents."""
    try:
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _make_writable(path: Path) -> None:
    """Clear the read-only attribute so the file can be overwritten."""
    try:
        path.chmod(path.stat().st_mode | stat.S_IWRITE)
    except OSError:
        pass


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
        _make_writable(destination)

    shutil.copy2(source, destination)
    info(f"{label}: {source}")
    return CopyResult.COPIED


# ---------------------------------------------------------------------------
# Qt deployment
# ---------------------------------------------------------------------------

# Qt5Core.dll, Qt6Core.dll, Qt6Cored.dll, QtCore4.dll, libQt5Core.dll, ...
_QT_CORE_RE = re.compile(
    r"^(?:lib)?Qt\d*Core[A-Za-z]*\d*\.dll$",
    re.IGNORECASE,
)


def uses_qt(dependencies: Iterable[Dependency]) -> bool:
    """Return True if any reported dependency is a Qt Core library."""
    return any(_QT_CORE_RE.match(dep.name) for dep in dependencies)


def run_windeployqt(
    executable: Path,
    output_dir: Path,
    verbose: bool,
    extra_args: Sequence[str] = (),
) -> QtDeployResult:
    """
    Run windeployqt on the executable supplied by the caller.

    A missing tool is an optional skip. If the tool exists but fails,
    return FAILED so the overall deployment can report a non-zero status.

    No ``--release``/``--debug`` flag is passed: windeployqt detects the
    build type from the executable. Use ``extra_args`` to override.
    """
    windeployqt = shutil.which("windeployqt.exe") or shutil.which("windeployqt")

    if not windeployqt:
        info("windeployqt not found. Qt deployment skipped.")
        return QtDeployResult.SKIPPED

    # windeployqt expects the executable as a positional argument and the
    # output directory via --dir.
    command = [
        windeployqt,
        "--dir",
        str(output_dir),
        *extra_args,
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
    force_qt: bool = False,
    qt_args: Sequence[str] = (),
) -> int:
    executable = executable.resolve()
    output_dir = output_dir.resolve()

    if not executable.is_file():
        warn(f"ERROR: executable not found: {executable}")
        return ExitCode.EXE_NOT_FOUND

    if output_dir == executable.parent:
        warn(
            "ERROR: output directory resolves to the input directory. "
            "Choose a distinct output folder."
        )
        return ExitCode.BAD_OUTPUT_DIR

    # Discover dependencies first so a failed scan leaves no half-made
    # output directory behind.
    section("Searching Dependencies")

    try:
        raw_ldd = run_ldd(executable, verbose=verbose)
    except RuntimeError as exc:
        warn(f"ERROR: {exc}")
        return ExitCode.LDD_FAILED

    dependencies = parse_ldd_output(raw_ldd, verbose=verbose)

    if not dependencies:
        # Every Windows executable has at least one dependency, so an
        # empty list means ldd failed (wrong file type, unreadable file...).
        warn("ERROR: ldd reported no dependencies. Its output was:")
        for line in raw_ldd.strip().splitlines()[:10]:
            warn(f"  {line}")
        return ExitCode.LDD_FAILED

    info(f"Total dependencies found: {len(dependencies)}")

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        warn(f"ERROR: cannot create output directory {output_dir}: {exc}")
        return ExitCode.BAD_OUTPUT_DIR

    section("Copying Executable")
    try:
        # The executable is always refreshed: after a rebuild it differs
        # from the previously deployed copy, which is expected.
        copy_file(
            executable,
            output_dir,
            label="Copied executable",
            verbose=verbose,
            overwrite=True,
        )
    except (OSError, shutil.Error) as exc:
        warn(f"ERROR: failed to copy executable: {exc}")
        return ExitCode.COPY_FAILED
    info(f"Destination: {output_dir / executable.name}")

    section("Copying Dependencies")

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
                    f"{progress} DLL NAME COLLISION: {dll.name}\n"
                    f"    First source : {previous_source}\n"
                    f"    Second source: {dll}\n"
                    "    Both files cannot safely occupy the same flat "
                    "deployment directory. Resolve this conflict manually."
                )
                continue

        # Record the claim before copying so that a failed copy still
        # blocks a later, different DLL with the same name.
        basename_sources[basename_key] = dll

        try:
            result = copy_file(
                dll,
                output_dir,
                label=f"{progress} Copied DLL",
                verbose=verbose,
                overwrite=overwrite,
            )
            if result is CopyResult.COPIED:
                copied += 1
            else:
                # ALREADY_PRESENT or SAME_FILE: nothing to do.
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
    if no_qt:
        pass
    elif force_qt or uses_qt(dependencies):
        section("Searching For Qt Dependencies")
        deployed_executable = output_dir / executable.name
        qt_result = run_windeployqt(
            deployed_executable,
            output_dir,
            verbose,
            qt_args,
        )
    else:
        info()
        info(
            "No Qt libraries detected; windeployqt skipped "
            "(use --force-qt to run it anyway)."
        )

    section("Deployment Finished")
    info(f"Executable : {executable}")
    info(f"Output     : {output_dir}")

    # Collect every problem so none is hidden behind another, then return
    # the code of the first one. Missing dependencies are useful
    # diagnostics and produce a non-zero status, while unresolved parser
    # lines alone do not (unless --strict is given).
    problems: list[tuple[ExitCode, str]] = []
    if missing:
        problems.append(
            (ExitCode.MISSING_DEPS, f"{missing} missing dependency(ies)")
        )
    if copy_failures:
        problems.append(
            (ExitCode.COPY_FAILED, f"{copy_failures} copy failure(s)")
        )
    if qt_result is QtDeployResult.FAILED:
        problems.append((ExitCode.QT_FAILED, "windeployqt failed"))
    if strict and unresolved:
        problems.append(
            (ExitCode.UNRESOLVED, f"{unresolved} unresolved dependency(ies)")
        )

    if problems:
        info()
        warn("Problems:")
        for code, text in problems:
            warn(f"  [{int(code)}] {text}")
        return problems[0][0]

    return ExitCode.OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose usage errors do not collide with exit code 2."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(int(ExitCode.USAGE), f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
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
        help=(
            "Overwrite existing destination DLLs with different contents. "
            "(The executable itself is always refreshed.)"
        ),
    )

    parser.add_argument(
        "--no-qt",
        action="store_true",
        help="Do not run windeployqt.",
    )

    parser.add_argument(
        "--force-qt",
        action="store_true",
        help=(
            "Run windeployqt even if no Qt library is among the "
            "dependencies (e.g. Qt loaded dynamically)."
        ),
    )

    parser.add_argument(
        "--windeployqt-arg",
        action="append",
        default=None,
        dest="qt_args",
        metavar="ARG",
        help=(
            "Extra argument passed to windeployqt; repeat as needed. "
            "Use the '=' form for values starting with '-', e.g. "
            "--windeployqt-arg=--debug."
        ),
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
    configure_console()

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

    return int(
        deploy(
            input_exe,
            output_dir,
            force_system=args.force_system,
            no_qt=args.no_qt,
            verbose=args.verbose,
            overwrite=args.overwrite,
            strict=args.strict,
            force_qt=args.force_qt,
            qt_args=args.qt_args or [],
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
