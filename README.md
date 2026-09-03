# CPLDD

CPLDD is a lightweight Windows deployment utility for Qt and non-Qt C/C++ executable programs.

It analyzes the DLL dependencies reported by `ldd` and copies the required non-system DLLs into a deployment directory together with the executable itself. For Qt applications, CPLDD can additionally invoke `windeployqt` to deploy the Qt runtime and plugins.

The original CPLDD was written in Python and has been modernized for Python 3.12+ and portable WinDev environments.

## Features

- Deploys Qt and non-Qt Windows C/C++ executables.
- Uses the `ldd` available in the active environment to discover DLL dependencies.
- Converts MSYS/Cygwin-style paths to native Windows paths using `cygpath` when available.
- Automatically ignores Windows system DLLs from `System32`, `SysWOW64`, and `WinSxS` by default.
- Copies non-system runtime DLLs into a self-contained deployment directory.
- Automatically runs `windeployqt` when it is available.
- Reports missing and unresolved dependencies.
- Supports executable paths and output paths containing spaces.
- Can be used across different compiler environments, provided the required dependency DLLs are visible through the active environment.

## Requirements

CPLDD is designed to work in a Windows shell where the required deployment tools and DLL dependencies are available on `PATH`.

The main tools used by CPLDD are:

- `ldd` for dependency discovery.
- `cygpath` for converting MSYS/Cygwin paths to Windows paths when available.
- `windeployqt` for Qt deployment when available.

CPLDD itself can be run using Python 3.12+ or packaged as a standalone executable.

> **Important:** CPLDD does not magically discover DLLs that are unavailable to the active environment. The executable should already be runnable from the shell or CMD environment used to invoke CPLDD. If dependencies cannot be resolved by `ldd`, CPLDD reports them as missing or unresolved.

## Command Line Usage

### Python

```text
python cpldd.py <Input_Exe_File> [Output_Folder]
```

### Standalone executable

```text
cpldd.exe <Input_Exe_File> [Output_Folder]
```

### Default Output Directory

The output folder is optional.

When it is not specified, CPLDD creates a directory using the executable name without its extension.

For example:

```text
myapp.exe
```

becomes:

```text
myapp/
    myapp.exe
    ...
```

### Custom Output Directory

```text
cpldd.exe myapp.exe deploy
```

creates:

```text
deploy/
    myapp.exe
    ...
```

## Optional Arguments

### `-f`, `--force`

Force Windows system DLLs from `System32`, `SysWOW64`, and `WinSxS` to be copied into the deployment directory.

This is normally undesirable and should only be used when there is a specific reason to deploy a system component.

### `--no-qt`

Do not run `windeployqt` after the regular DLL dependency scan.

```text
cpldd.exe myapp.exe --no-qt
```

### `-v`, `--verbose`

Enable additional diagnostic output.

```text
cpldd.exe myapp.exe --verbose
```

## Examples

Deploy using the executable name as the output directory:

```text
cpldd.exe MyApplication.exe
```

Deploy into a custom directory:

```text
cpldd.exe MyApplication.exe release
```

Deploy without Qt handling:

```text
cpldd.exe MyApplication.exe --no-qt
```

Force copying of Windows system DLLs:

```text
cpldd.exe MyApplication.exe --force
```

Enable verbose diagnostics:

```text
cpldd.exe MyApplication.exe --verbose
```

## How It Works

```text
Executable
    |
    v
   ldd
    |
    v
Parse DLL dependencies
    |
    +----------------------+
    |                      |
    v                      v
Windows system DLLs   Non-system DLLs
    |                      |
    v                      v
   Skip                  Copy
                           |
                           v
                    Deployment folder
                           |
                           v
                     windeployqt
                    (when available)
```

The active shell environment is important.

For example, when deploying a MinGW executable, CPLDD should be run from an environment where the relevant MinGW runtime DLLs and `ldd` are available.

## System DLL Handling

CPLDD deliberately avoids copying Windows-owned system components by default.

The following Windows locations are treated as system locations:

```text
%WINDIR%\System32
%WINDIR%\SysWOW64
%WINDIR%\WinSxS
```

This avoids unnecessarily bundling Windows components such as `COMCTL32.dll` when `ldd` resolves them from the Windows installation.

Use `--force` only when system DLL deployment is explicitly required.

## Qt Deployment

When `windeployqt` is available on `PATH`, CPLDD invokes it for the deployment directory and executable.

This allows the same utility to handle applications with Qt dependencies as well as applications without Qt dependencies.

Use `--no-qt` to disable this step.

## Dependency Resolution Model

CPLDD relies on the dependency information available through the active `ldd` environment.

It does not replace the Windows operating system loader and does not independently search every directory on the machine.

For best results:

1. Load the compiler/runtime environment used by the application.
2. Make sure the executable runs from that shell without DLL load failures.
3. Run CPLDD from the same environment.

This is especially useful with portable development environments such as WinDev, where the active toolchain determines which runtime DLLs are visible to `ldd`.

## Compiler Toolchains

CPLDD is designed to work with different Windows C/C++ compiler environments.

Examples include:

- MSVC
- MinGW / MinGW-w64
- MSYS2
- Cygwin
- Clang-based environments

The important requirement is that the active shell environment exposes the executable's required runtime DLLs to `ldd`.

For example:

```text
WinDev::MinGW
      |
      +--> ldd
      |
      +--> MinGW runtime DLLs
      |
      +--> cpldd
```

Similarly:

```text
WinDev::ClangMSVC
      |
      +--> ldd
      |
      +--> LLVM/MSVC runtime DLLs
      |
      +--> cpldd
```

CPLDD itself does not select a compiler toolchain. It works with whatever dependency environment is currently active.

## Standalone Deployment

CPLDD can be packaged as a standalone Windows executable so that Python itself does not need to be loaded as a development environment.

A typical WinDev layout is:

```text
WinDev/
└── Programs/
    └── cpldd.exe
```

Once `Programs` is on `PATH`, CPLDD can be invoked directly:

```text
cpldd myapp.exe
```

The standalone executable still uses the `ldd`, `cygpath`, and optional `windeployqt` available in the active shell environment.

This makes CPLDD convenient as a general-purpose WinDev deployment utility without requiring the Python environment to be loaded first.

## Sample Output

CPLDD reports each dependency as it is processed and provides a summary at the end.

A deployment may contain output similar to:

```text
============================================================
 Copying Executable
============================================================
Copied executable: C:\path\to\MyApplication.exe

============================================================
 Searching Dependencies
============================================================
Total dependencies found: 12
[1/12] System DLL ignored: C:\Windows\System32\KERNEL32.dll
[2/12] Copied DLL: C:\WinDev\...\libgcc_s_seh-1.dll
[3/12] Copied DLL: C:\WinDev\...\libwinpthread-1.dll
...

============================================================
 Dependency Summary
============================================================
Non-system DLLs copied : 3
System DLLs skipped    : 9
Missing dependencies   : 0
Unresolved dependencies: 0
```

## Original Use Case

CPLDD was originally developed to simplify deployment of complex C++ applications containing dependencies such as:

- Qt
- VTK
- ITK
- OpenBLAS
- muParser
- Armadillo
- tinyxml2

The same approach remains useful for modern portable development environments and complicated C++ applications.

## Download

Download the latest standalone binaries from the releases page:

<https://github.com/harshn05/cpldd/releases/latest>

## License

See the repository license file for the licensing terms of CPLDD.
