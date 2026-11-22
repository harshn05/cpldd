# Third-Party Notices

The CPLDD release bundle (`cpldd.zip`) contains CPLDD together with software
written by others. CPLDD itself is licensed under the MIT License
(see [LICENSE.md](LICENSE.md)). The components below are **not** covered by
that license; each is distributed under its own terms.

## Contents of the release bundle

| File | What it is | License |
|---|---|---|
| `cpldd.exe` | CPLDD, packaged with PyInstaller (includes the Python runtime) | MIT (CPLDD); PSF License (Python); see below |
| `ldd.exe` | MSYS2 runtime tool | GPL-3.0-or-later |
| `cygpath.exe` | MSYS2 runtime tool | GPL-3.0-or-later |
| `msys-2.0.dll` | MSYS2 runtime library (Cygwin-based) | GPL-3.0-or-later |
| `GPL-3.0.txt` | Full text of the GNU General Public License, version 3 | - |

---

## 1. MSYS2 runtime (`ldd.exe`, `cygpath.exe`, `msys-2.0.dll`)

These three files are extracted unmodified from the official `msys2-runtime`
package of the [MSYS2](https://www.msys2.org/) project. `msys2-runtime` is
MSYS2's build of the [Cygwin](https://www.cygwin.com/) runtime. The MSYS2
package metadata lists its license as **GPL-3.0-or-later**; some components of
the upstream Cygwin runtime carry additional or more permissive terms, which
are set out in the licensing files of the source distribution linked below.

CPLDD runs `ldd.exe` and `cygpath.exe` as separate programs. CPLDD does not
modify them and does not link against `msys-2.0.dll`.

The full text of the GNU General Public License, version 3, is included in this
bundle as `GPL-3.0.txt`.

**Exact version.** The bundle contains the latest `msys2-runtime` package that
was available when the release was built. That version is printed on the line
`Latest MSYS2 runtime: <version>` in the log of the *Build and Release CPLDD*
workflow run for the release.

**Corresponding source code.** The complete corresponding source for these
files is available from:

- Package recipe and patches (MSYS2): <https://github.com/msys2/MSYS2-packages/tree/master/msys2-runtime>
- Package page: <https://packages.msys2.org/base/msys2-runtime>
- Upstream Cygwin source releases: <https://www.cygwin.com/>

If you cannot obtain the source for the version in a particular release from
these locations, contact the CPLDD maintainer through
<https://github.com/harshn05/cpldd/issues> and it will be provided.

The GPL applies to these separate programs only. It does not apply to your own
applications or to the output CPLDD produces for them: CPLDD copies your
program's DLLs, not the MSYS2 tools.

## 2. Python runtime (inside `cpldd.exe`)

`cpldd.exe` is built with [PyInstaller](https://pyinstaller.org/) and contains
a copy of the CPython interpreter and its standard library.

> Python is Copyright (c) 2001-2026 Python Software Foundation; All Rights
> Reserved. It is distributed under the PSF License Agreement.

The full license text, including the licenses of third-party code bundled with
Python, is at <https://docs.python.org/3/license.html>.

## 3. PyInstaller bootloader (inside `cpldd.exe`)

The PyInstaller bootloader is licensed under the GNU General Public License,
version 2 or later, **with a special exception** that permits the bootloader to
be included in, and distributed with, an application under any license terms.
CPLDD is therefore distributed under the MIT License. See
<https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt>.

---

## Build-time only (not distributed)

`zstandard` is used by `scripts/fetch_msys2_runtime.py` during the release build
to unpack the MSYS2 package. It is not part of the bundle.
