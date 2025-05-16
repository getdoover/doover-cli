# Doover APT Package for Doover CLI

This CLI package is the core Doover CLI, allowing you to interact and perform scripting with the Doover platform, 
generate, test, lint, run and deploy new applications and more.

## Installation

Make sure you have the doover apt repository added to your system:
```bash
sudo wget http://apt.u.doover.com/install.sh -O - | sh
```

And then install the package with:
```bash
sudo apt install doover-cli
```

If you don't have `uv` installed, it is suggested to install that as well:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Usage

Invoke the CLI with ...:
```bash
doover --help
```
