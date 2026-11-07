---
name: secretary-release
description: Use when building, smoke-testing, packaging, or releasing. Covers the one-folder PyInstaller build, Inno installer, checksums, and release notes.
---
1. Data files: `tzdata`, vendored tiktoken `cl100k_base` encoding file, `migrations/`, QSS/theme assets.
2. Build the one-folder exe; test the built exe path (not only dev), including `--diagnose` and `--minimized`.
3. Toasts need an AUMID shortcut; confirm toast from the packaged exe. Simulated notifier failure must leave the inbox and popup intact.
4. Inno Setup installer (`packaging/installer.iss`) registers the Run-key value `Secretary` under `HKCU`; toggle off removes it.
5. Generate checksums; do not use UPX; code sign if available (else document unsigned status).
6. Run the manual test script for the phase; record results in `docs/progress.md`.
