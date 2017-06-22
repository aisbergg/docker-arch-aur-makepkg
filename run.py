#!/usr/bin/python3
import argparse
import os
import sys
import re
import shutil
import tempfile
import pwd
import grp
import tarfile
import time
import urllib.request
from subprocess import Popen, PIPE

import aur
import pacman

local_source_dir = '/makepkg/local_src'
build_dir = os.path.abspath('/makepkg/build')
pacman_cache_dir = '/var/cache/pacman/pkg'
accepted_architectures = ['any', 'x86_64', 'i686']

packages_in_cache = None
packages_in_offical_repositories = None


class ConsoleColors:
    blue = '\033[94m'
    green = '\033[92m'
    red = '\033[91m'
    yellow = '\033[93m'
    reset = '\033[0m'


class InvalidPackageSourceError(Exception):
    """ Invalid package source exception

    Args:
        message (str): Message passed with the exception

    """

    def __init__(self, message):
        super().__init__(message)


class NoSuchPackageError(Exception):
    """ No such package exception

    Args:
        message (str): Message passed with the exception

    """

    def __init__(self, message):
        super().__init__(message)


def printInfo(message):
    """Print a colorful info message.

    Args:
        message (str): Message to be printed

    """
    print(ConsoleColors.blue + message + ConsoleColors.reset)


def printSuccessfull(message):
    """Print a colorful successfull message.

    Args:
        message (str): Message to be printed

    """
    print(ConsoleColors.green + message + ConsoleColors.reset)


def printWarning(message):
    """Print a colorful warning message.

    Args:
        message (str): Message to be printed

    """
    print(ConsoleColors.yellow + message + ConsoleColors.reset)


def printError(message):
    """Print a colorful error message.

    Args:
        message (str): Message to be printed

    """
    print(ConsoleColors.red + message + ConsoleColors.reset)


class PackageRepository:
    """Represents an enum of all package repositories."""

    CORE = "core"
    EXTRA = "extra"
    COMMUNITY = "community"
    MULTILIB = "multilib"
    AUR = "aur"
    LOCAL = "local"


class PackageBase:
    """Base class for pacman packages and their sources.

    Args:
        name (str): Name of the Arch Linux package

    """

    name = None
    version = None
    architecture = None
    repository = None
    dependencies = None
    license = None

    # is a cached version of this package available
    #   0: not available
    #   1: different version(s) available
    #   2: same version available
    cache_available = 0

    # True if this package needs to be installed before a dependent package can
    # be build
    is_make_dependency = False

    # status of the installtion
    #   0: is not installed
    #   1: is installed
    #   2: different version is installed
    #   3: failed to install
    installation_status = 0

    # store for errors
    error_info = None

    def __init__(self, name):
        self.name = name

    def _check_if_cache_is_available(self):
        # check if same version is available
        name = '{0}-{1}-{2}.pkg.tar.xz'.format(
            self.name, self.version, self.architecture)
        if name in packages_in_cache:
            self.cache_available = 2
            return

        # check if different version is available
        else:
            regex_different = re.compile(r'{0}-(\S+)-{1}.pkg.tar.xz'.format(
                self.name, self.architecture))
            for cache_file in packages_in_cache:
                match = regex_different.search(os.path.basename(cache_file))
                if match:
                    self.cache_available = 1
                    return

        self.cache_available = 0

    def _get_installation_status(self):
        """Get the installation status of the package."""
        if pacman.is_installed(self.name):
            pcm_info = pacman.get_info(self.name)
            if pcm_info['Version'] == self.version:
                self.installation_status = 1
            else:
                self.installation_status = 2
        else:
            self.installation_status = 0


