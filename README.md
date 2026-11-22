# CPLDD

CPLDD is a lightweight Windows DLL deployment utility for Qt and non-Qt C/C++ applications.

It analyzes the DLL dependencies reported by `ldd`, then copies the input executable and its required non-system DLL dependencies into a deployment directory. For Qt applications, CPLDD can also invoke `windeployqt` to deploy the Qt runtime, plugins, and other Qt-related files.

The original CPLDD was written in Python and has been modernized for Python 3.12+ and portable development environments such as WinDev.

## Features

- Deploys Qt and non-Qt Windows C/C++ executables.
- Uses `ldd` from the currently active environment to discover DLL dependencies.
- Converts MSYS/Cygwin-style paths to native Windows paths using `cygpath` when available, with common drive-path fallbacks.
- Skips Windows system DLLs from `System32`, `SysWOW64`, and `WinSxS` by default.
- Copies non-system runtime DLLs alongside the executable.
- Runs `windeployqt` when Qt Core is detected and the tool is available. Use `--force-qt` to run it when Qt is loaded dynamically.
- Reports missing, unresolved, and conflicting dependencies.
- Supports executable and output paths containing spaces.
- Detects DLL basename collisions instead of silently overwriting one dependency with another.
- Supports multiple compiler/runtime environments, provided the required tools and DLLs are visible to the active environment.

## Requirements

CPLDD is intended to run on Windows from a shell where the required deployment tools and runtime DLL dependencies are available on `PATH`.

The tools used are:

| Tool | Purpose | Required |
|---|---|---|
| `ldd` | Dependency discovery | Yes |
| `cygpath` | MSYS/Cygwin path conversion | No, but recommended |
| `windeployqt` | Qt runtime deployment | Only for Qt deployment |

CPLDD itself can be run with Python 3.12+ or packaged as a standalone Windows executable.

> **Important:** CPLDD relies on the active `ldd` environment. It does not independently search every directory on the machine or discover DLLs that are unavailable to that environment. Load the compiler/runtime environment used by the application before running CPLDD.

## Command-line usage

### Python

```powershell
python cpldd.py <Input_Exe_File> [Output_Folder]
```

### Standalone executable

```powershell
cpldd.exe <Input_Exe_File> [Output_Folder]
```

The output folder is optional. If omitted, CPLDD creates a directory next to the executable using the executable's name with a `_deploy` suffix.

For example:

```text
myapp.exe
```

creates:

```text
myapp_deploy/
└── myapp.exe
    ...
```

To specify an output directory:

```powershell
cpldd.exe myapp.exe deploy
```

## Options

### `--force-system-dlls`

Copy Windows system DLLs from `System32`, `SysWOW64`, and `WinSxS` into the deployment directory.

```powershell
cpldd.exe myapp.exe --force-system-dlls
```

System DLLs are skipped by default. Copying Windows-owned components is normally undesirable, so use this option only when you have a specific reason.

### `--force-overwrite`

Overwrite an existing destination DLL when its contents differ from the source.

```powershell
cpldd.exe myapp.exe --force-overwrite
```

By default, CPLDD does not silently replace a different DLL already present in the output directory. Identical files are treated as already present.

The executable itself is always refreshed, so rebuilding the application and running CPLDD again updates the deployed executable without requiring this option.

This option does not bypass DLL basename-collision detection. Two different source DLLs with the same filename cannot safely occupy the same flat deployment directory.

### `--no-qt`

Disable the `windeployqt` step, even when Qt dependencies are detected.

```powershell
cpldd.exe myapp.exe --no-qt
```

### `--force-qt`

Run `windeployqt` even if no Qt Core library appears in the dependency list. This is useful when the application loads Qt dynamically.

```powershell
cpldd.exe myapp.exe --force-qt
```

If `windeployqt` is not available on `PATH`, Qt deployment is skipped.

### `--windeployqt-arg ARG`

Pass additional arguments to `windeployqt`. This option can be repeated.

```powershell
cpldd.exe myapp.exe --windeployqt-arg=--debug --windeployqt-arg=--qmldir=qml
```

Use the `=` form when the argument value itself begins with a hyphen.

CPLDD does not force `--release` or `--debug`; `windeployqt` determines the build type from the executable unless you explicitly pass an override.

### `--strict`

Return exit code `8` if one or more dependency paths remain unresolved.

```powershell
cpldd.exe myapp.exe --strict
```

Without `--strict`, unresolved paths are reported but do not, by themselves, cause a non-zero exit code. Missing dependencies are still treated as an error.

### `-v`, `--verbose`

Enable additional diagnostic output.

```powershell
cpldd.exe myapp.exe --verbose
```

## Examples

Deploy using the default output directory:

```powershell
cpldd.exe MyApplication.exe
```

Deploy into a custom directory:

```powershell
cpldd.exe MyApplication.exe release
```

Deploy without Qt handling:

```powershell
cpldd.exe MyApplication.exe --no-qt
```

Force Qt deployment, for example when Qt is loaded dynamically:

```powershell
cpldd.exe MyApplication.exe --force-qt
```

Enable strict dependency checking and verbose diagnostics:

```powershell
cpldd.exe MyApplication.exe --strict --verbose
```

## How it works

1. CPLDD runs `ldd` against the input executable.
2. It parses the dependency list and converts reported paths to Windows paths.
3. Windows system DLLs are skipped by default.
4. Resolved non-system DLLs are copied into the deployment directory.
5. If Qt Core is detected, CPLDD runs `windeployqt` when it is available. `--force-qt` can request this step explicitly.

