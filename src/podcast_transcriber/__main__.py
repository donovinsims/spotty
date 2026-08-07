"""Allow `python -m podcast_transcriber`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())