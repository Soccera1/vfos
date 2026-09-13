"""Console-launched graphical sessions with scoped audio and descendant cleanup."""
from __future__ import annotations

import ctypes
import grp
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

from .common import Error


def descendants(pid):
    result = set()
    pending = [pid]
    while pending:
        parent = pending.pop()
        try:
            children = Path(f"/proc/{parent}/task/{parent}/children").read_text().split()
        except FileNotFoundError:
            continue
        for child in map(int, children):
            if child not in result:
                result.add(child)
                pending.append(child)
    return result


def terminate_children():
    # A subreaper adopts daemonized grandchildren, including applications launched
    # from the WM. Never kill all processes belonging to the desktop user.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in descendants(os.getpid()):
            try:
                fd = os.pidfd_open(pid)
                try:
                    signal.pidfd_send_signal(fd, sig)
                finally:
                    os.close(fd)
            except ProcessLookupError:
                pass
        if sig == signal.SIGTERM:
            time.sleep(0.3)
    while True:
        try:
            os.waitpid(-1, 0)
        except ChildProcessError:
            break


def run_child(desktop):
    audio = []
    try:
        for command in ("pipewire", "wireplumber", "pipewire-pulse"):
            audio.append(subprocess.Popen([command]))
        return subprocess.call([desktop])
    finally:
        for process in reversed(audio):
            process.terminate() if process.poll() is None else None
        for process in audio:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def launch(desktop):
    if desktop not in ("dwm", "dwl"):
        raise Error("desktop must be dwm or dwl")
    if os.getuid() == 0 or not sys.stdin.isatty():
        raise Error("start the desktop as an ordinary user from a console login")
    tty = os.ttyname(sys.stdin.fileno())
    import re
    if not re.fullmatch(r"/dev/tty[1-9][0-9]*", tty):
        raise Error("graphical sessions require a local virtual console")
    try:
        seat = grp.getgrnam("seat")
        info = Path("/run/seatd.sock").lstat()
    except (KeyError, FileNotFoundError):
        raise Error("seatd is unavailable; start its SysVinit service and log in again") from None
    if seat.gr_gid not in os.getgroups() or info.st_uid != 0 or info.st_gid != seat.gr_gid or not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o660:
        raise Error("seatd socket must be root:seat 0660; this login must belong to seat")
    needed = ("startx", "X", "dwm") if desktop == "dwm" else ("dwl",)
    for command in (*needed, "pipewire", "wireplumber", "pipewire-pulse", "dbus-run-session"):
        if not shutil.which(command):
            raise Error(f"missing session executable: {command}")
    # PR_SET_CHILD_SUBREAPER: own orphaned session processes until logout cleanup.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise Error("cannot establish session process supervision")
    runtime = tempfile.mkdtemp(prefix=f"vfos-{os.getuid()}-", dir="/tmp")
    os.chmod(runtime, 0o700)
    env = dict(os.environ, LIBSEAT_BACKEND="seatd", SEATD_SOCK="/run/seatd.sock", XDG_RUNTIME_DIR=runtime,
               XDG_SESSION_TYPE="x11" if desktop == "dwm" else "wayland", XDG_CURRENT_DESKTOP=desktop)
    child = ["/usr/libexec/vfos-session-child", desktop]
    if desktop == "dwm":
        command = ["startx", *child, "--", "/usr/bin/X", "-keeptty", "-nolisten", "tcp", tty[5:]]
    else:
        command = child
        env["MOZ_ENABLE_WAYLAND"] = "1"
    # Keep the inherited controlling terminal; never setsid() XLibre/dwl.
    command = ["dbus-run-session", "--", *command]
    previous = {}
    def stop(signum, frame):
        raise KeyboardInterrupt
    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            previous[sig] = signal.signal(sig, stop)
        return subprocess.call(command, env=env)
    finally:
        terminate_children()
        shutil.rmtree(runtime)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
