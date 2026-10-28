"""`gndcrw-code-digest/v0.2`: the running tool's self-reported code identity.

RESULT_CONTRACT_V0_2 §4.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from gndcrw.jsonio import digest


def code_digest(package_root: Path | None = None) -> str:
    """SHA-256 over canonical {"files":[{"path","sha256"}]} of every .py/.json package file."""
    root = package_root or Path(__file__).resolve().parent
    files = []
    for path in root.rglob("*"):
        if "__pycache__" in path.relative_to(root).parts:
            continue
        if path.is_file() and path.suffix in (".py", ".json"):
            files.append({"path": path.relative_to(root).as_posix(),
                          "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()})
    files.sort(key=lambda entry: entry["path"])
    return digest({"files": files})
