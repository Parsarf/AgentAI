#!/usr/bin/env python3
"""Operator-only onboarding using the installed connector's own OAuth tool.

Run inside the prepared Google image with a protected client file and a
temporary loopback callback tunnel. Never pipe output into retained evidence.
This script is not an agent tool and does not enable OpenClaw connections.
"""
import asyncio
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    if not Path("/data/client-secret.json").is_file():
        raise SystemExit("Install the OAuth client JSON privately at /data/client-secret.json first.")
    if not os.environ.get("USER_GOOGLE_EMAIL"):
        raise SystemExit("Set the owner's USER_GOOGLE_EMAIL in the trusted operator environment.")
    params = StdioServerParameters(
        command="workspace-mcp",
        args=["--transport", "stdio", "--tools", "gmail", "calendar", "drive", "--read-only"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            auth = next((t for t in tools.tools if t.name == "start_google_auth"), None)
            if auth is None:
                raise SystemExit("Installed connector did not expose its native OAuth tool; leave disabled.")
            arguments = {"service_name": "gmail"}
            if "user_google_email" in auth.inputSchema.get("properties", {}):
                arguments["user_google_email"] = os.environ["USER_GOOGLE_EMAIL"]
            result = await session.call_tool("start_google_auth", arguments)
            if result.isError:
                raise SystemExit("Connector OAuth initiation failed. Inspect in this protected operator terminal.")
            for block in result.content:
                if getattr(block, "type", None) == "text":
                    print(block.text, flush=True)
            await asyncio.to_thread(input, "Complete consent in your browser, then press Enter here. ")
            print("OAuth flow closed. Account identity/scopes still require protected readback before activation.")


if __name__ == "__main__":
    asyncio.run(main())
