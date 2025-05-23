# Contributing

Thank you for your interest in contributing to the Doover project! 

We welcome contributions from the community and appreciate your help in making Doover better. Below are some guidelines to help you get started.

## Install Dependencies

To set up your development environment, install the optional dependencies for the CLI:

```bash
uv sync
source .venv/bin/activate
```

## Testing

To run unit tests, use `pytest` in the main directory of the repository:

```bash
uv run pytest
```

## Pre-commit Hooks

We use pre-commit hooks to ensure code quality and consistency using Ruff. To set up pre-commit hooks, run the following command:

```bash
pre-commit install
```