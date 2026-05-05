"""Allow `python -m slippage_labs ...` as an alias for the CLI."""

from slippage_labs.cli import app

if __name__ == "__main__":
    app()
