#!/bin/sh
# Idempotent host-firewall routing for customer cells (ufw): forwarding for the cell pools and the one
# door to the model relay. Everything else a cell tries is dropped by the agentai_cells nftables table.
set -eu
ufw route allow from 10.78.0.0/16 comment 'agentai cells forward' >/dev/null
ufw route allow from 10.77.0.0/16 comment 'agentai cells default bridge forward' >/dev/null
ufw allow from 10.78.0.0/16 to 10.77.0.1 port 4000 proto tcp comment 'agentai cells model relay' >/dev/null
ufw allow from 10.77.0.0/16 to 10.77.0.1 port 4000 proto tcp comment 'agentai cells model relay (default bridge)' >/dev/null
