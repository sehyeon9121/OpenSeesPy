"""Command-line entry point for OpenFrame Studio."""

from openframe.app.bootstrap import run_desktop_app


def main() -> int:
    return run_desktop_app()


if __name__ == "__main__":
    raise SystemExit(main())

