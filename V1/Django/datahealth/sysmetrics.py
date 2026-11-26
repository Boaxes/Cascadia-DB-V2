"""
The machine's own numbers: processor, memory, disks, load and uptime.

Standard library only (the project takes no new packages). The server is Linux,
where these come from /proc; a Windows development machine gets the same
figures from the system's own calls so the Server Health page opens there too.
A figure the platform cannot give is None, and the page says "Not Available".
"""

import os
import shutil
import socket
import sys
import time

_LINUX = sys.platform.startswith("linux")
_WINDOWS = sys.platform == "win32"


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


def _linux_cpu_times():
    text = _read("/proc/stat")
    if not text:
        return None
    fields = [int(x) for x in text.splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)   # idle and iowait
    return sum(fields[:8]), idle


def _windows_cpu_times():
    import ctypes
    from ctypes import wintypes

    idle, kernel, user = (wintypes.FILETIME() for _ in range(3))
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None

    def ticks(t):
        return (t.dwHighDateTime << 32) | t.dwLowDateTime
    # Kernel time includes idle time.
    return ticks(kernel) + ticks(user), ticks(idle)


def cpu_times():
    """(busy plus idle, idle) counters, or None."""
    try:
        if _LINUX:
            return _linux_cpu_times()
        if _WINDOWS:
            return _windows_cpu_times()
    except (OSError, ValueError, AttributeError):
        pass
    return None


def cpu_percent(interval=0.25):
    """How busy the processor was over `interval` seconds, 0 to 100, or None."""
    first = cpu_times()
    if first is None:
        return None
    time.sleep(interval)
    second = cpu_times()
    total, idle = second[0] - first[0], second[1] - first[1]
    return round(100 * (total - idle) / total, 1) if total > 0 else 0.0


def load_average():
    """(1, 5, 15 minute load averages), or None where the system keeps none (Windows)."""
    try:
        return tuple(round(x, 2) for x in os.getloadavg())
    except (AttributeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def _linux_memory():
    info = {}
    for line in (_read("/proc/meminfo") or "").splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            info[name] = int(parts[0]) * 1024
    if "MemTotal" not in info:
        return None
    total = info["MemTotal"]
    available = info.get("MemAvailable", info.get("MemFree", 0))
    return {"total": total, "available": available, "used": total - available,
            "cached": info.get("Cached", 0) + info.get("Buffers", 0),
            "swap_total": info.get("SwapTotal", 0),
            "swap_used": info.get("SwapTotal", 0) - info.get("SwapFree", 0)}


def _windows_memory():
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                    ("page_total", ctypes.c_ulonglong), ("page_available", ctypes.c_ulonglong),
                    ("virtual_total", ctypes.c_ulonglong), ("virtual_available", ctypes.c_ulonglong),
                    ("extended", ctypes.c_ulonglong)]
    status = Status()
    status.length = ctypes.sizeof(Status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    # The page file's own figures are not reliable from here, so no swap is claimed.
    return {"total": status.total, "available": status.available, "used": status.total - status.available,
            "cached": 0, "swap_total": 0, "swap_used": 0}


def memory():
    """Memory in bytes: total, available, used, cached, and swap; plus percentages. Or None."""
    try:
        found = _linux_memory() if _LINUX else _windows_memory() if _WINDOWS else None
    except (OSError, ValueError, AttributeError):
        found = None
    if not found:
        return None
    found["percent"] = round(100 * found["used"] / found["total"], 1) if found["total"] else 0.0
    found["swap_percent"] = round(100 * found["swap_used"] / found["swap_total"], 1) if found["swap_total"] else None
    return found


# ---------------------------------------------------------------------------
# Uptime and disks
# ---------------------------------------------------------------------------


def uptime_seconds():
    try:
        if _LINUX:
            return float((_read("/proc/uptime") or "").split()[0])
        if _WINDOWS:
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.GetTickCount64.restype = ctypes.c_ulonglong
            return kernel.GetTickCount64() / 1000
    except (IndexError, ValueError, OSError, AttributeError):
        pass
    return None


def disks(paths):
    """[{label, path, total, used, free, percent}] for each (label, path), one per
    filesystem: two folders on the same disk are one line, named for the first."""
    out, seen = [], set()
    for label, path in paths:
        try:
            device = os.stat(path).st_dev
            if device in seen:
                continue
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        seen.add(device)
        out.append({"label": label, "path": str(path), "total": usage.total, "used": usage.used,
                    "free": usage.free, "percent": round(100 * usage.used / usage.total, 1) if usage.total else 0.0})
    return out


def snapshot(paths=(), interval=0.25):
    """Every live figure: what the page shows and what it asks for again every few seconds."""
    return {"taken": time.time(), "host": socket.gethostname(), "cpu_count": os.cpu_count() or 1,
            "cpu_percent": cpu_percent(interval), "load": load_average(), "memory": memory(),
            "uptime": uptime_seconds(), "disks": disks(paths)}
