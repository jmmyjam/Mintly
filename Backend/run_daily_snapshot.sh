#!/bin/bash
# Daily price-history snapshot for Mintly — records every card's price so the
# history/portfolio charts are gap-free. Scheduled by the
# com.mintly.daily-snapshot LaunchAgent (~/Library/LaunchAgents). Run from the
# Backend/ dir so .env and venv/ resolve. Requires the Postgres in DATABASE_URL
# to be running.
cd "$(dirname "$0")" || exit 1
exec venv/bin/python snapshot_all.py
