# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""`neurostack ui`: serve the read-only web dashboard (issues #243, #251)."""

import getpass
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


def cmd_ui_user(args):
    from ..config import get_config
    from ..ui import auth

    cfg = get_config()
    if args.user_cmd == "list":
        for name in auth.list_users(cfg):
            print(name)
        return
    if args.user_cmd == "remove":
        if not auth.remove_user(cfg, args.name):
            print(f"No dashboard user named {args.name}", file=sys.stderr)
            sys.exit(1)
        print(f"Removed {args.name}; their sessions end now")
        return
    if args.password_stdin:
        password = sys.stdin.read().rstrip("\r\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords do not match", file=sys.stderr)
            sys.exit(1)
    try:
        auth.add_user(cfg, args.name, password)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    print(f"Saved dashboard user {args.name}")