class PacmanPackage(PackageBase):
    """Represents a pacman package from a official repository.

    Args:
        name (str): Name of the pacman package

    """

    def __init__(self, name):
        super().__init__(name)
        try:
            self._get_package_info()
            self._check_if_cache_is_available()
            self._get_installation_status()
        except Exception as e:
            self.error_info = e

    def _get_package_info(self):
        """Get the needed package information."""
        is_available = False
        for pcm_info in packages_in_offical_repositories:
            if pcm_info['id'] == self.name:
                is_available = True
                break

        if is_available:
            pkg_info = pacman.get_info(self.name)
            self.version = pkg_info['Version']
            self.architecture = pkg_info['Architecture']
            if 'Repository' in pkg_info:
                if pkg_info['Repository'] == PackageRepository.EXTRA:
                    self.repository = PackageRepository.EXTRA
                elif pkg_info['Repository'] == PackageRepository.CORE:
                    self.repository = PackageRepository.CORE
                elif pkg_info['Repository'] == PackageRepository.COMMUNITY:
                    self.repository = PackageRepository.COMMUNITY
                elif pkg_info['Repository'] == PackageRepository.MULTILIB:
                    self.repository = PackageRepository.MULTILIB
            else:
                self.repository = PackageRepository.EXTRA
            self.dependencies = pkg_info['Depends On'].split(' ')
            self.license = pkg_info['Licenses']
        else:
            raise NoSuchPackageError(
                "No package with the name '{0}' exists in the official repositories".format(self.name))

    def install(self):
        printInfo("Installing package {0} {1}...".format(
            self.name, self.version))
        rc, err = run_command(['pacman', '-S', '--noconfirm', '--force',
                               '--ignore', 'package-query', '--ignore', 'pacman-mirrorlist',
                               '--cachedir', pacman_cache_dir, self.name])
        if rc != 0:
            self.installation_status = 2
            self.error_info = Exception(
                "Failed to install package '{0}': {1}".format(self.name, '\n'.join(err)))
            return
        self.installation_status = 1


