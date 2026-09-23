"""Heurísticas de nombre y extracción de perfiles desde JSON de proveedores (PDL, etc.)."""
from __future__ import annotations

import re
from typing import Any

_PROFILE_HINT = re.compile(
    r"https?://[^\s\"'<>]+(?:linkedin\.com/in/|linkedin\.com/pub/)[^\s\"'<>]*",
    re.IGNORECASE,
)


def split_person_name(full_name: str) -> tuple[str | None, str | None, str | None]:
    parts = full_name.strip().split()
    if not parts:
        return None, None, None
    if len(parts) == 1:
        return None, None, parts[0]
    last = parts[-1]
    first = " ".join(parts[:-1])
    return first, last, None


def extract_profile_urls(payload: Any, *, max_urls: int = 8) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def maybe_add(u: str) -> None:
        u = u.strip()
        if not u or u in seen:
            return
        if not u.startswith("http"):
            return
        low = u.lower()
        if ("linkedin.com" in low and ("/in/" in low or "/pub/" in low)) or "linkedin.com" in low:
            seen.add(u)
            found.append(u)

    def walk(obj: Any) -> None:
        if len(found) >= max_urls:
            return
        if isinstance(obj, str):
            for m in _PROFILE_HINT.finditer(obj):
                maybe_add(m.group(0))
            return
        if isinstance(obj, dict):
            for key, val in obj.items():
                lk = str(key).lower()
                if lk in (
                    "url",
                    "profileurl",
                    "profile_url",
                    "publicprofileurl",
                    "link",
                    "linkedinurl",
                    "linkedin_url",
                    "linkedin",
                ) and isinstance(val, str):
                    maybe_add(val)
                walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    return found[:max_urls]
