#!/bin/zsh
cd /Users/parsa/AgentAI/jev-window-core || exit 1
python3 run.py "$@"
printf '\nPress Enter to close. '
read -r