class PackageSource(PackageBase):
    """Represents a source of a package.

    Args:
        name (str): Name of the package
        remove_dowloaded_source (bool): If True remove the source downloaded by 'makepkg' before build. If False
            the sources will be kept, under the condition that the source is of the same
            version of the package to be build
        local_source_path (str): Local path of the source. If 'None' the pckage will be fetched from the AUR

    """

    # path that contains the package source
    path = None

    # the dependencies that need to be installed prior build
    make_dependencies = None

    # is marked as an explicit build, so it is not a dependency of another
    # package
    explicit_build = False

    # the status of the build
    #   0: not yet build
    #   1: successfully build
    #   2: skipped build
    #   3: failed to build
    #   4: make dependency failed
    build_status = 0

    # If True remove the source downloaded by 'makepkg' before build. If False
    # the sources will be kept, under the condition that the source is of the same
    # version of the package to be build
    remove_dowloaded_source = False

    # package source is build from git repository
    build_from_git = False

    def __init__(self, name, remove_dowloaded_source, local_source_path=None):
        super().__init__(name)
        self.remove_dowloaded_source = remove_dowloaded_source
        try:
            # is local source package
            if local_source_path:
                self.repository = PackageRepository.LOCAL
                self.path = os.path.abspath(local_source_path)

            # is AUR package
            else:
                self.repository = PackageRepository.AUR
                self._download_aur_package_source()

            self._parse_pkgbuild_file()
            self._check_if_cache_is_available()
            self._get_installation_status()
        except Exception as e:
            self.error_info = e

    def _parse_from_string(self, name, string):
        """Parse a bash variable value from a string.

        Args:
            name (str): Name of the variable to be parsed
            string (str): String containing the bash variables

        Returns:
            str.  Value for given params
            list.  Value for given params
            None.  If given param wasn't found

        """
        # search for array like value
        match = re.compile(r'{0}=\(([^\)]+)\)'.format(name),
                           re.DOTALL).search(string)
        if match:
            return [x.strip('\"\'') for x in match.group(1).replace('\n', '').replace('"', '').replace('\'', '').split(' ') if x != '']
        else:
            # search for simple string value
            match = re.compile(r'{0}=(.+)'.format(name)).search(string)
            if match:
                return match.group(1).strip('\"\' ')
        return None

    def _get_dependencies_from_alias(self, dep_alias_names):
        """Get the real package names if only an alias was supplied.

        Args:
            dep_alias_names (list): (Alias-)Names of the packages

        Returns:
            list.  Real names of the packages

        """
        dependencies = []
        if dep_alias_names:
            for dep_alias_name in dep_alias_names:
                dep_alias_name = re.sub(r'(.+?)(<|<=|>|>=){1}.*?$', r'\1',
                                        dep_alias_name)
                p = Popen(['package-query', '-QSiif', '%n', dep_alias_name],
                          stdout=PIPE,
                          stderr=PIPE,
                          universal_newlines=True)
                out, err = p.communicate()
                if p.returncode == 0:
                    dependencies.append(out.splitlines()[-1])
                else:
                    dependencies.append(dep_alias_name)

        return dependencies

    def _parse_pkgbuild_file(self):
        """Parse package information from PKGBUILD file."""
        pkgbuild_file = os.path.join(self.path, "PKGBUILD")
        with open(pkgbuild_file, 'r') as f:
            file_content = f.read()

        # package name
        self.name = self._parse_from_string('pkgname', file_content)
        self.build_from_git = self.name.endswith('-git')

        # package version (combined with release)
        version = self._parse_from_string('pkgver', file_content)
        release = self._parse_from_string('pkgrel', file_content)
        self.version = version + '-' + release

        # package architecture
        architectures = self._parse_from_string('arch', file_content)
        for ac_arch in accepted_architectures:
            if ac_arch in architectures:
                self.architecture = ac_arch
                break
        if not self.architecture:
            raise InvalidPackageSourceError(
                "Architecture of the package '{0}' is not supported".format(os.path.basename(self.path)))

        # package license
        self.license = self._parse_from_string('license', file_content)

        # raise an error if PKGBUILD file does not contain mandatory variables
        if not self.name or \
           not version or \
           not release or \
           not self.architecture or \
           not self.license:
            raise InvalidPackageSourceError(
                "One or more mandatory variables (name, version, release, architecture, license) in the package '{0}' is missing".format(os.path.basename(self.path)))

        # package dependencies
        self.dependencies = self._get_dependencies_from_alias(
            self._parse_from_string('depends', file_content))

        # package make dependencies
        self.make_dependencies = self._get_dependencies_from_alias(
            self._parse_from_string('makedepends', file_content))

        # package repository
        self.repository = PackageRepository.LOCAL

    def _copy_source_to_build_dir(self):
        """Copy the package source to the build dir."""
        pkg_build_dir = os.path.join(build_dir, self.name)

        if os.path.exists(pkg_build_dir) and \
           os.path.isdir(pkg_build_dir) and \
           (not self.remove_dowloaded_source or not self.build_from_git):
            old_pkgbuild_file = os.path.join(pkg_build_dir,
                                             'PKGBUILD')
            if os.path.exists(old_pkgbuild_file) and \
               os.path.isfile(old_pkgbuild_file):
                try:
                    old_pkg_source = PackageSource(
                        self.name, False, pkg_build_dir)
                    if old_pkg_source.version == self.version:
                        if self.repository == PackageRepository.AUR:
                            shutil.rmtree(self.path, ignore_errors=True)
                        self.path = pkg_build_dir
                        return
                except:
                    pass

        shutil.rmtree(pkg_build_dir, ignore_errors=True)
        shutil.copytree(self.path, pkg_build_dir)
        if self.repository == PackageRepository.AUR:
            shutil.rmtree(self.path, ignore_errors=True)
        self.path = pkg_build_dir

    def _download_aur_package_source(self):
        """Fetch package source from the AUR."""
        aur_pkg_download_path = tempfile.mkdtemp()
        try:
            i = aur.info(self.name)
        except:
            raise NoSuchPackageError(
                "No package with the name '{0}' exists in the AUR".format(self.name))

        pkg_tar_file_path = os.path.join(aur_pkg_download_path,
                                         i.name + ".tar.gz")
        # download package sources from AUR
        urllib.request.urlretrieve("https://aur.archlinux.org" +
                                   i.url_path,
                                   pkg_tar_file_path)
        # extract source tarball
        tar = tarfile.open(pkg_tar_file_path)
        tar.extractall(path=aur_pkg_download_path)
        tar.close()
        os.remove(pkg_tar_file_path)

        self.path = os.path.join(aur_pkg_download_path, i.name)

    def makepkg(self, uid, gid):
        """Run makepkg.

        Args:
            uid (int): UID of the build user
            gid (int): GID of the build user

        Returns:
            bool.  True if build was successfull, False if not

        """
        self._copy_source_to_build_dir()

        # set uid and gid of the build dir
        os.chown(self.path, uid, gid)
        for root, dirs, files in os.walk(self.path):
            for f in dirs + files:
                if os.path.isfile(f) or os.path.isdir(f):
                    os.chown(os.path.join(root, f), uid, gid)

        printInfo("Building package {0} {1}...".format(
            self.name, self.version))
        os.chdir(self.path)

        rc, err = run_command(['makepkg', '--force', '--nodeps', '--noconfirm'], uid)
        if rc != 0:
            self.error_info = Exception("Failed to build package '{0}': {1}".format(
                self.name, '\n'.join(err)))
            return False

        # get new version info when build from git
        if self.build_from_git:
            git_pkg = PackageSource(
                self.name, False, self.path)
            self.version = git_pkg.version

        full_package_path = os.path.join(
            pacman_cache_dir, self.get_package_file_name())
        # copy created package
        shutil.move(os.path.join(self.path, self.get_package_file_name()),
                    full_package_path)
        # set uid and gid of the build package
        os.chown(full_package_path, 0, 0)

        if self.is_make_dependency:
            printInfo("Installing package '{0}', version '{1}'...".format(
                self.name, self.version))
            rc, err = run_command(['pacman', '-U', '--noconfirm', '--force',
                                   '--ignore', 'package-query', '--ignore', 'pacman-mirrorlist',
                                   '--cachedir', pacman_cache_dir, full_package_path])
            if rc != 0:
                self.installation_status = 2
                self.error_info = Exception(
                    "Failed to install package '{0}': {1}".format(self.name, '\n'.join(err)))
                return False
            self.installation_status = 1

        return True

    def get_package_file_name(self):
        """Get the pacman package file name.

        Returns:
            str.  The name of the package

        """
        return '{0}-{1}-{2}.pkg.tar.xz'.format(
            self.name, self.version, self.architecture)

    def get_all_dependencies(self):
        """Get dependencies and make dependencies together.

        Returns:
            list.  Names of all dependencies

        """
        return self.dependencies + self.make_dependencies


