"""Checks that the Python running the workspace is one the pinned tools support, and says so in plain words if it is not.

The pins in constraints.txt were chosen for Python 3.12 and 3.13 on 64-bit systems. An older Python is refused by several pinned
packages (NumPy 2.5 needs 3.12 or newer); a newer one has no ready-made files for some of them yet (pyarrow has none for 3.14's
free-threaded build or for 3.15), so pip would try to compile them and fail with a wall of build errors.
"""

from __future__ import annotations

import struct
import sys
import sysconfig

SUPPORTED = ((3, 12), (3, 13))


def summary() -> str:
    bits = struct.calcsize("P") * 8
    return f"Python {sys.version.split()[0]} ({bits}-bit, {sysconfig.get_platform()})"


def problems_with(version: tuple[int, int] | None = None, bits: int | None = None, free_threaded: bool | None = None) -> list[str]:
    """What is wrong with this Python for the workspace, as plain sentences. An empty list means it is fine."""
    version = version or (sys.version_info.major, sys.version_info.minor)
    bits = bits or struct.calcsize("P") * 8
    if free_threaded is None:
        free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    wanted = " or ".join(f"{major}.{minor}" for major, minor in SUPPORTED)
    found = []
    if version not in SUPPORTED:
        found.append(
            f"Python {version[0]}.{version[1]} is not supported. Use Python {wanted}"
            + (" (the tools need 3.12 or newer)." if version < SUPPORTED[0] else " (some tools have no ready-made files for newer versions yet, so pip would try to compile them).")
        )
    if bits != 64:
        found.append("This is a 32-bit Python. Use the 64-bit one.")
    if free_threaded:
        found.append("This is a free-threaded build of Python. Use the normal build.")
    return found


def main() -> int:
    print(summary())
    problems = problems_with()
    if problems:
        print("Not usable for the ML workspace:")
        for problem in problems:
            print(f"  - {problem}")
        print("\nCreate the environment with a supported Python, for example:  py -3.13 -m venv .venv")
        return 1
    print("ok: this Python can run the workspace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
