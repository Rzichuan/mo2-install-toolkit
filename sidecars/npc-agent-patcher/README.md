# NPC Agent Patcher sidecar

This in-repository .NET 8 project builds the private `NpcAgentPatcher.exe` sidecar embedded by PyInstaller. It is invoked only through MO2 Agent Toolkit's versioned protocol; end users do not run or build it separately.

The project uses Mutagen.Bethesda 0.31.0 and Newtonsoft.Json 13.0.4. See the repository `THIRD_PARTY_NOTICES.md` and `third_party/` for licensing.
