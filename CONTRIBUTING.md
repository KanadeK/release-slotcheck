# Contributing

Open an issue with a minimal synthetic reproducer before proposing a large change.
Do not include private installers, proprietary payloads, credentials or local user data.

Use Python 3.11 or later. From the checkout, create and activate a virtual environment:

```sh
python -m pip install . ruff==0.14.2 build==1.3.0
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m build
```

Add tests for changed behavior and malformed input. Keep the CLI read-only and
the runtime dependency-free. CI tests and builds; it never commits code.
Contributions are licensed under MIT. Maintainers review changes manually.
