#!/bin/zsh
set -e
cd "${0:A:h}"
command -v gh >/dev/null || { print 'Install GitHub CLI and sign in as the repository owner first.'; exit 1; }
python3 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir -r requirements.txt
.venv/bin/python -B -m hosted_sender.prepare --mac-folder "${SHINE_MAC_FOLDER:-$HOME/Downloads/autoclient-acquisition/New/shine-acquisition-agent}"
read 'shine_done?Press Return to close.'
