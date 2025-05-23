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


# Contributing
See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for more information on how to contribute to this project.

# License
This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.