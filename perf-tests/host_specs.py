"""Collect host/environment specs so perf-test results are attributable.

Best-effort: every field is wrapped so a missing tool (e.g. no `docker` on
PATH from inside a container) degrades to null rather than crashing the run.
"""
import json
import platform
import shutil
import subprocess


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _powershell(script):
    if not shutil.which("powershell") and not shutil.which("powershell.exe"):
        return None
    return _run(["powershell", "-NoProfile", "-Command", script])


def collect():
    specs = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
    }

    cpu_count = _powershell(
        "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"
    )
    specs["logical_processors"] = int(cpu_count) if cpu_count and cpu_count.isdigit() else None

    mem_bytes = _powershell(
        "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"
    )
    if mem_bytes and mem_bytes.isdigit():
        specs["total_physical_memory_gb"] = round(int(mem_bytes) / (1024 ** 3), 1)
    else:
        specs["total_physical_memory_gb"] = None

    cpu_model = _powershell("(Get-CimInstance Win32_Processor).Name")
    specs["cpu_model"] = cpu_model

    system_model = _powershell(
        "(Get-CimInstance Win32_ComputerSystem).Model + ' / ' + (Get-CimInstance Win32_ComputerSystem).Manufacturer"
    )
    specs["system_model"] = system_model

    docker_version = _run(["docker", "version", "--format", "{{.Server.Version}}"])
    specs["docker_server_version"] = docker_version

    docker_resources = _run(
        ["docker", "info", "--format", "{{.NCPU}} CPUs / {{.MemTotal}} bytes RAM allocated to Docker"]
    )
    specs["docker_resources"] = docker_resources

    mysql_version = _run(
        ["docker", "compose", "exec", "-T", "db", "mysql", "--version"]
    )
    specs["mysql_version"] = mysql_version

    server_python_version = _run(
        ["docker", "compose", "exec", "-T", "server", "python3", "-c", "import platform; print(platform.python_version())"]
    )
    specs["server_container_python_version"] = server_python_version

    return specs


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
