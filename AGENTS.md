# MO2 Agent Toolkit instructions

All agents must first run the loaded `mo2-mod-installer` Skill's `scripts/ensure-runtime.ps1 -Json`, then use only the absolute `tool_path` it returns for MO2 mutations. The bootstrap pins and verifies the matching Bundle; never use `latest`, `PATH`, a source `dist`, or a copied EXE. A bootstrap checksum/version failure is a hard stop. Start with `doctor --json`; use `setup --json` only when configuration is absent. Before writes, run planning/archive inspection and the matching `--dry-run --json`, summarize warnings, and obtain explicit confirmation. After a write, run `profile audit --json`. Never read or print the DPAPI credential file. Exit code 1 requires review; exit code 3 is a safety block and must not be bypassed.

See `skills/mo2-mod-installer/references/agent-contract.md` for the stable response contract.

SKSE and Engine Fixes root/AIO archives are exceptions: use `root inspect`, `root deploy --dry-run`, explicit confirmation, then `root deploy --yes`. Never send them through ordinary `install`; never bypass an unknown-signature safety block.
