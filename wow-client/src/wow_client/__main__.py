import argparse
import asyncio
from .client import Client

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--host", type=str, required=True, help="Server host")
    parser.add_argument("-p", "--port", type=int, required=True, help="Server port")
    parser.add_argument("-t", "--token", type=str, required=True, help="Authenticate token")
    args = parser.parse_args()
    client = Client(
        args.host,
        args.port,
        args.token,
    )

    try:
        await client.run()
    finally:
        await client.stop()

if __name__ == "__main__":
    asyncio.run(main())