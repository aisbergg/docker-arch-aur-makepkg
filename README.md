# Docker - Arch AUR makepkg

Dockerfile to build a Arch-Linux based container image to be used for automated creation of *[Pacman](https://wiki.archlinux.org/index.php/Pacman)* packages. The image is equipped with `makepkg` and various necessary build tools. It can pull package sources from the *[AUR](https://aur.archlinux.org/)* or use local sources.
Using docker the build process of a package will be executed in a clean environment seperated from the host operating system. Because the docker image contains all needed dependencies you can build *Pacman* packages from different linux distribution rather than Arch-Linux. Once the build of a package is done, all the additional programs and data needed for the process will be deleted and therefore leave your OS in a clean, not bloated state.

## Build the image

From within this repository simply run:

```
docker build -t aisberg/arch-aur-makepkg
```

## Usage

The script within the image will process local sources of a package aswell as sources from the AUR. Local sources are preferred over those in the AUR. Before building a package the version of a already existing *Pacman* package is checked against the version of the source package. Therefore a package will only build when a change in the version occourred.
To save the created packages in a destination of your choice you have to mount a *Volume* into the container. The path within the container is `/makepkg`. After a build is complete the package will be copied into `/makepkg`. Local sources of a package need to be put into `/makepkg/local_src` as a dir containing a `PKGBUILD` file. The resulting structure can therefore look like this:

```
.
├── local_src
│   ├── package_1
│   │   └── PKGBUILD
│   └── package_2
│       └── PKGBUILD
├── package_1-1.2.3-1-x86_64.pkg.tar.xz
├── package_2-1.2.3-2-x86_64.pkg.tar.xz
└── package_N-from-AUR-1.2.3-3-x86_64.pkg.tar.xz
```

### Invoke

The basic command to run a container and build a few packages would be following:

```
docker run -it --rm -v ~/mypackages:/makepkg aisberg/arch-aur-makepkg package_1 package_2 ... package_N
```

In this example `~/mypackages` is the volume to be mounted into the container. `package_1 package_2 ... package_N` are the names of the packages you like to build.
Together with the names of the packages to be build, some optional arguments can be passed on. The help (`... aisberg/arch-aur-makepkg --help`) lists all available arguments:

```
aur-makepkg [-h] [-g GID] [-k] [-p] [-u UID]
                   package_names [package_names ...]

Build Pacman packages with makepkg from local source or the AUR

positional arguments:
  package_names         Name fo packages to be build from local source or the
                        AUR

optional arguments:
  -h, --help            show this help message and exit
  -g GID, --gid GID     GID for created packages
  -k, --keep-old-versions
                        Keep older versions of a package after a newer one is
                        build
  -p, --pacman-update
  -u UID, --uid UID     UID for created packages
```
