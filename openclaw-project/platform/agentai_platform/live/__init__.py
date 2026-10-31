"""Live view: the newest frame of a running browser task, delivered without touching the web app's single worker.

ticket.py   signed, short-lived "may watch task X of account Y" tokens, minted by the account app (which checks ownership)
gateway.py  a tiny HTTP server (its own threads, inside the browse service, never the web app's worker) that long-polls the newest frame file
"""
