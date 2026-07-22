# Intercloud Portal — Memory Bundle

This archive contains the "project memory" used by the E1 development agent
to keep continuity between sessions. Drop these files into `/app/memory/`
(or the equivalent) on any new workspace and the fork agent will pick up
from the exact state described in PRD.md.

Contents:
- memory/PRD.md             — full product requirements, architecture, and history
- memory/test_credentials.md — admin/client credentials for the seeded portal
- test_reports/iteration_*.json — testing-agent outcome per iteration (regression trail)

Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)
