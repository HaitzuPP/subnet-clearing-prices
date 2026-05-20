#!/usr/bin/env python3
"""
update_data.py — Queries Bittensor chain for new subnet registrations
and patches index.html with fresh data. Run manually or via GitHub Actions.
"""

import re
import json
import sys
from datetime import datetime, timedelta, timezone

import bittensor as bt

HTML_FILE = "index.html"
BLOCK_SECONDS = 12  # Bittensor target block time


# ── Date helper ───────────────────────────────────────────────────────────────

def block_to_date(block: int, anchor_block: int, anchor_date: datetime) -> str:
    """Estimate UTC date for a block using a known anchor."""
    delta = timedelta(seconds=(block - anchor_block) * BLOCK_SECONDS)
    return (anchor_date + delta).strftime("%Y-%m-%d")


# ── HTML parsers ──────────────────────────────────────────────────────────────

def parse_data(html: str) -> list:
    match = re.search(r"const ALL_DATA = (\[.*?\]);", html, re.DOTALL)
    if not match:
        raise ValueError("Could not find ALL_DATA in index.html")
    return json.loads(match.group(1))


def last_anchor(data: list) -> tuple[int, datetime]:
    """Return (block, date) of the most recent entry in the data."""
    most_recent = max(data, key=lambda d: d["block"])
    date = datetime.strptime(most_recent["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return most_recent["block"], date


# ── Chain query ───────────────────────────────────────────────────────────────

def fetch_new_registrations(last_block: int, anchor_block: int, anchor_date: datetime) -> list:
    """
    Query Bittensor chain for subnets registered after last_block.
    Note: only covers currently-active subnets (NetworkRegisteredAt map).
    Subnets that register and deregister between runs are not captured.
    """
    print("Connecting to Bittensor finney…")
    sub = bt.Subtensor(network="finney")
    print(f"  Current chain block: {sub.block}")

    reg_items  = list(sub.substrate.query_map("SubtensorModule", "NetworkRegisteredAt"))
    lock_items = list(sub.substrate.query_map("SubtensorModule", "SubnetLocked"))

    lock_map = {int(uid): int(amt) for uid, amt in lock_items}

    new = []
    for uid, blk in reg_items:
        netuid = int(uid)
        block  = int(blk)
        if block > last_block:
            cost_tao = round(lock_map.get(netuid, 0) / 1e9, 2)
            new.append({
                "netuid":   netuid,
                "block":    block,
                "date":     block_to_date(block, anchor_block, anchor_date),
                "cost_tao": cost_tao,
            })

    return sorted(new, key=lambda x: x["block"])


# ── HTML patcher ──────────────────────────────────────────────────────────────

def update_html(html: str, new_entries: list) -> str:
    existing = parse_data(html)
    old_total = len(existing)

    updated = sorted(existing + new_entries, key=lambda d: d["block"])
    total   = len(updated)

    most_recent  = max(updated, key=lambda d: d["block"])
    recent_cost  = most_recent["cost_tao"]
    recent_sn    = most_recent["netuid"]
    recent_mo    = datetime.strptime(most_recent["date"], "%Y-%m-%d").strftime("%b %Y")
    formatted_cost = f"τ{recent_cost:,.0f}"

    # 1. Replace ALL_DATA array
    new_json = json.dumps(updated, separators=(",", ":"))
    html = re.sub(
        r"const ALL_DATA = \[.*?\];",
        f"const ALL_DATA = {new_json};",
        html,
        flags=re.DOTALL,
    )

    # 2. Update event counts in subtitle and source line
    html = html.replace(
        f"{old_total} actual registration events",
        f"{total} actual registration events",
    )
    html = html.replace(
        f"{old_total} on-chain registration events",
        f"{total} on-chain registration events",
    )

    # 3. Update the "Total" stat counter box (the standalone number)
    html = re.sub(
        r'(<div class="stat-v">)' + str(old_total) + r"(</div>)",
        rf"\g<1>{total}\2",
        html,
    )

    # 4. Update Most Recent cost stat
    html = re.sub(
        r'(<div class="stat-v">)τ[\d,]+(</div>\s*<div class="stat-l">Most Recent)',
        rf"\g<1>{formatted_cost}\2",
        html,
    )

    # 5. Update Most Recent label
    html = re.sub(
        r"Most Recent — SN\d+, \w+ \d{4}",
        f"Most Recent — SN{recent_sn}, {recent_mo}",
        html,
    )

    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    data = parse_data(html)
    anchor_block, anchor_date = last_anchor(data)
    last_block = anchor_block

    print(f"Last recorded block: {last_block} ({anchor_date.date()})")

    try:
        new_entries = fetch_new_registrations(last_block, anchor_block, anchor_date)
    except Exception as e:
        print(f"ERROR: chain query failed — {e}")
        sys.exit(1)

    if not new_entries:
        print("No new registrations. Nothing to do.")
        sys.exit(0)

    print(f"Found {len(new_entries)} new registration(s):")
    for e in new_entries:
        print(f"  SN{e['netuid']}: block {e['block']}, date {e['date']}, cost {e['cost_tao']} TAO")

    updated_html = update_html(html, new_entries)

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(updated_html)

    print("index.html updated successfully.")


if __name__ == "__main__":
    main()