def change_user(uid):
    """Temporarily change the UID and GID for code execution."""
    def set_uid_and_guid():
        os.setuid(uid)
    return set_uid_and_guid


def run_command(command, uid=None, print_output=True):
    """Run a command in a subprocess.

    Args:
        command (string): Command to run
        uid (int): UID of the user to run with
        print_output (bool): True if the output should be printed to stdout and stderr

    Returns:
        (int, list).  Return code of the subprocess and the stderr if any

    """
    if uid:
        process = Popen(command, stdout=PIPE, stderr=PIPE, universal_newlines=True, preexec_fn=change_user(uid))
    else:
        process = Popen(command, stdout=PIPE, stderr=PIPE, universal_newlines=True)
    err = []
    while True:
        out = process.stdout.readline()
        if out:
            if print_output:
                print(out.rstrip('\n'))
        if process.poll() is not None:
            break
        time.sleep(.05)

    if print_output:
        for line in process.stdout.readlines():
            print(line.rstrip('\n'))
    rc = process.poll()
    if rc != 0:
        for line in process.stderr.readlines():
            if print_output:
                printError(line.rstrip('\n'))
            err.append(line.rstrip('\n'))
    return (rc, err)


def get_package_recursive(pkg_name,
                          explicit_build,
                          pkg_dict,
                          locally_available_package_sources,
                          remove_dowloaded_source,
                          is_make_dependency):
    """Get a package and all their dependencies.

    Args:
        pkg_name (str): Name of the package
        explicit_build (bool): True if package source is given by the user
        pkg_dict (dict): Store for package information
        locally_available_package_sources (list): List of all locally available package sources
        remove_dowloaded_source (bool): If True remove the source downloaded by 'makepkg' before build. If False
            the sources will be kept, under the condition that the source is of the same
            version of the package to be build
        is_make_dependency (bool): True if package shall be installed as a make dependency

    """
    # check if package is already in pkg_dict
    if pkg_name in pkg_dict:
        return

    # check if package is in official repo
    for pcm_info in packages_in_offical_repositories:
        if pcm_info['id'] == pkg_name:
            pcm_pkg = PacmanPackage(pkg_name)
            pcm_pkg.is_make_dependency = is_make_dependency
            pkg_dict[pkg_name] = pcm_pkg
            return

    # check if package source is locally available
    if pkg_name in locally_available_package_sources:
        pkg_path = os.path.join(local_source_dir, pkg_name)
        lcl_pkg = PackageSource(pkg_name, remove_dowloaded_source, pkg_path)
        lcl_pkg.explicit_build = explicit_build
        lcl_pkg.explicit_build = is_make_dependency
        pkg_dict[pkg_name] = lcl_pkg
        if not lcl_pkg.error_info:
            for dependency in lcl_pkg.dependencies:
                get_package_recursive(dependency,
                                      False,
                                      pkg_dict,
                                      locally_available_package_sources,
                                      remove_dowloaded_source,
                                      True if is_make_dependency else False)
            for make_dependency in lcl_pkg.make_dependencies:
                get_package_recursive(make_dependency,
                                      False,
                                      pkg_dict,
                                      locally_available_package_sources,
                                      remove_dowloaded_source,
                                      True)

    # check for the package in the AUR
    else:
        aur_pkg = PackageSource(pkg_name, remove_dowloaded_source, None)
        aur_pkg.explicit_build = explicit_build
        pkg_dict[pkg_name] = aur_pkg
        if not aur_pkg.error_info:
            for dependency in aur_pkg.dependencies:
                get_package_recursive(dependency,
                                      False,
                                      pkg_dict,
                                      locally_available_package_sources,
                                      remove_dowloaded_source,
                                      True if is_make_dependency else False)
            for make_dependency in aur_pkg.make_dependencies:
                get_package_recursive(make_dependency,
                                      False,
                                      pkg_dict,
                                      locally_available_package_sources,
                                      remove_dowloaded_source,
                                      True)


