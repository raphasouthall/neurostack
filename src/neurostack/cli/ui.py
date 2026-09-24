# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""`neurostack ui`: serve the read-only web dashboard (issue #243)."""

import sys


def cmd_ui(args):
    from ..config import get_config
    from ..ui.server import serve

    try:
        serve(get_config(), args.host, args.port, open_browser=args.open)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Cannot listen on {args.host}:{args.port}: {exc.strerror or exc}",
              file=sys.stderr)
        sys.exit(1)
