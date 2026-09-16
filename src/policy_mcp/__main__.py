"""Allow ``python -m policy_mcp`` to run the installed command."""

from policy_mcp.cli import main

raise SystemExit(main())
