#!/usr/bin/env python3
"""Fetch the latest x86_64 MSYS2 runtime package and extract CPLDD's 3 tools."""
from __future__ import annotations
import argparse, hashlib, re, shutil, sys, tarfile, urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

PAGE = "https://packages.msys2.org/packages/msys2-runtime"
FILES = {
    "usr/bin/cygpath.exe": "cygpath.exe",
    "usr/bin/ldd.exe": "ldd.exe",
    "usr/bin/msys-2.0.dll": "msys-2.0.dll",
}
PACKAGE_RE = re.compile(r"msys2-runtime-[0-9][A-Za-z0-9.+~_-]*-x86_64\.pkg\.tar\.zst$")
SHA_RE = re.compile(r"SHA256\s*:?\s*([0-9a-fA-F]{64})", re.I)

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.text = [], []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href: self.links.append(href)
    def handle_data(self, data):
        if data.strip(): self.text.append(data.strip())

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "CPLDD-GitHub-Actions"})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read()

def discover():
    parser = Parser()
    parser.feed(get(PAGE).decode("utf-8", "replace"))
    urls = list(dict.fromkeys(
        urljoin(PAGE, u) for u in parser.links
        if PACKAGE_RE.search(u.rsplit("/", 1)[-1])
    ))
    if len(urls) != 1:
        raise RuntimeError(f"Expected one latest x86_64 package URL, found: {urls}")
    match = SHA_RE.search(" ".join(parser.text))
    if not match:
        raise RuntimeError("Could not read SHA256 from official MSYS2 package page")
    url = urls[0]
    filename = url.rsplit("/", 1)[-1]
    version = filename.removeprefix("msys2-runtime-").removesuffix("-x86_64.pkg.tar.zst")
    return filename, url, match.group(1).lower(), version

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=Path, required=True)
    out = ap.parse_args().output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    filename, url, expected, version = discover()
    archive = out.parent / filename
    print(f"Latest MSYS2 runtime: {version}")
    print(f"Package URL: {url}")
    archive.write_bytes(get(url))
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f"SHA256 mismatch: expected {expected}, got {actual}")
    print(f"SHA256 verified: {actual}")

    import zstandard
    found = set()
    with archive.open("rb") as compressed:
        with zstandard.ZstdDecompressor().stream_reader(compressed) as reader:
            with tarfile.open(fileobj=reader, mode="r|") as tar:
                for member in tar:
                    name = FILES.get(member.name)
                    if name is None: continue
                    if not member.isfile():
                        raise RuntimeError(f"Not a regular file: {member.name}")
                    src = tar.extractfile(member)
                    if src is None: raise RuntimeError(f"Cannot read {member.name}")
                    with (out / name).open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.add(member.name)
                    print(f"Extracted: {name}")
    missing = set(FILES) - found
    if missing: raise RuntimeError(f"Package is missing required files: {sorted(missing)}")
    archive.unlink()
    print("MSYS2 runtime extraction complete.")

if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
