import platform
import subprocess

_os_cache: str | None = None


def get_goarch():
    arch = platform.machine().lower()

    # Mapping common platform.machine() outputs to GOARCH values
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "i386": "386",
        "i686": "386",
        "x86": "386",
        "arm64": "arm64",
        "aarch64": "arm64",
        "armv7l": "arm",
        "armv6l": "arm",
        "ppc64le": "ppc64le",
        "ppc64": "ppc64",
        "mips": "mips",
        "mipsle": "mipsle",
        "mips64": "mips64",
        "mips64le": "mips64le",
        "s390x": "s390x",
    }

    goarch = arch_map.get(arch)
    if not goarch:
        raise ValueError(f"Unsupported architecture: {arch}")
    return goarch


def get_rust_arch():
    """
    Returns the system architecture string similar to Rust's arch naming.
    Examples: 'x86_64', 'aarch64', 'arm', 'i386', etc.
    """
    machine = platform.machine().lower()

    # Normalize common architecture names to Rust-like arch strings
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    elif machine in ("i386", "i686", "x86"):
        return "x86"
    elif machine.startswith("armv7") or machine == "arm":
        return "arm"
    elif machine.startswith("aarch64") or machine == "arm64":
        return "aarch64"
    elif machine.startswith("ppc64"):
        return "powerpc64"
    elif machine.startswith("ppc"):
        return "powerpc"
    else:
        return machine  # fallback to whatever platform.machine() returns


def get_os() -> str:
    global _os_cache
    if _os_cache is None:
        _os_cache = subprocess.check_output(["uname", "-s"], text=True).strip().lower()
    return _os_cache
