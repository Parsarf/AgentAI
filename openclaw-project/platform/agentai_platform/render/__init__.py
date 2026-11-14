"""Turning one file into another format (PDF, Word, Excel, PowerPoint, images) for the customer.

    engine.py        the conversions; runs only inside the renderer container
    service.py       the host service (root) that runs one container per job
    service_main.py  its entry point
    client.py        what the app uses to ask for a conversion
"""
