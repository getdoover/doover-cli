# Template Repository for Doover APT Packages

When you create a new package, remove this section!

You will also need to:
- Put any source files in the src/ directory
- Update the package name in the 
  - src/ files
  - debian/control file
  - debian/doover-CHANGEME.install file
  - This README.md
- Update the README.md with install instructions and usage information
- Ask someone to enable the `APT_RELEASE_X` secrets in the GitHub organisation settings for this repository.

**Make sure you mark your src/ files as executable!**

If you're stuck, ask for help.

## Releases

Releases are automatically pushed to the apt repository when a new release is created in GitHub.
Update the version number and changelog in the debian/changelog file before creating a new release.

Please don't try and push changes to the apt repository manually. If you're stuck, ask for help.

If you need custom build steps, feel free to change the `.github/workflows/release.yml` file.

**If you're using bash or python, you don't need a custom build step!**


# Remove the above section when you're ready to go!

# Doover APT Package for XXXXX

A simple CLI package that forms part of the `doover` apt repository.

## Installation

Make sure you have the doover apt repository added to your system:
```bash
sudo wget http://apt.u.doover.com/install.sh -O - | sh
```

And then install the package with:
```bash
sudo apt install doover-YOUR_PACKAGE_NAME
```

## Usage

Invoke the CLI with ...:
```bash
doover-YOUR_PACKAGE_NAME --arg <ARG> --arg2 <ARG2>
```
