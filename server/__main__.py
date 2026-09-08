"""Run the API and the built React client: python -m server"""
from __future__ import annotations

import argparse
import webbrowser
from threading import Timer

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG Data Analytics Assistant")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"\n  RAG Data Analytics Assistant\n  {url}\n  API docs: {url}/docs\n")

    if not args.no_browser and not args.reload:
        Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run("server.api:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
