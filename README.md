# Docker - Arch AUR makepkg

Dockerfile to build a Arch-Linux based container image to be used for automated creation of *[Pacman](https://wiki.archlinux.org/index.php/Pacman)* packages. The image is equipped with `makepkg` and various necessary build tools. It can pull package sources from the *[AUR](https://aur.archlinux.org/)* or use local sources.
Using docker the build process of a package will be executed in a clean environment seperated from the host operating system. Therefore dependencies that where only needed for building a package won't pile up in your OS.

- [Docker - Arch AUR makepkg](#docker-arch-aur-makepkg)
  - [Why another one?](#why-another-one)
  - [Build the image](#build-the-image)
  - [Usage](#usage)
    - [Invoke](#invoke)
  - [Installing the build packages](#installing-the-build-packages)
  - [Troubleshooting](#troubleshooting)
  - [License](#license)

---

## Why another one?
There a quite a lot [AUR helper](wiki.archlinux.org/index.php/AUR_helpers), so why another one? My Reasons:
- automaticylly build packages in an isolated docker container --> don't pollute my primarily systems with make dependencies
- keep the make dependencies (save bandwidth)
- keep the package sources around as long they don't change (save bandwidth)
- rebuild package if dependency changed (using pamac for example won't always do the trick)

## Build the image
From within this repository simply run:

```
docker build -t aisberg/arch-aur-makepkg .
```

## Usage
The script within the image will process local sources of a package aswell as sources from the AUR. Local sources are preferred over those in the AUR, meaning if a local source is found it will be used rather than the AUR one.

The directory structure in the container is as follows:
```
.
├── etc
│   ├── pacman.conf        # Pacman configuration
│   └── pacman.d
│       └── mirrorlist     # Pacman mirrorlist
├── makepkg
│   ├── local_src          # Path that will be used to look for sources
│   │   ├── foo            # Local source of 'foo'
│   │   │   └── PKGBUILD
│   │   └── bar            # Local source of 'foo'
│   │       └── PKGBUILD
│   └── build              # Path that will be used for building
├── usr
|   └── share
|       └── pacman
|           └── keyrings   # Pacman keyrings for signature checking
└── var
    └── cache
        └── pacman
            └── pkg        # Pacman package cache
```

Three files and dirs need to be mounted into the container to work properly:
- `/makepkg`: Your store for local sources and build sources fetched by `makepkg`
- `/etc/pacman.conf`: Your personal pacman configuration
- `/etc/pacman.d/mirrorlist`: Your preferred mirrorlist
- `/usr/share/pacman/keyrings`: Your initial pacman keyrings
- `/var/cache/pacman/pkg`: Your pacman package chache, where all packages will be stored

### Invoke
The basic command to run a container and build a few packages would be following:

```bash
docker run -it --rm \
  -v "~/makepkg:/makepkg" \
  -v "/etc/pacman.conf:/etc/pacman.conf:ro" \
  -v "/etc/pacman.d/mirrorlist:/etc/pacman.d/mirrorlist:ro" \
  -v "/usr/share/pacman/keyrings/:/usr/share/pacman/keyrings/:ro" \
  -v "/var/cache/pacman/pkg:/var/cache/pacman/pkg" \
  aisberg/arch-aur-makepkg --keyrings archlinux,manjaro package_1 package_2 ... package_N
```

In this example `~/mypackages` will be mounted as `\makepkg` and `package_1 package_2 ... package_N` are the names of the packages you like to build.
There are a few optional arguments available that can be passed on together with the package names:

```
usage: aur-makepkg [-h] [-g GID] [-i] [-k KEYRINGS] [-p] [-r REBUILD]
                   [--remove-downloaded-source] [-u UID]
                   build_package_names [build_package_names ...]

Build Pacman packages with makepkg from local source or the AUR

positional arguments:
  build_package_names   Name fo packages to be build from local source or the
                        AUR

optional arguments:
  -h, --help            show this help message and exit
  -g GID, --gid GID     GID of the build user
  -i, --install-all-dependencies
                        Install all dependencies, not only 'make dependencies'
  -k KEYRINGS, --keyrings KEYRINGS
                        Pacman keyrings initialized prior building (comma
                        seperated list)
  -p, --pacman-update   Update all installed pacman packages before build
  -r REBUILD, --rebuild REBUILD
                        Rebuild behaviour: 0: Build only new versions of
                        packages (default) 1: Rebuild all explicit listed
                        packages 2: Rebuild all explicit listed packages and
                        their dependencies
  --remove-downloaded-source
                        Remove the source downloaded by 'makepkg' before
                        build. If not the sources will be kept, under the
                        condition that the source is of the same version of
                        the package to be build. (Note: Sources of packages
                        build from a Git repository will always be removed.)
  -u UID, --uid UID     UID of the build user
```

## Installing the build packages
This docker container is only for building the images not for installing those.

Personally I distribute the package cache to my systems and use this [Installation Script](https://github.com/Aisbergg/install-local-pacman-packages) to handle this job.

## Troubleshooting
> Package requirements ### were not met

Sometimes the dependencies that are needed to make a package are not properly listed as `makedepends` but as `depends`. The default behaviour is to only install the `makedepends`. With `--install-all-dependencies` this can be bypassed.

> Linux Kernel Headers

Packages that provide some system functionality and require the linux kernel headers to be build, should be avoided.

> Signature issues

If you running not an *ArchLinux* distribution, but a distribution that is based on *ArchLinux* like *Manjaro* for example, than you have different maintainer and therefore different keys in the GPG keychain. Therefore the installation of packages may fail because the signatures cannot be validated. To solve this problem the keyring must be initialized with different set of keys. Therefore your keyrings directory (see [Usage](#usage)) must be mounted into the container and then started with the extra argument `--keychain KEYRINGS`, where `KEYRINGS` is a comma seperated list of keyrings located in your keyrings directory.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
