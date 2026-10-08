# Security

feedready runs on your machine: `setup.sh` builds a Python venv, compiles the Swift engine with `swiftc`, and pulls ONNX models from Hugging Face; the scripts themselves edit photos locally.

## Reporting a vulnerability

Report privately at [github.com/dataguyofprocol/feedready/security/advisories/new](https://github.com/dataguyofprocol/feedready/security/advisories/new), not in a public issue. Say how to reproduce it and which `version` from `.claude-plugin/plugin.json` you're on.

## Scope

In scope:

- `skills/feedready/scripts/**` and `skills/feedready/swift/feedready_engine.swift`
- `skills/feedready/setup.sh`, `skills/feedready/run.sh`, `build_zip.sh`
- what those scripts download and execute (venv build, engine compile, model fetches)

Out of scope: the behaviour of the downloaded models themselves, and what any agent chooses to do with the CLI.

## Supported versions

The latest commit on `main` only. This is a personal project, so reports are handled best-effort — usually within a week.
