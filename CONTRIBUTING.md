# Contributing

Commit subjects must start with `feat:` or `fix:`.

Run the checks with Python 3.14:

```sh
python -m pip install -r requirements-test.txt
python -m pytest
ruff check custom_components tests --select E4,E7,E9,F
ruff format --check custom_components tests
```

Tests use synthetic data and mock network access. Never commit credentials, tokens, personal configuration or packet captures.
