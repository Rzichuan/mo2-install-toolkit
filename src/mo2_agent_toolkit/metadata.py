from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


class MetadataError(ValueError):
    pass


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _reject_controls(text: str) -> None:
    invalid = sorted({ord(char) for char in text if ord(char) < 32 and char not in "\t\r\n"})
    if invalid:
        rendered = ", ".join(f"U+{value:04X}" for value in invalid)
        raise MetadataError(f"meta.ini contains invalid control characters: {rendered}")


def _section_bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    wanted = f"[{section}]".casefold()
    start = next((index for index, line in enumerate(lines) if line.strip().casefold() == wanted), None)
    if start is None:
        return None
    end = next((index for index in range(start + 1, len(lines)) if lines[index].strip().startswith("[")), len(lines))
    return start, end


def _set_value(lines: list[str], section: str, key: str, value: str) -> None:
    bounds = _section_bounds(lines, section)
    if bounds is None:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend([f"[{section}]", f"{key}={value}"])
        return
    start, end = bounds
    matches = [
        index for index in range(start + 1, end)
        if "=" in lines[index] and lines[index].split("=", 1)[0].strip().casefold() == key.casefold()
    ]
    if matches:
        lines[matches[0]] = f"{key}={value}"
        for index in reversed(matches[1:]):
            del lines[index]
    else:
        lines.insert(end, f"{key}={value}")


def _remove_installed_identity(lines: list[str]) -> None:
    bounds = _section_bounds(lines, "installedFiles")
    if bounds is None:
        return
    start, end = bounds
    identity = re.compile(r"^\s*(?:size|\d+\\(?:modid|fileid))\s*=", re.IGNORECASE)
    for index in reversed(range(start + 1, end)):
        if identity.match(lines[index]):
            del lines[index]


def _value(lines: list[str], section: str, key: str) -> str | None:
    bounds = _section_bounds(lines, section)
    if bounds is None:
        return None
    start, end = bounds
    values = [
        line.split("=", 1)[1].strip() for line in lines[start + 1:end]
        if "=" in line and line.split("=", 1)[0].strip().casefold() == key.casefold()
    ]
    if len(values) > 1:
        raise MetadataError(f"meta.ini has duplicate [{section}] {key} entries")
    return values[0] if values else None


def validate_meta_ini(path: Path, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    text = _read(path)
    _reject_controls(text)
    lines = text.splitlines()
    result: dict[str, Any] = {"path": str(path), "valid": True}
    if expected and expected.get("provider") == "nexus":
        required = {
            ("General", "modid"): str(expected["mod_id"]),
            ("General", "version"): str(expected.get("version") or ""),
            ("General", "newestVersion"): str(expected.get("version") or ""),
            ("General", "installationFile"): str(expected["official_filename"]),
            ("installedFiles", r"1\modid"): str(expected["mod_id"]),
            ("installedFiles", r"1\fileid"): str(expected["file_id"]),
            ("installedFiles", "size"): "1",
        }
        if expected.get("last_modified"):
            required[("General", "nexusLastModified")] = str(expected["last_modified"])
        mismatches = []
        for (section, key), wanted in required.items():
            actual = _value(lines, section, key)
            if actual != wanted:
                mismatches.append({"section": section, "key": key, "expected": wanted, "actual": actual})
        if mismatches:
            raise MetadataError(f"meta.ini does not match the installation plan: {mismatches}")
        result.update(mod_id=int(expected["mod_id"]), file_id=int(expected["file_id"]),
                      version=str(expected.get("version") or ""), official_filename=str(expected["official_filename"]))
    return result


def prepare_meta_ini(staged: Path, existing: Path | None, source_metadata: dict[str, Any] | None) -> dict[str, Any]:
    target = staged / "meta.ini"
    source_metadata = source_metadata or {}
    if existing and existing.is_file():
        base = _read(existing)
        action = "merged" if source_metadata.get("provider") == "nexus" else "preserved"
    elif source_metadata.get("provider") == "nexus":
        base = "[General]\n"
        action = "created"
    elif target.is_file():
        validate_meta_ini(target)
        return {"action": "archive_preserved", "path": str(target), "validated": True}
    else:
        return {"action": "none", "path": None, "validated": True}

    _reject_controls(base)
    if source_metadata.get("provider") != "nexus":
        target.write_text(base, encoding="utf-8", newline="\n")
        validate_meta_ini(target)
        return {"action": action, "path": str(target), "validated": True}

    lines = base.splitlines()
    fields = {
        "modid": str(source_metadata["mod_id"]),
        "version": str(source_metadata.get("version") or ""),
        "newestVersion": str(source_metadata.get("version") or ""),
        "installationFile": str(source_metadata["official_filename"]),
    }
    if source_metadata.get("last_modified"):
        fields["nexusLastModified"] = str(source_metadata["last_modified"])
    for key, value in fields.items():
        _set_value(lines, "General", key, value)
    _remove_installed_identity(lines)
    _set_value(lines, "installedFiles", "size", "1")
    _set_value(lines, "installedFiles", r"1\modid", str(source_metadata["mod_id"]))
    _set_value(lines, "installedFiles", r"1\fileid", str(source_metadata["file_id"]))
    rendered = "\n".join(lines).rstrip("\n") + "\n"
    _reject_controls(rendered)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    os.replace(temporary, target)
    validation = validate_meta_ini(target, source_metadata)
    return {"action": action, "path": str(target), "validated": True, "audit": validation}
