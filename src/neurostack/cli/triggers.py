# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Trigger CLI commands (issue #159): did the warnings change anything?"""

import json


def cmd_triggers(args):
    """Report fired-versus-followed counts for trigger memories."""
    from ..schema import DB_PATH, get_db
    from ..triggers import trigger_stats

    subcmd = getattr(args, "triggers_command", None)
    if subcmd != "stats":
        print("Usage: neurostack triggers stats [--days N]")
        return

    stats = trigger_stats(get_db(DB_PATH), days=args.days)
    if args.json:
        print(json.dumps(stats, indent=2, default=str))
        return

    print(
        f"Triggers ({stats['days']}d): {stats['fired']} fired,"
        f" {stats['followed']} followed, {stats['ignored']} ignored,"
        f" {stats['pending']} pending{_rate(stats['followed_rate'])}"
    )
    if not stats["memories"]:
        print("No trigger fired in the window.")
        return
    print()
    print(f"{'ID':<8}{'FIRED':<7}{'FOLLOWED':<10}{'IGNORED':<9}{'PENDING':<9}RATE")
    for entry in stats["memories"]:
        rate = entry["followed_rate"]
        print(
            f"{entry['memory_id']:<8}{entry['fired']:<7}{entry['followed']:<10}"
            f"{entry['ignored']:<9}{entry['pending']:<9}"
            f"{'-' if rate is None else f'{rate * 100:.0f}%'}"
        )
        print(f"        {entry['trigger'] or 'no trigger tag'}: {entry['content']}")


def _rate(rate: float | None) -> str:
    """The followed share, or nothing at all while no outcome is in."""
    return "" if rate is None else f" ({rate * 100:.0f}% followed)"