def build_package_recursive(pkg_name,
                            pkg_dict,
                            rebuild,
                            install_all_dependencies,
                            uid,
                            gid):
    """Build a package and all their dependencies.

    Args:
        pkg_name (str): Name of the package
        pkg_dict (dict): Store for package information
        rebuild (int): Rebuild behaviour:
            0: Build only new versions of packages (default)
            1: Rebuild all explicit listed packages
            2: Rebuild all explicit listed packages and their dependencies
        uid (int): UID of the build user
        gid (int): GID of the build user

    """
    pkg = pkg_dict[pkg_name]

    # break if a error occurred
    if pkg.error_info:
        return

    if type(pkg) is PacmanPackage:
        # install pacman package if it is a make dependency
        if (pkg.is_make_dependency or install_all_dependencies) and pkg.installation_status != 1:
            pkg.install()
        return

    dependency_changed = False
    for dependency in pkg.get_all_dependencies():
        pkg_dependency = pkg_dict[dependency]
        build_package_recursive(dependency, pkg_dict, rebuild, install_all_dependencies, uid, gid)
        if pkg_dependency.error_info:
            pkg.build_status = 4
            return
        else:
            if type(pkg_dependency) is PackageSource and \
               pkg_dependency.build_status == 1:
                dependency_changed = True

    if dependency_changed:
        if pkg.makepkg(uid, gid):
            pkg.build_status = 1
        else:
            pkg.build_status = 3
        return
    else:
        # rebuild only if new version is available
        if rebuild == 0:
            if pkg.cache_available < 2:
                if pkg.makepkg(uid, gid):
                    pkg.build_status = 1
                else:
                    pkg.build_status = 3
                return

        # rebuild if explicit or a new version is available
        elif rebuild == 1:
            if pkg.cache_available < 2 or pkg.explicit_build:
                if pkg.makepkg(uid, gid):
                    pkg.build_status = 1
                else:
                    pkg.build_status = 3
                return

        # rebuild all
        elif rebuild == 2:
            if pkg.makepkg(uid, gid):
                pkg.build_status = 1
            else:
                pkg.build_status = 3
            return

    pkg.build_status = 2
    return


def format_log(pkg, msg, prefix=''):
    """Format a build log for a given packge.

    Args:
        pkg (PackageBase): The package
        msg (str): Message for the package
        prefix (str): Prefix added for message in multiple lines

    Returns:
        str.  The formatted build log

    """
    msg_lines = msg.splitlines()
    if len(msg_lines) > 1:
        for i in range(1, len(msg_lines)):
            msg_lines[i] = prefix + '    ' + msg_lines[i]
        msg = '\n'.join(msg_lines)

    if pkg.version:
        return "{0} {1}: {2}".format(pkg.name, pkg.version, msg)
    return "{0}: {1}".format(pkg.name, msg)


