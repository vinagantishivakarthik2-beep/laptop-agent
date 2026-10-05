"""
system_tools.py
----------------
All the "hands" of the agent: real functions that inspect the Windows
machine and return plain data. Claude never touches the OS directly —
it only calls these functions through the tool-use interface defined
in TOOL_DEFINITIONS, and we run whatever it asks for.

Every function returns a JSON-serializable dict so it can be dropped
straight into a tool_result block.
"""

import platform
import subprocess
import shutil
import os
import datetime
import json

import psutil


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_powershell(command: str, timeout: int = 20) -> str:
    """Run a PowerShell command and return stdout as text. Never raises —
    returns an error string instead, so the agent can still respond."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0 and not result.stdout.strip():
            return f"ERROR: {result.stderr.strip()[:500]}"
        return result.stdout.strip()
    except FileNotFoundError:
        return "ERROR: PowerShell not found. Is this running on Windows?"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out"
    except Exception as e:
        return f"ERROR: {e}"


def _bytes_to_gb(n: int) -> float:
    return round(n / (1024 ** 3), 2)


def _folder_size_bytes(path: str, max_seconds: float = 6.0) -> int:
    """Best-effort folder size. Bails out early on huge folders so the
    agent stays responsive rather than walking an entire drive."""
    import time
    start = time.time()
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        if time.time() - start > max_seconds:
            break
        for f in filenames:
            try:
                fp = os.path.join(dirpath, f)
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def get_disk_space(drive: str = "all") -> dict:
    """Free/used/total space per drive letter, or a specific one."""
    results = []
    for part in psutil.disk_partitions(all=False):
        letter = part.device.rstrip("\\")
        if drive.lower() != "all" and not letter.lower().startswith(drive.lower().rstrip(":\\").rstrip(":")):
            continue
        try:
            usage = shutil.disk_usage(part.mountpoint)
            results.append({
                "drive": letter,
                "filesystem": part.fstype,
                "total_gb": _bytes_to_gb(usage.total),
                "used_gb": _bytes_to_gb(usage.used),
                "free_gb": _bytes_to_gb(usage.free),
                "percent_used": round(usage.used / usage.total * 100, 1) if usage.total else None,
            })
        except (PermissionError, OSError):
            continue
    return {"drives": results}


def get_cpu_info() -> dict:
    """Processor name, physical/logical cores, current usage, max clock speed."""
    name = _run_powershell(
        "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"
    )
    max_clock = _run_powershell(
        "(Get-CimInstance Win32_Processor | Select-Object -First 1).MaxClockSpeed"
    )
    return {
        "name": name if not name.startswith("ERROR") else platform.processor(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "max_clock_mhz": max_clock if not max_clock.startswith("ERROR") else "unknown",
        "current_usage_percent": psutil.cpu_percent(interval=0.5),
    }


def get_memory_info() -> dict:
    """RAM total/used/free, plus swap."""
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "total_gb": _bytes_to_gb(vm.total),
        "available_gb": _bytes_to_gb(vm.available),
        "used_gb": _bytes_to_gb(vm.used),
        "percent_used": vm.percent,
        "swap_total_gb": _bytes_to_gb(swap.total),
        "swap_used_gb": _bytes_to_gb(swap.used),
    }


def get_system_overview() -> dict:
    """OS name/version/build, machine name, architecture, boot time."""
    boot_ts = psutil.boot_time()
    boot_time = datetime.datetime.fromtimestamp(boot_ts).strftime("%Y-%m-%d %H:%M:%S")
    manufacturer = _run_powershell(
        "(Get-CimInstance Win32_ComputerSystem).Manufacturer"
    )
    model = _run_powershell(
        "(Get-CimInstance Win32_ComputerSystem).Model"
    )
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "machine_name": platform.node(),
        "manufacturer": manufacturer if not manufacturer.startswith("ERROR") else "unknown",
        "model": model if not model.startswith("ERROR") else "unknown",
        "last_boot_time": boot_time,
    }


def get_gpu_info() -> dict:
    """Graphics card name(s) and driver version."""
    raw = _run_powershell(
        "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM | ConvertTo-Json"
    )
    if raw.startswith("ERROR"):
        return {"error": raw}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        gpus = []
        for g in data:
            ram_gb = _bytes_to_gb(g["AdapterRAM"]) if g.get("AdapterRAM") else None
            gpus.append({
                "name": g.get("Name"),
                "driver_version": g.get("DriverVersion"),
                "vram_gb": ram_gb,
            })
        return {"gpus": gpus}
    except (json.JSONDecodeError, KeyError):
        return {"raw": raw}


def get_windows_update_info() -> dict:
    """When Windows was last updated: most recent installed hotfixes/updates,
    plus the original OS install date."""
    hotfix_raw = _run_powershell(
        "Get-HotFix | Sort-Object InstalledOn -Descending | "
        "Select-Object -First 5 HotFixID,Description,InstalledOn | ConvertTo-Json"
    )
    install_date_raw = _run_powershell(
        "(Get-CimInstance Win32_OperatingSystem).InstallDate"
    )

    recent_updates = []
    if not hotfix_raw.startswith("ERROR") and hotfix_raw:
        try:
            data = json.loads(hotfix_raw)
            if isinstance(data, dict):
                data = [data]
            recent_updates = [
                {"id": h.get("HotFixID"), "description": h.get("Description"),
                 "installed_on": h.get("InstalledOn")}
                for h in data
            ]
        except json.JSONDecodeError:
            recent_updates = [{"raw": hotfix_raw}]

    return {
        "recent_updates": recent_updates,
        "os_install_date": install_date_raw if not install_date_raw.startswith("ERROR") else "unknown",
        "note": "recent_updates lists the last installed hotfixes/patches; "
                "os_install_date is when Windows was originally installed on this machine.",
    }


def get_battery_info() -> dict:
    """Battery percentage and charging status, if a battery exists (laptops)."""
    batt = psutil.sensors_battery()
    if batt is None:
        return {"has_battery": False}
    return {
        "has_battery": True,
        "percent": batt.percent,
        "plugged_in": batt.power_plugged,
        "minutes_remaining": None if batt.secsleft in (psutil.POWER_TIME_UNLIMITED, -1) else round(batt.secsleft / 60),
    }


def get_cleanup_report() -> dict:
    """Estimates reclaimable space: temp folders, recycle bin, downloads.
    Gives concrete, actionable cleanup suggestions with rough size estimates."""
    user_temp = os.environ.get("TEMP", "")
    win_temp = r"C:\Windows\Temp"
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")

    findings = []

    if user_temp and os.path.isdir(user_temp):
        size = _folder_size_bytes(user_temp)
        findings.append({"location": user_temp, "type": "User temp files",
                          "estimated_size_gb": _bytes_to_gb(size),
                          "action": "Safe to delete via Disk Cleanup or manually (close apps first)."})

    if os.path.isdir(win_temp):
        size = _folder_size_bytes(win_temp)
        findings.append({"location": win_temp, "type": "Windows temp files",
                          "estimated_size_gb": _bytes_to_gb(size),
                          "action": "Safe to clear via Disk Cleanup (may need admin rights)."})

    if os.path.isdir(downloads):
        size = _folder_size_bytes(downloads)
        findings.append({"location": downloads, "type": "Downloads folder",
                          "estimated_size_gb": _bytes_to_gb(size),
                          "action": "Review manually — often has large old installers/files worth deleting."})

    recycle_bin_raw = _run_powershell(
        "$sh = New-Object -ComObject Shell.Application; "
        "$rb = $sh.Namespace(10); "
        "($rb.Items() | Measure-Object -Property Size -Sum).Sum"
    )
    recycle_bin_gb = None
    if not recycle_bin_raw.startswith("ERROR") and recycle_bin_raw.strip().isdigit():
        recycle_bin_gb = _bytes_to_gb(int(recycle_bin_raw.strip()))
        findings.append({"location": "Recycle Bin", "type": "Deleted files",
                          "estimated_size_gb": recycle_bin_gb,
                          "action": "Empty the Recycle Bin if you don't need these files back."})

    general_tips = [
        "Run 'Disk Cleanup' (search it in Start menu) and check 'system files' too — "
        "it can remove old Windows Update leftovers that are otherwise hard to find.",
        "Enable Storage Sense (Settings > System > Storage) to auto-clean temp files and the recycle bin on a schedule.",
        "Check Settings > Apps for large programs you no longer use.",
        "Use 'Settings > System > Storage > Temporary files' for a built-in breakdown by category.",
        "If OneDrive/Dropbox sync is on, consider 'Free up space' (Files On-Demand) to keep cloud files off local disk.",
    ]

    total_reclaimable = round(sum(f["estimated_size_gb"] for f in findings), 2)

    return {
        "findings": findings,
        "estimated_total_reclaimable_gb": total_reclaimable,
        "general_tips": general_tips,
    }


def get_startup_programs() -> dict:
    """Programs configured to launch at startup — often a source of slow boot times."""
    raw = _run_powershell(
        "Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location | ConvertTo-Json"
    )
    if raw.startswith("ERROR") or not raw:
        return {"error": raw or "no data returned"}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        return {"startup_programs": [
            {"name": p.get("Name"), "command": p.get("Command"), "location": p.get("Location")}
            for p in data
        ]}
    except json.JSONDecodeError:
        return {"raw": raw}


# ---------------------------------------------------------------------------
# Tool registry — dispatch table + Claude tool schema
# ---------------------------------------------------------------------------

TOOL_FUNCTIONS = {
    "get_disk_space": get_disk_space,
    "get_cpu_info": get_cpu_info,
    "get_memory_info": get_memory_info,
    "get_system_overview": get_system_overview,
    "get_gpu_info": get_gpu_info,
    "get_windows_update_info": get_windows_update_info,
    "get_battery_info": get_battery_info,
    "get_cleanup_report": get_cleanup_report,
    "get_startup_programs": get_startup_programs,
}

TOOL_DEFINITIONS = [
    {
        "name": "get_disk_space",
        "description": "Get free/used/total disk space for one or all drives (e.g. C:, D:).",
        "input_schema": {
            "type": "object",
            "properties": {
                "drive": {
                    "type": "string",
                    "description": "Drive letter like 'D' or 'D:', or 'all' for every drive. Defaults to 'all'.",
                }
            },
        },
    },
    {
        "name": "get_cpu_info",
        "description": "Get the processor name/model, core counts, clock speed, and current CPU usage.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_memory_info",
        "description": "Get RAM total/used/available and swap usage.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_system_overview",
        "description": "Get general laptop configuration: OS version/build, manufacturer, model, "
                        "architecture, machine name, and last boot time.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_gpu_info",
        "description": "Get graphics card (GPU) name, driver version, and VRAM.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_windows_update_info",
        "description": "Get when Windows was last updated: recent installed patches/hotfixes "
                        "and the original OS install date.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_battery_info",
        "description": "Get battery charge percentage, charging status, and estimated time remaining.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_cleanup_report",
        "description": "Analyze temp folders, Downloads, and Recycle Bin to estimate reclaimable "
                        "disk space, and give concrete cleanup suggestions/tips.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_startup_programs",
        "description": "List programs configured to launch automatically at Windows startup.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def call_tool(name: str, tool_input: dict) -> dict:
    """Dispatch a tool call by name. Returns a dict; never raises."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(**tool_input) if tool_input else fn()
    except Exception as e:
        return {"error": str(e)}
