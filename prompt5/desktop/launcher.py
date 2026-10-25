"""PyInstaller entry point.

The real entry lives in ``prompt5.ui``. Importing it as a package avoids
relative-import failures when running from a one-file executable.
"""

from prompt5.ui import main


if __name__ == "__main__":
    raise SystemExit(main())
