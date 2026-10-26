#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remove stray files whose names are Windows reserved devices (nul, con, prn,
aux, com1..com9, lpt1..lpt9).

Where they come from
--------------------
A POSIX shell (git-bash, MSYS2, WSL) does not know about the Windows NUL device.
When such a shell runs a redirection like `2>nul` - e.g. by pasting a line from
one of the .bat files - the shell creates a *real* file named `nul` and writes
the command's stderr into it. Windows then resolves the name to the device, so
`del nul` / `rm nul` / PowerShell `Remove-Item` all appear to do nothing; only a
path with the `\\\\?\\` prefix reaches the real file.

This helper is safe to run repeatedly: it only touches files inside the project
directory whose stem is a reserved device name.
"""

import os
import sys

RESERVED = ({"nul", "con", "prn", "aux"}
            | {"com%d" % i for i in range(1, 10)}
            | {"lpt%d" % i for i in range(1, 10)})


def clean_reserved_names(base_dir):
    """Delete reserved-name strays in base_dir. Returns the removed names."""
    removed = []
    if os.name != "nt":
        return removed
    backslash = chr(92)
    try:
        entries = os.listdir(base_dir)
    except OSError:
        return removed
    for name in entries:
        stem = name.split(".")[0].strip().lower()
        if stem not in RESERVED:
            continue
        # Only the \\?\ prefix reaches a file whose name is a device name.
        target = backslash + backslash + "?" + backslash + os.path.join(base_dir, name)
        try:
            os.remove(target)
            removed.append(name)
        except OSError:
            pass
    return removed


def main(argv=None):
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    removed = clean_reserved_names(project_dir)
    if removed:
        print("Removed stray reserved-name file(s): %s" % ", ".join(removed))
    else:
        print("No stray reserved-name files found in %s" % project_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
