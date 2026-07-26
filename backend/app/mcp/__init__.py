"""Digonto's three MCP (Model Context Protocol) stdio servers.

`agents.md` describes three custom MCP servers so the tools behind Porter,
Prohori, and Khoji are reusable from any MCP client, including Claude Code
during development, not just from the in-process agent runtime:

  - `digonto-portal-mcp`  (portal_server.py)
  - `digonto-vault-mcp`   (vault_server.py)
  - `digonto-funding-mcp` (funding_server.py)

Every tool in every server calls into the existing repositories and services
under `app.repositories` / `app.services` rather than re-implementing a
query; `_common.py` is the shared bootstrap that constructs them once per
server process. See `app/mcp/README.md` for how to register each server with
an MCP client and the exact tool schemas.
"""
