import argparse

from er_triage.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="er-triage")
    sub = parser.add_subparsers(dest="command", required=True)

    initdb = sub.add_parser("initdb", help="create database tables")
    initdb.add_argument("--drop", action="store_true", help="drop existing tables first")

    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    args = parser.parse_args()
    match args.command:
        case "initdb":
            from er_triage.db import init_db

            init_db(drop=args.drop)
            print(f"tables ready in {get_settings().database_url}")
        case "serve":
            import uvicorn

            uvicorn.run("er_triage.app:app", host=args.host, port=args.port, reload=args.reload)
