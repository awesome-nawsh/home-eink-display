"""Connectivity checks run once at boot, before the boot checklist screen is
drawn. Each check is a fast, cheap probe (BOOT_CHECK_TIMEOUT seconds) — not a
full data fetch — so all four can run back-to-back before a single
render+display() call. render/boot_screen.py is the only importer; keeping
these checks here (rather than inline in the render module) keeps them
unit-testable without importing PIL.

check_network/check_internet/check_lta_api/check_home_assistant hit real
sockets/HTTP and are intentionally NOT unit-tested here — they're
integration-only, exercised by actually booting the app. format_checklist_lines()
is the pure/testable boundary: given a fixed list of (label, bool) results, it
has no network or PIL dependency at all.
"""
import logging
import socket

import requests

from config import (
    BOOT_CHECK_TIMEOUT,
    INTERNET_CHECK_URL,
    BUS_API_URL,
    HOME_ASSISTANT_API_URL,
    HOME_ASSISTANT_TOKEN,
)


def check_network():
    """LAN/route-out reachability: open a UDP socket toward a public IP.
    UDP connect() doesn't send any packets — it just asks the kernel to pick
    a local route/address, which fails immediately if there's no network
    route at all (no Wi-Fi/ethernet link)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(BOOT_CHECK_TIMEOUT)
        s.connect(("8.8.8.8", 80))
        s.close()
        return True
    except OSError:
        return False


def check_internet():
    """Real internet reachability via a cheap GET to a 204-No-Content
    endpoint — minimal payload, short timeout."""
    try:
        r = requests.get(INTERNET_CHECK_URL, timeout=BOOT_CHECK_TIMEOUT)
        return r.status_code < 500
    except requests.RequestException:
        return False


def check_lta_api():
    """LTA DataMall host reachability via HEAD — proves the host answers,
    without spending an AccountKey-authenticated call on a full bus-arrival
    fetch."""
    if not BUS_API_URL or BUS_API_URL.startswith('Not Found'):
        return False
    try:
        r = requests.head(BUS_API_URL, timeout=BOOT_CHECK_TIMEOUT)
        return r.status_code < 500
    except requests.RequestException:
        return False


def check_home_assistant():
    """HA reachability via the lightweight /api/ root endpoint, not a
    states/<entity> fetch."""
    if not HOME_ASSISTANT_API_URL or not HOME_ASSISTANT_TOKEN:
        return False
    try:
        r = requests.get(
            f"{HOME_ASSISTANT_API_URL}/api/",
            headers={'Authorization': f'Bearer {HOME_ASSISTANT_TOKEN}'},
            timeout=BOOT_CHECK_TIMEOUT,
        )
        return r.status_code == 200
    except requests.RequestException:
        return False


def run_all_checks():
    """Runs all four checks sequentially (each is short-timeout and this
    only happens once at boot, so parallelizing isn't worth the added
    complexity) and returns an ordered list of (label, passed) pairs."""
    results = [
        ("Network", check_network()),
        ("Internet", check_internet()),
        ("LTA API", check_lta_api()),
        ("Home Assistant", check_home_assistant()),
    ]
    logging.info(f"Boot connectivity checks: {results}")
    return results


def format_checklist_lines(results):
    """Pure formatting: [(label, bool), ...] -> ['Network: OK', ...].
    Kept separate from run_all_checks() so tests can feed fixed results in
    without touching the network."""
    return [f"{label}: {'OK' if ok else 'FAIL'}" for label, ok in results]
