# Official Data Snapshot

This directory stores the 2026-05-09 official local-evaluation data snapshot in
compressed form so collaborators can reproduce the experiments without
re-downloading the original release package.

## Contents

```text
official_data_20260509.tar.gz
  data/cargo_dataset.jsonl
  data/drivers.json
```

## Restore

Run from repository root:

```bash
tar -xzf demo/resources/official_data_20260509.tar.gz -C demo/server
```

The archive intentionally excludes `demo/server/config/config.json` because API
keys and local result paths must remain machine-specific. Use
`demo/server/config/config.example.json` as the template.
