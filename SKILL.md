---
name: mo2-mod-installer
description: Safely inspect, plan, install, update, validate, archive, back up, or restore Skyrim SE/AE mods in Mod Organizer 2 from a directly cloned Claude Skill repository.
---

# MO2 Mod Installer Repository Adapter

This repository keeps the authoritative Skill at `skills/mo2-mod-installer/SKILL.md`.

Before handling an MO2 request:

1. Resolve this root `SKILL.md` to an absolute path.
2. Read `skills/mo2-mod-installer/SKILL.md` relative to this repository root.
3. Follow that nested Skill as the authoritative workflow, including its runtime bootstrap. Resolve all of its relative paths from `skills/mo2-mod-installer`, not from the shell working directory.

Do not duplicate or reconstruct the nested workflow, and do not search for another `mo2-tool` on `PATH`.
