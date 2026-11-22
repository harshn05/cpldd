"""
Unit tests for cpldd.

Run from the repository root:

    python tests/test_cpldd.py
    python -m unittest discover -s tests -v

The tests do not need ldd, cygpath or windeployqt: external tools are
mocked, and path handling is exercised through Windows-style strings.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cpldd  # noqa: E402
from cpldd import (  # noqa: E402
    CopyResult,
    DepStatus,
    Dependency,
    QtDeployResult,
)


def posix(path: Path | None) -> str | None:
    return None if path is None else str(path).replace("\\", "/")


def no_cygpath(paths):
    """Stand-in for _cygpath_batch: forces the regex fallback."""
    return [None] * len(paths)


# ---------------------------------------------------------------------------
# ldd parsing
# ---------------------------------------------------------------------------

class ParseLddTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(cpldd, "_cygpath_batch", side_effect=no_cygpath)
        self.cygpath = patcher.start()
        self.addCleanup(patcher.stop)

    def test_resolved_and_not_found(self) -> None:
        output = (
            "\tntdll.dll => /c/Windows/SYSTEM32/ntdll.dll (0x7ff800000000)\n"
            "\tlibfoo.dll => /c/WinDev/mingw64/bin/libfoo.dll (0x6fe00000)\n"
            "\tmissing.dll => not found\n"
        )
        deps = cpldd.parse_ldd_output(output)

        self.assertEqual([d.name for d in deps], ["ntdll.dll", "libfoo.dll", "missing.dll"])
        self.assertEqual(posix(deps[1].windows_path), "C:/WinDev/mingw64/bin/libfoo.dll")
        self.assertIs(deps[1].status, DepStatus.RESOLVED)
        self.assertIs(deps[2].status, DepStatus.NOT_FOUND)
        self.assertIsNone(deps[2].windows_path)

    def test_cygdrive_path_and_no_base_address(self) -> None:
        deps = cpldd.parse_ldd_output("a.dll => /cygdrive/d/lib/a.dll\n")
        self.assertEqual(posix(deps[0].windows_path), "D:/lib/a.dll")

    def test_path_with_spaces(self) -> None:
        deps = cpldd.parse_ldd_output(
            "liba.dll => /c/Program Files/My Lib/liba.dll (0x1000)\n"
        )
        self.assertEqual(posix(deps[0].windows_path), "C:/Program Files/My Lib/liba.dll")

    def test_unconvertible_path_is_unresolved(self) -> None:
        deps = cpldd.parse_ldd_output("libx.dll => /mingw64/bin/libx.dll (0x1)\n")
        self.assertIs(deps[0].status, DepStatus.UNRESOLVED)
        self.assertEqual(deps[0].raw_path, "/mingw64/bin/libx.dll")

    def test_ldd_error_text_yields_no_dependencies(self) -> None:
        self.assertEqual(
            cpldd.parse_ldd_output("ldd: nosuch.exe: No such file or directory"), []
        )

    def test_only_hex_base_address_is_stripped(self) -> None:
        deps = cpldd.parse_ldd_output("foo.dll => /c/dir/foo (1)\n")
        self.assertEqual(deps[0].raw_path, "/c/dir/foo (1)")

    def test_duplicates_are_removed(self) -> None:
        line = "libfoo.dll => /c/bin/libfoo.dll (0x1)\n"
        self.assertEqual(len(cpldd.parse_ldd_output(line * 3)), 1)

    def test_paths_are_converted_in_one_batch(self) -> None:
        output = (
            "a.dll => /c/bin/a.dll (0x1)\n"
            "b.dll => /c/bin/b.dll (0x2)\n"
            "c.dll => /c/bin/c.dll (0x3)\n"
        )
        cpldd.parse_ldd_output(output)
        self.assertEqual(self.cygpath.call_count, 1)

    def test_native_windows_path_needs_no_conversion(self) -> None:
        deps = cpldd.parse_ldd_output(r"a.dll => C:\bin\a.dll (0x1)" + "\n")
        self.assertEqual(posix(deps[0].windows_path), "C:/bin/a.dll")
        self.cygpath.assert_not_called()


# ---------------------------------------------------------------------------
# Path conversion & normalization
# ---------------------------------------------------------------------------

class PathConversionTests(unittest.TestCase):
    def test_convert_paths_preserves_leading_and_trailing_spaces(self) -> None:
        samples = [
            "/c/dir/trailing space ",
            " /c/leading space/a.dll",
            r"C:\dir\trailing space ",
        ]
        with mock.patch.object(cpldd, "_cygpath_batch", side_effect=no_cygpath) as batch:
            converted = cpldd.convert_paths(samples)

        batch.assert_called_once_with(
            ["/c/dir/trailing space ", " /c/leading space/a.dll"]
        )
        self.assertEqual(converted["/c/dir/trailing space "], Path("C:/dir/trailing space "))
        self.assertIsNone(converted[" /c/leading space/a.dll"])
        self.assertEqual(converted[r"C:\dir\trailing space "], Path(r"C:\dir\trailing space "))

    def test_cygpath_to_windows_preserves_trailing_space_with_cygpath(self) -> None:
        with mock.patch.object(
            cpldd, "_cygpath_batch", return_value=["C:/dir/foo .dll"]
        ) as batch:
            result = cpldd.cygpath_to_windows("/c/dir/foo .dll ")

        batch.assert_called_once_with(["/c/dir/foo .dll "])
        self.assertEqual(result, Path("C:/dir/foo .dll"))

    def test_convert_paths_rejects_blank_and_question_placeholders(self) -> None:
        with mock.patch.object(cpldd, "_cygpath_batch") as batch:
            converted = cpldd.convert_paths(["", "   ", "?", "??"])

        batch.assert_not_called()
        self.assertEqual(converted, {"": None, "   ": None, "?": None, "??": None})


# ---------------------------------------------------------------------------
# cygpath batch conversion
# ---------------------------------------------------------------------------

class CygpathBatchTests(unittest.TestCase):
    def test_empty_input_does_not_spawn_process(self) -> None:
        with mock.patch.object(cpldd.shutil, "which") as which, \
             mock.patch.object(cpldd.subprocess, "run") as run:
            self.assertEqual(cpldd._cygpath_batch([]), [])
        which.assert_not_called()
        run.assert_not_called()

    def test_successful_binary_batch_preserves_order_and_utf8(self) -> None:
        completed = mock.Mock(
            stdout="C:/Program Files/a.dll\r\nD:/München/b.dll\r\n".encode("utf-8")
        )
        with mock.patch.object(cpldd.shutil, "which", return_value="cygpath.exe"), \
             mock.patch.object(cpldd.subprocess, "run", return_value=completed) as run:
            result = cpldd._cygpath_batch(["/c/Program Files/a.dll", "/d/München/b.dll"])
        self.assertEqual(result, ["C:/Program Files/a.dll", "D:/München/b.dll"])
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["cygpath.exe", "-C", "UTF8", "-m", "-f", "-"])
        self.assertEqual(kwargs["input"], "/c/Program Files/a.dll\n/d/München/b.dll\n".encode("utf-8"))
        self.assertIs(kwargs["text"], False)
        self.assertEqual(kwargs["timeout"], 30)

    def test_missing_cygpath(self) -> None:
        with mock.patch.object(cpldd.shutil, "which", return_value=None):
            self.assertEqual(cpldd._cygpath_batch(["/c/a.dll", "/d/b.dll"]), [None, None])

    def test_finds_cygpath_sibling_next_to_ldd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            ldd_bin = bin_dir / "ldd"
            cygpath_name = "cygpath.exe" if os.name == "nt" else "cygpath"
            cygpath_bin = bin_dir / cygpath_name
            ldd_bin.write_text("")
            cygpath_bin.write_text("")

            def fake_which(cmd: str) -> str | None:
                return str(ldd_bin) if cmd == "ldd" else None

            with mock.patch.object(cpldd.shutil, "which", side_effect=fake_which):
                self.assertEqual(cpldd._find_cygpath(), str(cygpath_bin))

    def test_process_failure_retries_each_path(self) -> None:
        with mock.patch.object(cpldd.shutil, "which", return_value="cygpath"), \
             mock.patch.object(cpldd.subprocess, "run", side_effect=[
                 cpldd.subprocess.CalledProcessError(1, "cygpath"),
                 mock.Mock(stdout=b"C:/a.dll\n"),
                 mock.Mock(stdout=b"D:/b.dll\n"),
             ]) as run:
            self.assertEqual(cpldd._cygpath_batch(["/c/a.dll", "/d/b.dll"]), ["C:/a.dll", "D:/b.dll"])
        self.assertEqual(run.call_count, 3)

    def test_malformed_batch_retries_paths_individually(self) -> None:
        with mock.patch.object(cpldd.shutil, "which", return_value="cygpath"), \
             mock.patch.object(cpldd.subprocess, "run", side_effect=[
                 mock.Mock(stdout=b"C:/only-one.dll\n"),
                 mock.Mock(stdout=b"C:/a.dll\n"),
                 mock.Mock(stdout=b"D:/b.dll\n"),
             ]):
            self.assertEqual(cpldd._cygpath_batch(["/c/a.dll", "/d/b.dll"]), ["C:/a.dll", "D:/b.dll"])

    def test_invalid_utf8_batch_retries_individually(self) -> None:
        with mock.patch.object(cpldd.shutil, "which", return_value="cygpath"), \
             mock.patch.object(cpldd.subprocess, "run", side_effect=[
                 mock.Mock(stdout=b"\xff\n"),
                 mock.Mock(stdout=b"C:/a.dll\n"),
             ]):
            self.assertEqual(cpldd._cygpath_batch(["/c/a.dll"]), ["C:/a.dll"])

    def test_whitespace_only_output_is_rejected(self) -> None:
        with mock.patch.object(cpldd.shutil, "which", return_value="cygpath"), \
             mock.patch.object(cpldd.subprocess, "run", side_effect=[
                 mock.Mock(stdout=b"   \n"),
                 mock.Mock(stdout=b""),
             ]):
            self.assertEqual(cpldd._cygpath_batch(["/c/a.dll"]), [None])

    def test_embedded_newline_path_does_not_poison_batch(self) -> None:
        with mock.patch.object(cpldd.shutil, "which", return_value="cygpath"), \
             mock.patch.object(cpldd.subprocess, "run", return_value=mock.Mock(stdout=b"C:/good.dll\n")) as run:
            self.assertEqual(
                cpldd._cygpath_batch(["/c/good.dll", "/c/bad\nname.dll"]),
                ["C:/good.dll", None],
            )
        run.assert_called_once()


# ---------------------------------------------------------------------------
# System DLL detection
# ---------------------------------------------------------------------------

class SystemDllTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {"WINDIR": r"C:\Windows"})
        patcher.start()
        self.addCleanup(patcher.stop)
        cpldd._system_roots.cache_clear()
        self.addCleanup(cpldd._system_roots.cache_clear)

    def test_system_locations(self) -> None:
        for p in (
            r"C:\Windows\System32\kernel32.dll",
            r"C:\WINDOWS\syswow64\x.dll",
            r"C:\Windows\WinSxS\amd64_foo\bar.dll",
            "C:/Windows/system32/user32.dll",
        ):
            with self.subTest(path=p):
                self.assertTrue(cpldd.is_system_dll(Path(p)))

    def test_non_system_locations(self) -> None:
        for p in (
            r"C:\WinDev\mingw64\bin\libgcc_s_seh-1.dll",
            r"C:\Windows\System32x\a.dll",  # prefix must end at a separator
            r"C:\Windows\Fonts\a.dll",
        ):
            with self.subTest(path=p):
                self.assertFalse(cpldd.is_system_dll(Path(p)))


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

class CopyFileTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src_dir = self.root / "src"
        self.dst_dir = self.root / "dst"
        self.src_dir.mkdir()
        self.src = self.src_dir / "a.dll"
        self.src.write_bytes(b"one")

    def copy(self, **kw) -> CopyResult:
        with redirect_stdout(io.StringIO()):
            return cpldd.copy_file(self.src, self.dst_dir, label="Copied", **kw)

    def test_new_identical_and_different(self) -> None:
        self.assertIs(self.copy(), CopyResult.COPIED)
        self.assertIs(self.copy(), CopyResult.ALREADY_PRESENT)

        self.src.write_bytes(b"two")
        with self.assertRaises(FileExistsError):
            self.copy()

        self.assertIs(self.copy(overwrite=True), CopyResult.COPIED)
        self.assertEqual((self.dst_dir / "a.dll").read_bytes(), b"two")

    def test_same_file(self) -> None:
        with redirect_stdout(io.StringIO()):
            result = cpldd.copy_file(self.src, self.src_dir, label="Copied")
        self.assertIs(result, CopyResult.SAME_FILE)

    def test_overwrite_read_only_destination(self) -> None:
        self.copy()
        dest = self.dst_dir / "a.dll"
        dest.chmod(0o444)
        self.src.write_bytes(b"three")
        self.assertIs(self.copy(overwrite=True), CopyResult.COPIED)
        self.assertEqual(dest.read_bytes(), b"three")

    def test_missing_source(self) -> None:
        self.src.unlink()
        with self.assertRaises(FileNotFoundError):
            self.copy()


# ---------------------------------------------------------------------------
# Qt detection and console handling
# ---------------------------------------------------------------------------

class QtDetectionTests(unittest.TestCase):
    def dep(self, name: str) -> Dependency:
        return Dependency(name, None, None, DepStatus.NOT_FOUND)

    def test_detects_qt_core_variants(self) -> None:
        for name in ("Qt6Core.dll", "Qt5Cored.dll", "QtCore4.dll", "libQt5Core.dll"):
            with self.subTest(name=name):
                self.assertTrue(cpldd.uses_qt([self.dep(name)]))

    def test_ignores_non_qt(self) -> None:
        self.assertFalse(cpldd.uses_qt([self.dep("libfoo.dll"), self.dep("vtkCommon.dll")]))


class ConsoleTests(unittest.TestCase):
    def test_strike_falls_back_on_legacy_code_page(self) -> None:
        legacy = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch.object(sys, "stdout", legacy):
            self.assertEqual(cpldd.strike("abc"), "abc")

    def test_strike_on_utf8(self) -> None:
        utf8 = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with mock.patch.object(sys, "stdout", utf8):
            self.assertEqual(cpldd.strike("ab"), "a\u0336b\u0336")

    def test_usage_error_exit_code(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            cpldd.build_parser().parse_args([])
        self.assertEqual(cm.exception.code, 64)

    def test_no_qt_and_force_qt_are_mutually_exclusive(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            cpldd.build_parser().parse_args(["app.exe", "--no-qt", "--force-qt"])
        self.assertEqual(cm.exception.code, 64)


# ---------------------------------------------------------------------------
# deploy()
# ---------------------------------------------------------------------------

class DeployTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.exe = self.bin / "app.exe"
        self.exe.write_bytes(b"exe-v1")
        self.out = self.root / "out"

    def make_dll(self, name: str, folder: str = "libs", data: bytes = b"dll") -> Path:
        directory = self.root / folder
        directory.mkdir(exist_ok=True)
        path = directory / name
        path.write_bytes(data)
        return path

    @staticmethod
    def dep(path: Path) -> Dependency:
        return Dependency(path.name, str(path), path, DepStatus.RESOLVED)

    def run_deploy(self, deps, **kw):
        params = dict(force_system=False, no_qt=True, verbose=False, overwrite=False)
        params.update(kw)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cpldd, "run_ldd", return_value="stub"), \
             mock.patch.object(cpldd, "parse_ldd_output", return_value=deps), \
             redirect_stdout(out), redirect_stderr(err):
            rc = cpldd.deploy(self.exe, self.out, **params)
        return rc, out.getvalue(), err.getvalue()

    def test_success_and_rebuilt_exe_is_refreshed(self) -> None:
        dll = self.make_dll("libfoo.dll")
        rc, _, _ = self.run_deploy([self.dep(dll)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.out / "libfoo.dll").is_file())
        self.assertEqual((self.out / "app.exe").read_bytes(), b"exe-v1")

        self.exe.write_bytes(b"exe-v2")  # simulate a rebuild
        rc, _, _ = self.run_deploy([self.dep(dll)])
        self.assertEqual(rc, 0)
        self.assertEqual((self.out / "app.exe").read_bytes(), b"exe-v2")

    def test_no_dependencies_is_an_error_and_leaves_no_output(self) -> None:
        err = io.StringIO()
        with mock.patch.object(cpldd, "run_ldd", return_value="ldd: app.exe: not a PE file"), \
             mock.patch.object(cpldd, "_cygpath_batch", side_effect=no_cygpath), \
             redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = cpldd.deploy(
                self.exe, self.out,
                force_system=False, no_qt=True, verbose=False, overwrite=False,
            )
        self.assertEqual(rc, 3)
        self.assertFalse(self.out.exists())
        self.assertIn("not a PE file", err.getvalue())

    def test_unusable_output_directory(self) -> None:
        self.out.write_text("I am a file, not a directory")
        rc, _, _ = self.run_deploy([self.dep(self.make_dll("libfoo.dll"))])
        self.assertEqual(rc, 6)

    def test_output_directory_equal_to_input_directory(self) -> None:
        self.out = self.bin
        rc, _, _ = self.run_deploy([self.dep(self.make_dll("libfoo.dll"))])
        self.assertEqual(rc, 6)

    def test_missing_executable(self) -> None:
        self.exe.unlink()
        rc, _, _ = self.run_deploy([])
        self.assertEqual(rc, 2)

    def test_system_dll_is_skipped(self) -> None:
        dll = self.make_dll("sys.dll")
        with mock.patch.object(cpldd, "is_system_dll", return_value=True):
            rc, stdout, _ = self.run_deploy([self.dep(dll)])
        self.assertEqual(rc, 0)
        self.assertFalse((self.out / "sys.dll").exists())
        self.assertIn("System DLLs skipped    : 1", stdout)

    def test_name_collision_is_reported(self) -> None:
        first = self.make_dll("dup.dll", folder="libs1", data=b"1")
        second = self.make_dll("dup.dll", folder="libs2", data=b"2")
        rc, _, err = self.run_deploy([self.dep(first), self.dep(second)])
        self.assertEqual(rc, 5)
        self.assertIn("DLL NAME COLLISION", err)
        self.assertIn("\n    First source", err)  # real line breaks, not "\n"
        self.assertEqual((self.out / "dup.dll").read_bytes(), b"1")

    def test_all_problems_are_listed_first_code_returned(self) -> None:
        qt = self.make_dll("Qt6Core.dll")
        gone = Dependency("gone.dll", None, None, DepStatus.NOT_FOUND)
        with mock.patch.object(
            cpldd, "run_windeployqt", return_value=QtDeployResult.FAILED
        ):
            rc, _, err = self.run_deploy([self.dep(qt), gone], no_qt=False)
        self.assertEqual(rc, 4)
        self.assertIn("[4]", err)
        self.assertIn("[7]", err)

    def test_windeployqt_skipped_without_qt_libraries(self) -> None:
        dll = self.make_dll("libfoo.dll")
        with mock.patch.object(cpldd, "run_windeployqt") as qt:
            rc, stdout, _ = self.run_deploy([self.dep(dll)], no_qt=False)
        self.assertEqual(rc, 0)
        qt.assert_not_called()
        self.assertIn("No Qt libraries detected", stdout)

    def test_windeployqt_runs_when_qt_detected(self) -> None:
        qt_dll = self.make_dll("Qt6Core.dll")
        with mock.patch.object(
            cpldd, "run_windeployqt", return_value=QtDeployResult.SUCCESS
        ) as qt:
            rc, _, _ = self.run_deploy([self.dep(qt_dll)], no_qt=False)
        self.assertEqual(rc, 0)
        qt.assert_called_once()

    def test_force_qt_and_passthrough_args(self) -> None:
        dll = self.make_dll("libfoo.dll")
        with mock.patch.object(
            cpldd, "run_windeployqt", return_value=QtDeployResult.SUCCESS
        ) as qt:
            rc, _, _ = self.run_deploy(
                [self.dep(dll)], no_qt=False, force_qt=True, qt_args=["--debug"],
            )
        self.assertEqual(rc, 0)
        self.assertEqual(qt.call_args.args[3], ["--debug"])

    def test_strict_reports_unresolved(self) -> None:
        unresolved = Dependency("libx.dll", "/mingw64/bin/libx.dll", None, DepStatus.UNRESOLVED)
        self.assertEqual(self.run_deploy([unresolved])[0], 0)
        self.assertEqual(self.run_deploy([unresolved], strict=True)[0], 8)

    def test_windeployqt_command_has_no_forced_release_flag(self) -> None:
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            return mock.Mock(returncode=0)

        with mock.patch.object(cpldd.shutil, "which", return_value="windeployqt.exe"), \
             mock.patch.object(cpldd.subprocess, "run", side_effect=fake_run), \
             redirect_stdout(io.StringIO()):
            result = cpldd.run_windeployqt(
                Path("app.exe"), Path("out"), verbose=True, extra_args=["--debug"]
            )

        self.assertIs(result, QtDeployResult.SUCCESS)
        command = captured["command"]
        self.assertNotIn("--release", command)
        self.assertIn("--debug", command)
        self.assertEqual(command[-3:], ["--verbose", "2", "app.exe"])


if __name__ == "__main__":
    unittest.main()
