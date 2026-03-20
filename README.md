# Doover APT Package for Doover CLI

This CLI package is the core Doover CLI, allowing you to interact and perform scripting with the Doover platform, 
generate, test, lint, run and deploy new applications and more.

# Installation

If you don't have `uv` installed, it is suggested to install that first:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## With UV / Pip

In order of preference (choose one):

```bash
uv tool install doover-cli
```

```bash
pipx install doover-cli
```

```bash
pip install doover-cli
```


## Linux / Debian

Make sure you have the doover apt repository added to your system:
```bash
sudo wget http://apt.u.doover.com/install.sh -O - | sh
```

And then install the package with:
```bash
sudo apt install doover-cli
```

## MacOS / Homebrew

If you don't have `brew` installed, it is suggested to install that first:
```bash
```



# Usage

Invoke the CLI with ...:
```bash
doover --help
```

Generally, you'll want to start with `doover login` which will walk you through an interactive login process to authenticate with the Doover platform.

```bash
doover login
```

If you're using the CLI in a script or CI/CD pipeline, you can set the `DOOVER_API_TOKEN` environment variable to an API token to bypass login mechanisms.
If you need to target a custom data API endpoint in that mode, set `DOOVER_DATA_API_BASE_URL`.

Channel commands on the new API surface require an explicit target agent:

```bash
doover channel get my-channel --agent 12345
```

For channel payloads that are hard to read in a plain dump, `channel get` now supports multiple terminal-oriented views:

```bash
uv run doover channel get ui_state --agent 157338390533018379
uv run doover channel get ui_state --agent 157338390533018379 --view plain
uv run doover channel get ui_state --agent 157338390533018379 --view simple
uv run doover channel get ui_state --agent 157338390533018379 --view interactive
```

Available `--view` modes:

- `plain`: legacy text output
- `overview`: Rich panels and a readable tree of aggregate data
- `simple`: Textual split view with aggregate tree on the left and channel metadata on the right
- `interactive`: Textual tree explorer with keyboard navigation

## Error Reporting

The CLI reports exception-based command failures to Sentry by default. It avoids normal control-flow exits such as `--help`, `--version`, and user aborts, and it does not intentionally attach secrets such as API tokens as structured metadata.

You can control Sentry with these environment variables:

```bash
DOOVER_SENTRY_ENABLED=0
DOOVER_SENTRY_DSN=<dsn>
DOOVER_SENTRY_ENVIRONMENT=<name>
```


# Contributing
See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for more information on how to contribute to this project.

# License
This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