Dependency discovery happens before the output directory is created. If `ldd` fails or reports no usable dependencies, CPLDD exits without creating a partial deployment directory.

The active shell environment matters. For example, when deploying a MinGW executable, run CPLDD from an environment where the relevant MinGW runtime DLLs and `ldd` are available.

## Output directory behaviour

CPLDD creates the output directory if it does not exist. If the directory already exists, it reuses it.

- The executable is always refreshed.
- An identical DLL already in the destination is left in place.
- A different DLL with the same destination filename is not overwritten unless `--force-overwrite` is used.
- Different source DLLs with the same basename are reported as a collision and are not silently substituted.

**CPLDD does not clean the output directory before deployment.** DLLs left over from an earlier deployment are not automatically deleted if they are no longer dependencies of the current executable. If you need a clean deployment, remove or empty the output directory before running CPLDD.

## System DLL handling

CPLDD avoids copying Windows-owned system components by default.

The following locations are treated as system locations:

```text
%WINDIR%\System32
%WINDIR%\SysWOW64
%WINDIR%\WinSxS
```

This avoids unnecessarily bundling Windows components such as `KERNEL32.dll` or `COMCTL32.dll` when `ldd` resolves them from the Windows installation.

Use `--force-system-dlls` only when system DLL deployment is explicitly required.

## Qt deployment

CPLDD detects Qt by looking for a Qt Core dependency, such as `Qt6Core.dll` or `Qt5Core.dll`.

When Qt Core is detected and `windeployqt` is available on `PATH`, CPLDD invokes it for the copied executable in the deployment directory. This allows `windeployqt` to deploy the relevant Qt runtime files and plugins.

- Non-Qt applications skip this step.
- Use `--force-qt` if Qt is loaded dynamically and is not visible in the `ldd` dependency list.
- Use `--no-qt` to disable Qt deployment.
- Use `--windeployqt-arg` to pass additional arguments to `windeployqt`.

If `windeployqt` is unavailable, the Qt deployment step is skipped. If it is found but fails, CPLDD reports the failure and returns exit code `7` unless an earlier error takes precedence.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success. |
| `2` | Input executable not found. |
| `3` | `ldd` failed or reported no dependencies. |
| `4` | One or more dependencies were missing. |
| `5` | A file copy failed, including a DLL basename collision. |
| `6` | Invalid or unusable output directory. |
| `7` | `windeployqt` was found but Qt deployment failed. |
| `8` | Unresolved dependencies found while `--strict` was enabled. |
| `64` | Command-line usage error. |

When several problems occur, CPLDD reports all detected problems and returns the first applicable error code in the order shown above.

## MSVC runtime note

On a machine with the Visual C++ Redistributable installed, runtime DLLs such as `vcruntime140.dll` and `msvcp140.dll` may resolve to Windows system locations and therefore be skipped by default.

An MSVC application deployed to a machine without the required Visual C++ runtime may fail to start. Install the appropriate Microsoft Visual C++ Redistributable on the target machine, or deliberately include the required runtime DLLs alongside the executable where licensing and deployment requirements permit.

## Dependency resolution model

CPLDD uses the dependency information available through the active `ldd` environment. It does not replace the Windows loader and does not independently search every directory on the machine.

For best results:

1. Load the compiler/runtime environment used to build the application.
2. Make sure the required runtime DLLs are visible to that environment.
3. Run the executable from that environment and check that it starts without DLL load failures.
4. Run CPLDD from the same environment.

This model is particularly useful with portable development environments such as WinDev, where the active toolchain determines which runtime DLLs are visible to `ldd`.

## Compiler toolchains

CPLDD is designed to work with different Windows C/C++ compiler environments, including:

- MSVC
- MinGW / MinGW-w64
- MSYS2
- Cygwin
- Clang-based environments

CPLDD does not select or configure a compiler toolchain. It works with the dependency environment that is active when it is launched.

For example, a WinDev MinGW environment should expose `ldd` and the relevant MinGW runtime DLLs on its `PATH`. A Clang/MSVC environment should expose the corresponding LLVM/MSVC runtime dependencies and the required `ldd` tool.

## Standalone deployment

CPLDD can be packaged as a standalone Windows executable, so a separate Python installation is not required to launch CPLDD.

A typical WinDev layout is:

```text
WinDev/
└── Programs/
    └── cpldd.exe
```

Once `Programs` is on `PATH`, invoke it directly:

```powershell
cpldd myapp.exe
```

The standalone CPLDD executable still relies on `ldd`, `cygpath`, and the optional `windeployqt` available in the active shell environment. Packaging CPLDD itself does not bundle or replace those external tools.

## Sample output

The following is illustrative. Exact paths, dependency counts, and messages vary by application and environment.

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
```

## Original use case

CPLDD was originally developed to simplify deployment of complex C++ applications containing dependencies such as:

- Qt
- VTK
- ITK
- OpenBLAS
- muParser
- Armadillo
- tinyxml2

The same approach remains useful for modern portable development environments and applications with substantial native dependency trees.

## Tests

Run the test suite from the repository root:

```powershell
python tests/test_cpldd.py
```

Or use unittest discovery:

```powershell
python -m unittest discover -s tests -v
```

The tests mock `ldd`, `cygpath`, and `windeployqt`, so the test suite does not require those external tools to be installed.

## Download

Download the latest standalone binaries from the [GitHub Releases page](https://github.com/harshn05/cpldd/releases/latest).

## License

See the repository's `LICENSE` file for the licensing terms of CPLDD.