def print_build_log_recursive(pkg_names, pkg_dict, prefix=''):
    """Recursivly prints a build log for a given package.

    Args:
        pkg_names (PackageBase): The package
        pkg_dict (dict): Store for package information
        prefix (str): Prefix for the message

    Returns:
        (bool, list).  Tuple consting of the build status and the log messages as a list

    """
    successfull_build = True
    log = []
    log_prefix = prefix + '├── '
    intermediate_prefix = prefix + '|   '
    for pos, anchor, pkg_name in enumerate_package_names(pkg_names):
        pkg = pkg_dict[pkg_name]
        if anchor == 1:
            log_prefix = prefix + '└── '
            intermediate_prefix = prefix + '    '
        if pkg.error_info:
            successfull_build = False
            log.append(log_prefix + format_log(
                pkg, "Failed: " + str(pkg.error_info), log_prefix))
        else:
            if type(pkg) == PacmanPackage:
                log.append(log_prefix + format_log(pkg, "Installed"))
            else:
                mkdep = [dep for dep in pkg.make_dependencies]
                dep = [dep for dep in pkg.dependencies if type(
                    pkg_dict[dep]) == PackageSource]
                successfull_build, log_dep = print_build_log_recursive(
                    mkdep + dep,
                    pkg_dict,
                    intermediate_prefix)
                if successfull_build:
                    if pkg.build_status == 2:
                        log.append(
                            log_prefix + format_log(pkg, "Skipped build"))
                    elif pkg.build_status == 3:
                        log.append(log_prefix + format_log(pkg, "Failed"))
                        successfull_build = False
                    elif pkg.build_status == 4:
                        log.append(log_prefix + format_log(
                            pkg, "Dependency Failed"))
                        successfull_build = False
                    else:
                        log.append(log_prefix + format_log(
                            pkg, "Successfull build"))
                else:
                    log.append(
                        log_prefix + format_log(pkg, "Dependency Failed"))
                log = log + log_dep

    return successfull_build, log


def print_build_log(pkg_name, pkg_dict):
    """Recursivly prints a build log for a given package.

    Args:
        pkg_names (PackageBase): The package
        pkg_dict (dict): Store for package information

    """
    log = []
    successfull_build = True
    pkg = pkg_dict[pkg_name]
    if pkg.error_info:
        log.append(format_log(pkg, "Failed: " + str(pkg.error_info)))
        successfull_build = False
    else:
        mkdep = [dep for dep in pkg.make_dependencies]
        dep = [dep for dep in pkg.dependencies if type(
            pkg_dict[dep]) == PackageSource]
        successfull_build, log_dep = print_build_log_recursive(
            mkdep + dep,
            pkg_dict,
            '')
        if successfull_build or pkg.build_status == 4:
            if pkg.build_status == 2:
                log.append(format_log(pkg, "Skipped build"))
            elif pkg.build_status == 3:
                log.append(format_log(pkg, "Failed"))
                successfull_build = False
            elif pkg.build_status == 4:
                log.append(format_log(pkg, "Dependency Failed"))
                successfull_build = False
            else:
                log.append(format_log(pkg, "Successfull build"))
        else:
            log.append(format_log(pkg, "Dependency Failed"))
        log = log + log_dep

    for line in log:
        if successfull_build:
            printSuccessfull(line)
        else:
            printError(line)


def enumerate_package_names(sequence):
    length = len(sequence)
    for count, value in enumerate(sequence):
        yield count, length - count, value


