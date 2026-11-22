# CPLDD

**Portable Windows DLL Deployment Helper**

CPLDD is a lightweight Windows utility for deploying Qt and non-Qt C/C++ applications with their required non-system DLL dependencies.

It analyzes dependencies reported by `ldd`, converts MSYS2/Cygwin paths into native Windows paths, and copies the input executable and its resolved non-system DLL dependencies into a deployment directory. For Qt applications, CPLDD can also invoke `windeployqt` to deploy Qt runtime libraries, plugins, and other Qt-related files.

CPLDD is written in Python and can be run with Python 3.12+ or distributed as a standalone Windows executable. The standalone release is packaged with the MSYS2 runtime tools needed for dependency discovery and path conversion.

## Features

- Deploys Qt and non-Qt Windows C/C++ applications.
- Discovers DLL dependencies through the active environment's `ldd`.
- Converts MSYS2/Cygwin paths to native Windows paths.
- Skips Windows system DLLs by default, with an option to include them.
- Copies resolved non-system DLLs and reports missing or unresolved dependencies.
- Detects DLL filename collisions and protects existing destination DLLs.
- Integrates with `windeployqt` for Qt runtime deployment.
- Supports strict checking, verbose diagnostics, and automation-friendly exit codes.

## Download

Download the latest standalone bundle from the [GitHub Releases page](https://github.com/harshn05/cpldd/releases/latest).

### Release bundle contents

The release ZIP contains exactly these four files:

```text
cpldd/
├── cpldd.exe
├── cygpath.exe
├── ldd.exe
└── msys-2.0.dll
```

| File | Purpose |
|---|---|
| `cpldd.exe` | Standalone CPLDD application built with PyInstaller. |
| `ldd.exe` | MSYS2 dependency inspection utility used to identify the executable's DLL dependencies. |
| `cygpath.exe` | MSYS2 path conversion utility used to convert MSYS paths into native Windows paths. |
| `msys-2.0.dll` | MSYS2 runtime library required by the bundled MSYS2 tools. |

Keep all four files together in the extracted release directory. Do not remove or rename the bundled runtime files.

**Important:** The bundled `ldd.exe`, `cygpath.exe`, and `msys-2.0.dll` provide the MSYS2 runtime tooling used by the release. They do not bundle every compiler runtime DLL required by every application you deploy. CPLDD still uses the active environment and its available DLL search paths to resolve application dependencies.

The optional Qt deployment tool, `windeployqt`, is not included in this ZIP. It must be available on `PATH` from the Qt environment you want to use.

## Requirements

### Running the standalone release

- Windows 10 or Windows 11.
- Extract all four files from the release ZIP into the same directory.
- Make `ldd.exe` available on `PATH`, or run CPLDD from a shell where it is discoverable. CPLDD also checks for `cygpath.exe` beside the resolved `ldd.exe`, so adding the extracted release directory to `PATH` makes both tools available cleanly.
- Make the application's compiler/runtime DLL directories available to the active environment so `ldd` can resolve them.

### Running from source

- Windows.
- Python 3.12 or newer.
- An active MSYS2/Cygwin-style environment providing `ldd`.
- `cygpath` is recommended for full path conversion support. CPLDD has a fallback for common drive-letter path formats such as `/c/...` and `/cygdrive/c/...`.

### Qt applications

For Qt deployment, `windeployqt` must be available on `PATH`. CPLDD detects Qt Core dependencies and invokes the available `windeployqt` automatically unless `--no-qt` is used.

## Installation and setup

### Option 1: Standalone executable

1. Download the latest ZIP from [GitHub Releases](https://github.com/harshn05/cpldd/releases/latest).
2. Extract all four files into a directory, for example `C:\Tools\CPLDD`.
3. Add that directory to your `PATH`, or open a shell in that directory.
4. Load the compiler/runtime environment used to build your application.
5. Run `cpldd.exe` against your executable.

Example:

```powershell
cpldd.exe MyApplication.exe
```

The release includes the MSYS2 `ldd` and `cygpath` tools and their runtime library. You do not need to install a separate Python runtime to launch the standalone `cpldd.exe`.

### Option 2: Run using Python

Clone the repository:

```powershell
git clone https://github.com/harshn05/cpldd.git
cd cpldd
```

Run:

```powershell
python cpldd.py --help
```

The main Python script uses only the Python standard library. The standalone release build uses PyInstaller and the packaging workflow uses zstandard to prepare the MSYS2 runtime bundle.

## Command-line usage

### Syntax

```text
cpldd [options] <Input_Exe_File> [Output_Folder]
```

With Python:

```powershell
python cpldd.py MyApplication.exe
```

With the standalone release:

```powershell
cpldd.exe MyApplication.exe
```

The output folder is optional. If omitted, CPLDD creates a directory next to the input executable using the executable's stem plus the `_deploy` suffix.

For example:

```text
MyApplication.exe
MyApplication_deploy/
```

To specify an output directory:

```powershell
cpldd.exe MyApplication.exe release
```

### Arguments

| Argument | Description |
|---|---|
| `<inputexe>` | Input Windows executable (required). |
| `[outputfolder]` | Optional deployment directory. Defaults to `<exe-stem>_deploy` next to the input executable. |

### Options

| Option | Description |
|---|---|
| `--force-system-dlls` | Also copy DLLs from Windows system directories. |
| `--force-overwrite` | Overwrite existing destination DLLs when their contents differ. The executable itself is always refreshed. |
| `--no-qt` | Do not run `windeployqt`. |
| `--force-qt` | Run `windeployqt` even if no Qt Core dependency is detected. |
| `--windeployqt-arg=ARG` | Pass an additional argument to `windeployqt`. Can be repeated. |
| `--strict` | Return exit code `8` if one or more dependency paths remain unresolved. |
| `-v`, `--verbose` | Show additional diagnostic information. |
| `-h`, `--help` | Display command-line help. |

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success. |
| `2` | Input executable not found. |
| `3` | `ldd` failed or reported no dependencies. |
| `4` | One or more dependencies were missing. |
| `5` | A file copy failed. |
| `6` | Invalid or unusable output directory. |
| `7` | `windeployqt` was found but Qt deployment failed. |
| `8` | Unresolved dependencies found while `--strict` was enabled. |
| `64` | Command-line usage error. |

If several problems occur, CPLDD reports all of them and returns the first applicable error code in the order shown above.

### Examples

Deploy using the default output directory:

```powershell
cpldd.exe MyApplication.exe
```

Deploy into a custom directory:

```powershell
cpldd.exe MyApplication.exe release
```

Include Windows system DLLs:

```powershell
cpldd.exe MyApplication.exe --force-system-dlls
```

Overwrite existing destination DLLs when their contents differ:

```powershell
cpldd.exe MyApplication.exe release --force-overwrite
```

Skip Qt deployment:

```powershell
cpldd.exe MyApplication.exe --no-qt
```

Force Qt deployment, for example when Qt is loaded dynamically:

```powershell
cpldd.exe MyApplication.exe --force-qt
```

Pass additional arguments to `windeployqt`:

```powershell
cpldd.exe MyApplication.exe --windeployqt-arg=--qmldir=qml
```

Multiple arguments can be supplied:

```powershell
cpldd.exe MyApplication.exe --force-qt --windeployqt-arg=--qmldir=qml --windeployqt-arg=--debug
```

Use the `=` form when an argument value itself begins with a hyphen.

Enable strict dependency checking and verbose diagnostics:

```powershell
cpldd.exe MyApplication.exe --strict --verbose
```

## How it works

### 1. Dependency discovery

CPLDD invokes `ldd` against the input executable and parses its output.

Dependencies are classified as:

- **Resolved:** A dependency path was converted to a native Windows path.
- **Unresolved:** A path was reported but could not be converted.
- **Not found:** `ldd` explicitly reported `not found`.

MSYS2/Cygwin `ldd` may return a non-zero exit code while still providing useful dependency information, for example when one dependency is missing. CPLDD parses usable output and reports missing dependencies separately.

### 2. Path conversion

CPLDD converts MSYS2/Cygwin paths into native Windows paths.

For example:

```text
/c/WinDev/mingw64/bin/libgcc_s_seh-1.dll
```

becomes:

```text
C:/WinDev/mingw64/bin/libgcc_s_seh-1.dll
```

CPLDD uses batched `cygpath` conversion to reduce process creation overhead. It uses binary input/output and strict UTF-8 decoding to avoid Windows text-mode newline translation and encoding ambiguity.

If batch conversion fails or produces malformed output, CPLDD retries eligible paths individually. If `cygpath` is unavailable or a conversion still fails, common drive-letter formats are handled by a fallback converter.

Input paths are not whitespace-stripped during conversion, so the conversion layer does not silently alter leading or trailing whitespace.

### 3. System DLL filtering

By default, DLLs located in these Windows directories are skipped:

```text
%WINDIR%\System32
%WINDIR%\SysWOW64
%WINDIR%\WinSxS
```

Use `--force-system-dlls` to include them. Copying Windows-owned components is normally unnecessary, so use this option only when there is a specific reason.

### 4. Executable and DLL deployment

CPLDD creates the destination directory after dependency discovery succeeds.

- The executable is copied and refreshed on each deployment.
- Identical DLLs already in the destination are left in place.
- Different destination DLLs are not overwritten unless `--force-overwrite` is used.
- Different source DLLs with the same basename are reported as a collision, even with `--force-overwrite`.

CPLDD uses a flat deployment directory, so two different DLLs with the same filename cannot safely occupy it under the same name. The output directory is created if it does not exist and reused if it already exists.

> **Note:** CPLDD does not clean the output directory before deployment. Files left over from an earlier deployment are not automatically removed when they are no longer dependencies of the current executable. For a clean deployment, remove or empty the output directory before running CPLDD.

### 5. Qt deployment

If a Qt Core dependency is detected and `windeployqt` is available, CPLDD invokes it for the executable in the deployment directory.

- Non-Qt applications skip this step.
- Use `--force-qt` if Qt is loaded dynamically and is not visible in the `ldd` dependency list.
- Use `--no-qt` to disable Qt deployment.
- Use `--windeployqt-arg` to pass additional arguments.

CPLDD does not force `--release` or `--debug`; `windeployqt` determines the build type unless an override is explicitly passed.

If `windeployqt` is unavailable, Qt deployment is skipped. If it is found but fails, CPLDD reports the failure.

### 6. Final report

CPLDD displays a summary containing:

- Non-system DLLs copied.
- DLLs already present.
- System DLLs skipped.
- Missing dependencies.
- Unresolved dependencies.
- Copy failures and basename collisions.

When multiple problems occur, all detected problems are reported and the first applicable error code is returned.

## MSVC runtime note

On a machine with the Visual C++ Redistributable installed, runtime DLLs such as `vcruntime140.dll` and `msvcp140.dll` may resolve to Windows system locations and therefore be skipped by default.

An MSVC application deployed to a machine without the required Visual C++ runtime may fail to start. Install the appropriate Microsoft Visual C++ Redistributable on the target machine, or deliberately include the required runtime DLLs alongside the executable where licensing and deployment requirements permit.

## Dependency resolution and toolchains

CPLDD relies on the dependency information available through the active `ldd` environment. It does not replace the Windows loader and does not independently search every directory on the machine. It may not discover DLLs loaded dynamically at runtime.

For best results:

1. Load the compiler/runtime environment used to build the application.
2. Make sure the required runtime DLLs are visible to that environment.
3. Run CPLDD from the same environment.
4. Test the deployed application on a clean Windows machine.

CPLDD is designed to work with different Windows C/C++ compiler environments, including:

- MSVC
- MinGW / MinGW-w64
- MSYS2
- Cygwin
- Clang-based environments

CPLDD does not select or configure a compiler toolchain. The active environment determines which tools and runtime DLLs are visible to `ldd`.

## Limitations

- Dynamically loaded dependencies may not appear in `ldd` output.
- Qt deployment requires a compatible `windeployqt` available on `PATH`.
- Unresolved dependency paths may require manual investigation.
- A successful dependency copy does not guarantee that the application has no additional runtime, plugin, data-file, or configuration requirements.
- Final validation on a clean Windows machine is recommended.

## Sample output

The following output is illustrative. Paths, dependency counts, and messages vary by application and environment.

```text
============================================================
 Searching Dependencies
============================================================
Total dependencies found: 12

============================================================
 Copying Executable
============================================================
Copied executable: C:\path\to\MyApplication.exe
Destination: C:\path\to\MyApplication_deploy\MyApplication.exe

============================================================
 Copying Dependencies
============================================================
[1/12] System DLL (skipped): C:\Windows\System32\KERNEL32.dll
[2/12] Copied DLL: C:\WinDev\...\libgcc_s_seh-1.dll
[3/12] Copied DLL: C:\WinDev\...\libwinpthread-1.dll
...

============================================================
 Dependency Summary
============================================================
Non-system DLLs copied : 3
Already present        : 0
System DLLs skipped    : 9
Missing dependencies   : 0
Unresolved dependencies: 0

============================================================
 Searching For Qt Dependencies
============================================================
Qt deployment completed.

============================================================
 Deployment Finished
============================================================
```

## Tests

Run the test suite from the repository root:

```powershell
python tests/test_cpldd.py
```

Or use unittest discovery:

```powershell
python -m unittest discover -s tests -v
```

The unit tests mock `ldd`, `cygpath`, and `windeployqt`, so they do not require those external tools.

For integration testing, use actual Windows executables and the MSYS2 runtime tools. Test the resulting deployment directory on a clean Windows environment to identify dependencies that may not be visible to static dependency inspection.

## Build and release packaging

The standalone executable is built with PyInstaller using `cpldd_.spec`.

The release workflow:

1. Sets up Python 3.12 on Windows.
2. Installs PyInstaller and zstandard.
3. Builds `cpldd.exe` and performs a `--help` smoke test.
4. Downloads the latest x86_64 MSYS2 runtime package.
5. Verifies the downloaded package against its SHA-256 checksum.
6. Extracts `cygpath.exe`, `ldd.exe`, and `msys-2.0.dll`.
7. Assembles and validates a ZIP containing exactly the four release files.
8. Publishes the ZIP as a GitHub Actions artifact and attaches it to tagged GitHub Releases.

The MSYS2 runtime tools are fetched from the official [MSYS2 package page](https://packages.msys2.org/packages/msys2-runtime). The release ZIP contains the three extracted runtime files plus the standalone CPLDD executable.

## Original use case

CPLDD was originally developed to simplify deployment of complex C++ applications with dependency trees involving libraries such as:

- Qt
- VTK
- ITK
- OpenBLAS
- muParser
- Armadillo
- tinyxml2

The same approach remains useful for portable development environments and applications with substantial native dependency trees.

## Project

**Author:** Harsh Kumar Narula

**Repository:** [github.com/harshn05/cpldd](https://github.com/harshn05/cpldd)

**Releases:** [Download the latest CPLDD release](https://github.com/harshn05/cpldd/releases/latest)

## License

See the repository's `LICENSE` file for the licensing terms of CPLDD.
