"""Read-only dependency controller; only explicit setup actions call this file."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

REPO = Path("/work/repo")
ACQUIRED = Path("/work/acquired")
MAX_PACKAGE_FILES = 50_000
DEPS = Path("/work/deps")


def _path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts or "\x00" in name:
        raise ValueError("Invalid dependency archive path")
    return path


def _protect_controller() -> None:
    # Same-UID children must not reopen this process's stdout via /proc and
    # forge command evidence, or modify its memory with ptrace. This controller
    # always runs in Linux, and unsupported protection is a hard blocker.
    library = ctypes.CDLL(None, use_errno=True)
    library.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    library.prctl.restype = ctypes.c_int
    if library.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE, SUID_DUMP_DISABLE
        raise OSError(ctypes.get_errno(), "Unable to protect coding controller descriptors")


def _package_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/work/tmp/home", "TMPDIR": "/work/tmp",
        "PIP_CONFIG_FILE": "/dev/null", "UV_CACHE_DIR": "/work/tmp/uv", "UV_PYTHON": "/usr/local/bin/python",
    }


def _package_command(argv: list[str]) -> None:
    subprocess.run(argv, cwd=REPO, env=_package_environment(), check=True, stdin=subprocess.DEVNULL)


def _export_python_requirements() -> None:
    ACQUIRED.mkdir(exist_ok=True)
    constraints = ["--offline", "--no-config", "--no-build", "--no-python-downloads", "--no-cache"]
    _package_command(["uv", "lock", "--check", "--python", "/usr/local/bin/python", *constraints])
    _package_command([
        "uv", "export", "--frozen", *constraints, "--format", "requirements.txt",
        "--no-emit-local", "--no-emit-project", "--no-emit-workspace", "--all-groups",
        "--no-header", "--no-annotate", "--output-file", str(ACQUIRED / "requirements.txt"),
    ])


def _acquire_python() -> None:
    ACQUIRED.mkdir(exist_ok=True)
    if not (ACQUIRED / "requirements.txt").exists():
        shutil.copyfile(REPO / "requirements.txt", ACQUIRED / "requirements.txt")
    _package_command([
        "/usr/local/bin/python", "-I", "-m", "pip", "--isolated", "--disable-pip-version-check",
        "--no-cache-dir", "download", "--index-url", "https://pypi.org/simple",
        "--only-binary=:all:", "--require-hashes", "--no-deps", "--dest", str(ACQUIRED / "wheels"),
        "-r", str(ACQUIRED / "requirements.txt"),
    ])


def _acquire_node() -> None:
    for name in ("empty-user.npmrc", "empty-global.npmrc"):
        Path("/work/tmp", name).write_text("")
    _package_command([
        "npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--engine-strict",
        "--registry=https://registry.npmjs.org", "--cache=/work/tmp/npm",
        "--userconfig=/work/tmp/empty-user.npmrc", "--globalconfig=/work/tmp/empty-global.npmrc",
    ])


def _package_export(kind: str, max_bytes: int) -> None:
    if kind not in {"python", "node"}:
        raise ValueError("Unknown dependency kind")
    root = ACQUIRED if kind == "python" else REPO
    selected = [ACQUIRED / "requirements.txt", ACQUIRED / "wheels"] if kind == "python" else [REPO / "node_modules"]
    files: list[tuple[Path, os.stat_result]] = []
    total = 0

    def add(path: Path) -> None:
        nonlocal total
        info = path.lstat()
        total += info.st_size if stat.S_ISREG(info.st_mode) else 0
        if len(files) >= MAX_PACKAGE_FILES or total > max_bytes or stat.S_IMODE(info.st_mode) & 0o7000:
            raise ValueError("Package export exceeds its inventory or storage limit")
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise ValueError("Package export refuses hardlinks and special files")
        files.append((path, info))

    visited = 0
    for selected_path in selected:
        if not selected_path.is_dir() or selected_path.is_symlink():
            add(selected_path)
            continue
        for directory, names, filenames in os.walk(selected_path, followlinks=False):
            visited += len(names) + len(filenames)
            if visited > MAX_PACKAGE_FILES:
                raise ValueError("Package export exceeds its inventory limit")
            for name in tuple(names):
                candidate = Path(directory) / name
                if candidate.is_symlink():
                    add(candidate)
                    names.remove(name)
            for name in sorted(filenames):
                add(Path(directory) / name)
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|", format=tarfile.PAX_FORMAT) as archive:
        for path, info in files:
            member = tarfile.TarInfo(path.relative_to(root).as_posix())
            member.mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                member.type, member.linkname = tarfile.SYMTYPE, os.readlink(path)
                archive.addfile(member)
            else:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as reader:
                    member.size = os.fstat(reader.fileno()).st_size
                    archive.addfile(member, reader)


def _package_import(kind: str, max_bytes: int) -> None:
    if kind not in {"python", "node"}:
        raise ValueError("Unknown dependency kind")
    destination = ACQUIRED if kind == "python" else Path("/work/deps/node")
    if destination.is_symlink():
        destination.unlink()
    elif destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    total = 0
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
        for index, member in enumerate(archive):
            total += member.size
            if index >= MAX_PACKAGE_FILES or total > max_bytes or member.size < 0:
                raise ValueError("Package import exceeds its resource limit")
            _path(member.name)
            archive.extract(member, destination, filter="data")
    if kind == "python":
        target = Path("/work/deps/python")
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        _package_command([
            "/usr/local/bin/python", "-I", "-m", "pip", "--isolated", "--disable-pip-version-check",
            "--no-cache-dir", "install", "--no-index", "--only-binary=:all:", "--require-hashes",
            "--no-deps", "--no-compile", "--find-links", str(ACQUIRED / "wheels"),
            "--target", str(target), "-r", str(ACQUIRED / "requirements.txt"),
        ])
        shutil.rmtree(ACQUIRED)
    else:
        local = REPO / "node_modules"
        if local.is_symlink():
            local.unlink()
        elif local.exists():
            shutil.rmtree(local)
        local.symlink_to(destination / "node_modules", target_is_directory=True)


def _dependency_identity(max_bytes: int) -> str:
    """Fingerprint the installed environment, including later offline builds."""
    if DEPS.is_symlink() or not DEPS.is_dir():
        raise ValueError("Invalid installed dependency root")
    digest = hashlib.sha256()
    total = 0
    visited = 0
    for directory, names, files in os.walk(DEPS, followlinks=False):
        names.sort()
        visited += len(names) + len(files)
        if visited > MAX_PACKAGE_FILES:
            raise ValueError("Installed dependencies exceed the inventory limit")
        for name in sorted([*names, *files]):
            path = Path(directory) / name
            relative = path.relative_to(DEPS).as_posix()
            info = path.lstat()
            mode = stat.S_IMODE(info.st_mode)
            if mode & 0o7000:
                raise ValueError("Installed dependencies carry unsupported permission bits")
            if stat.S_ISLNK(info.st_mode):
                if not path.resolve().is_relative_to(DEPS):
                    raise ValueError("Installed dependency symlinks escape their root")
                content_hash = "link:" + os.readlink(path)
            elif stat.S_ISDIR(info.st_mode):
                content_hash = "directory"
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                total += info.st_size
                if total > max_bytes:
                    raise ValueError("Installed dependencies exceed the storage limit")
                content = hashlib.sha256()
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    if (before.st_dev, before.st_ino, before.st_size) != (info.st_dev, info.st_ino, info.st_size):
                        raise ValueError("Installed dependency changed during inspection")
                    for chunk in iter(lambda: stream.read(262_144), b""):
                        content.update(chunk)
                    after = os.fstat(stream.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("Installed dependency changed during inspection")
                content_hash = content.hexdigest()
            else:
                raise ValueError("Installed dependencies refuse hardlinks and special files")
            digest.update(json.dumps([relative, mode, content_hash], separators=(",", ":")).encode() + b"\n")
    return digest.hexdigest()


def main() -> None:
    _protect_controller()
    action = sys.argv[1]
    if action == "export-python-requirements":
        _export_python_requirements()
    elif action == "read-requirements":
        sys.stdout.buffer.write((ACQUIRED / "requirements.txt").read_bytes())
    elif action == "set-requirements":
        ACQUIRED.mkdir(exist_ok=True)
        contents = sys.stdin.buffer.read(5 * 1024 * 1024 + 1)
        if len(contents) > 5 * 1024 * 1024:
            raise ValueError("Requirements exceed their size bound")
        (ACQUIRED / "requirements.txt").write_bytes(contents)
    elif action == "acquire-python":
        _acquire_python()
    elif action == "acquire-node":
        _acquire_node()
    elif action == "package-export":
        _package_export(sys.argv[2], int(sys.argv[3]))
    elif action == "package-import":
        _package_import(sys.argv[2], int(sys.argv[3]))
    elif action == "dependency-identity":
        print(_dependency_identity(int(sys.argv[2])))
    else:
        raise ValueError("Unknown setup action")


if __name__ == "__main__":
    main()