def main(argv):
    """Run the main logic.

    Args:
        argv (list): Command line arguments

    """
    parser = argparse.ArgumentParser(
        prog='aur-makepkg',
        description='Build Pacman packages with makepkg from local source or the AUR',
        epilog=''
    )
    parser.add_argument('-g', '--gid', dest='gid', type=int, default=1000,
                        help="GID of the build user")
    parser.add_argument('-i', '--install-all-dependencies', action='store_true',
                        dest='install_all_dependencies', default=False,
                        help="Install all dependencies, not only 'make dependencies'")
    parser.add_argument('-k', '--keyrings', dest='keyrings', default=None,
                        help="Pacman keyrings initialized prior building (comma seperated list)")
    parser.add_argument('-p', '--pacman-update', action='store_true',
                        dest='pacman_update', default=False,
                        help="Update all installed pacman packages before build")
    parser.add_argument('-r', '--rebuild', dest='rebuild', type=int, default=0,
                        help="""Rebuild behaviour:
                            0: Build only new versions of packages (default)
                            1: Rebuild all explicit listed packages
                            2: Rebuild all explicit listed packages and their dependencies""")
    parser.add_argument('--remove-downloaded-source',
                        dest='remove_dowloaded_source',
                        action='store_true', default=False,
                        help="""Remove the source downloaded by 'makepkg' before build. If not
                            the sources will be kept, under the condition that the source is of the same
                            version of the package to be build. (Note: Sources of packages build from a Git repository
                            will always be removed.)""")
    parser.add_argument('-u', '--uid', dest='uid', type=int, default=1000,
                        help="UID of the build user")
    parser.add_argument('build_package_names', nargs='+',
                        help="Name fo packages to be build from local source or the AUR")
    args = parser.parse_args(argv)

    # create build user and group
    try:
        grp.getgrgid(args.gid)
    except Exception:
        os.system("groupadd -g {0} build-user".format(args.gid))
    try:
        pwd.getpwuid(args.uid)
    except Exception:
        os.system(
            "useradd -p /makepkg/build -m -g {1} -s /bin/bash -u {0} build-user".format(args.uid, args.gid))

    # refresh pacman package database
    if args.keyrings:
        printInfo("Initializing pacman keyring...")
        run_command(['pacman-key', '--init'], print_output=False)
        rc, err = run_command(['pacman-key', '--populate'] + args.keyrings.split(','), print_output=True)
        if rc != 0:
            raise Exception("Failed to initialize Pacman keyrings: " + '\n'.join(err))

    # refresh pacman package database
    printInfo("Update pacman package database...")
    pacman.refresh()

    global packages_in_cache, packages_in_offical_repositories
    packages_in_cache = [x for x in os.listdir(pacman_cache_dir) if
                         os.path.isfile(os.path.join(pacman_cache_dir, x))]
    packages_in_offical_repositories = pacman.get_available()

    if args.pacman_update:
        # upgrade installed pacman packages
        printInfo("Upgrading installed pacman packages...")
        rc, err = run_command(['pacman', '-Su', '--noconfirm', '--force',
                               '--ignore', 'package-query', '--ignore', 'pacman-mirrorlist',
                               '--cachedir', pacman_cache_dir], print_output=True)
        if rc != 0:
            raise Exception("Failed to upgrade Pacman packages: " + '\n'.join(err))

    pkg_dict = dict()

    # look for local package sources
    locally_available_package_sources = []
    if os.path.exists(local_source_dir) and \
       os.path.isdir(local_source_dir):
        for d in os.listdir(local_source_dir):
            pkgbuild_file_path = os.path.join(d, "PKGBUILD")
            if os.path.exists(pkgbuild_file_path) and \
               os.path.isfile(pkgbuild_file_path):
                locally_available_package_sources.append(os.path.basename(d))

    # get packages and their dependencies
    for pkg_name in args.build_package_names:
        printInfo("Collecting information about {0}...".format(pkg_name))
        get_package_recursive(pkg_name,
                              True,
                              pkg_dict,
                              locally_available_package_sources,
                              args.remove_dowloaded_source,
                              False)

    # build packages
    os.makedirs(build_dir, exist_ok=True)
    os.chown(build_dir, args.uid, args.gid)
    for pkg_name in args.build_package_names:
        build_package_recursive(pkg_name,
                                pkg_dict,
                                args.rebuild,
                                args.install_all_dependencies,
                                args.uid,
                                args.gid)

    # print build statistics
    printInfo("\nBuild Statistics:")
    for pkg_name in args.build_package_names:
        print_build_log(pkg_name, pkg_dict)


try:
    main(sys.argv[1:])
    exit(0)
except Exception as e:
    printError(str(e))
    exit(1)
