#!/usr/bin/python3
import argparse
import os
import sys
import re
import shutil
import glob
import tarfile
import urllib.request
from subprocess import Popen, PIPE

import aur

root_path = os.path.abspath("/makepkg")
local_package_source_path = os.path.join(root_path, "local_src")
build_path = os.path.abspath("/tmp/build")

class ConsoleColors:
    blue = '\033[94m'
    red = '\033[91m'
    yellow = '\033[93m'
    reset = '\033[0m'

class InvalidPackageSourceError(Exception):
    """ Invalid package source exception

    Args:
        message (str): Message passed with the exception

    """
    def __init__(self, message):
        super(Exception, self).__init__(message)


class InvalidPacmanPackageError(Exception):
    """ Invalid pacman package exception

    Args:
        message (str): Message passed with the exception

    """
    def __init__(self, message):
        super(Exception, self).__init__(message)

class PacmanUpgradeError(Exception):
    """ Pacman upgrade exception

    """
    def __init__(self):
        super(Exception, self).__init__("Failed to upgrade packages with pacman")


def printInfo(message):
    print(ConsoleColors.blue + message + ConsoleColors.reset)

def printWarning(message):
    print(ConsoleColors.yellow + message + ConsoleColors.reset)

def printError(message):
    print(ConsoleColors.red + message + ConsoleColors.reset)

class LocalPackageSource():
    """ Represents a local source of a package

    Args:
        path (str): Path which contains the source code of a package

    """
    name = None
    version = None
    path = None

    def __init__(self, path):
        self.path = os.path.abspath(path)
        pbpath = os.path.join(path, "PKGBUILD")
        if not os.path.exists(pbpath) and not os.path.isfile(pbpath):
            raise InvalidPackageSourceError("Local package source does not contain a 'PKGBUILD' file")
        self._parse_pkgbuild_file(pbpath)

        # copy to tmp build dir
        self.path = os.path.join(build_path, os.path.basename(self.path))
        if os.path.exists(self.path):
            shutil.rmtree(self.path)
        shutil.copytree(path, self.path)

    def _parse_from_string(self, name, string):
        """ Parses a value for a param from a string

        Args:
            name (str): Name of the param to parse
            string (str): String containing all params

        Returns:
            str.  Value for given params
            None.  If given param wasn't found

        """
        match = re.compile(r'{0}=(.+)'.format(name)).search(string)
        if match:
            return match.group(1).strip("\" ")
        return None

    def _parse_pkgbuild_file(self, pkgbuild_path):
        """ Parses package information from PKGBUILD file

        Args:
            pkgbuild_path (str): Path PKGBUILD file

        """
        with open(pkgbuild_path, 'r') as f:
            file_content = f.read()

        self.name = self._parse_from_string("pkgname", file_content)
        version = self._parse_from_string("pkgver", file_content)
        release = self._parse_from_string("pkgrel", file_content)

        if not self.name or not version or not release:
            raise InvalidPackageSourceError(self.path)
        self.version = version + '-' + release


class PacmanPackage:
    """ Represents a ready made pacman package

    Args:
        path (str): Path to a compressed pacman package

    """
    name = None
    version = None
    path = None

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self._get_package_info()

    def _parse_from_string(self, name, string):
        """ Parses a value for a param from a string

        Args:
            name (str): Name of the param to parse
            string (str): String containing all params

        Returns:
            str.  Value for given params
            None.  If given param wasn't found

        """
        match = re.compile(r'{0} = (.+)'.format(name)).search(string)
        if match:
            return match.group(1)
        return None

    def _get_package_info(self):
        """ Parses package information from compressed tar file

        """
        if not os.path.isfile(self.path):
            raise InvalidPacmanPackageError(self.path)

        tar = tarfile.open(self.path, mode='r:xz')
        pkginfo = None

        for tarinfo in tar:
            if tarinfo.name == ".PKGINFO":
                pkginfo = tarinfo.name
                break

        if not pkginfo and not pkginfo.isfile():
            tar.close()
            raise InvalidPacmanPackageError(self.path)

        pkginfo_file_content = tar.extractfile(pkginfo).read().decode("utf-8")
        tar.close()

        self.name = self._parse_from_string("pkgname", pkginfo_file_content)
        self.version = self._parse_from_string("pkgver", pkginfo_file_content)
        if not self.version or not self.name:
            raise InvalidPacmanPackageError(self.path)


def changeUser():
	""" Change the UID for code execution

    """
	def setUID():
		os.setuid(1000)
	return setUID

def makepkg(path):
    """ Runs makepkg

    Args:
        path (str): Path which contains the source code of a package

    """
    os.chown(path, 1000, -1)
    os.chdir(path)
    p = Popen(['makepkg', '--force', '--syncdeps', '--noconfirm'], stderr=PIPE, universal_newlines=True, preexec_fn=changeUser())
    p.wait()

    if p.returncode != 0:
        printError("Makepkg Error: {0}".format(p.stderr.read()))
        return False

    return True

def main(argv):
    """ Main logic

    Args:
        argv (list): Command line arguments

    """
    parser = argparse.ArgumentParser(
        prog='aur-makepkg',
        description='Build Pacman packages with makepkg from local source or the AUR',
        epilog=''
    )
    parser.add_argument('-g', '--gid', dest='gid', type=int, default=-1,
                        help='GID for created packages')
    parser.add_argument('-k', '--keep-old-versions', dest='keep_old_versions',
                        action='store_true', default=False,
                        help='Keep older versions of a package after a newer one is build')
    parser.add_argument('-p', '--pacman-update', action='store_true',
                        dest='pacman_update', default=False,
                        help='')
    parser.add_argument('-u', '--uid', dest='uid', type=int, default=-1,
                        help='UID for created packages')
    parser.add_argument('package_names', nargs='+',
                        help='Name fo packages to be build from local source or the AUR')
    args = parser.parse_args(argv)

    if args.pacman_update:
        # upgrade pacman packages
        printInfo("Upgrading packages...")
        p = Popen(['pacman', '-Syu'], stdout=PIPE, stderr=PIPE)
        p.wait()
        if p.returncode != 0:
            raise PacmanUpgradeError()

    local_package_source = []
    aur_package_source = []
    if os.path.exists(local_package_source_path) and os.path.isdir(local_package_source_path):
        dir_list = os.listdir(local_package_source_path)
        for package_name in args.package_names:
            # check if local source is available
            if package_name in dir_list:
                local_package_source.append(LocalPackageSource(os.path.join(local_package_source_path, package_name)))

            # use AUR as source
            else:
                aur_package_source.append(aur.info(package_name))

    # get information about present pacman pacakges
    pacman_packages = dict()
    for f in os.listdir(root_path):
        fpath = os.path.join(root_path, f)
        if os.path.isfile(fpath) and f.endswith(".tar.xz"):
            pcmp = PacmanPackage(fpath)
            if pcmp.name in pacman_packages.keys():
                pacman_packages[pcmp.name].append(pcmp)
            else:
                pacman_packages[pcmp.name] = [pcmp]

    # create packages from local source
    latest = []
    succeeded = []
    failed = []
    for lcl_src in local_package_source:
        build = True
        if lcl_src.name in pacman_packages.keys():
            for pcm_pkg in pacman_packages[lcl_src.name]:
                if pcm_pkg.version == lcl_src.version:
                    build = False;
                    latest.append(lcl_src)
                    break
        if build:
            printInfo("Building package '{0}' from local source...".format(lcl_src.name))
            if makepkg(lcl_src.path):
                succeeded.append(lcl_src)
                # copy created package
                os.chdir(lcl_src.path)
                pcm_pkg_file = glob.glob("{0}-*.pkg.tar.xz".format(lcl_src.name))[0]
                dest = os.path.join(root_path, pcm_pkg_file)
                shutil.copyfile(pcm_pkg_file, dest)
                # set uid and gid
                os.chown(dest, args.uid, args.gid)
            else:
                failed.append(lcl_src)

    # create packages from AUR
    for aur_src in aur_package_source:
        build = True
        if aur_src.name in pacman_packages:
            for pcm_pkg in pacman_packages[aur_src.name]:
                if pcm_pkg.version == aur_src.version:
                    build = False;
                    latest.append(aur_src)
                    break
        if build:
            printInfo("Building package '{0}' from AUR...".format(aur_src.name))
            ppath = os.path.join(build_path, aur_src.name)
            if os.path.exists(ppath):
                shutil.rmtree(ppath)
            os.mkdir(ppath)
            urllib.request.urlretrieve("https://aur.archlinux.org" + aur_src.url_path, os.path.join(build_path, aur_src.name + ".tar.gz"))
            tar = tarfile.open(os.path.join(build_path, aur_src.name + ".tar.gz"))
            tar.extractall(path=build_path)
            tar.close()
            if makepkg(ppath):
                succeeded.append(aur_src)
                # copy created package
                os.chdir(ppath)
                pcm_pkg_file = glob.glob("{0}-*.pkg.tar.xz".format(aur_src.name))[0]
                dest = os.path.join(root_path, pcm_pkg_file)
                shutil.copyfile(pcm_pkg_file, dest)
                # set uid and gid
                os.chown(dest, args.uid, args.gid)
            else:
                failed.append(aur_src)

    if not args.keep_old_versions:
        # remove old packages
        for pkg_src in succeeded:
            if pkg_src.name in pacman_packages:
                for pcm_pkg in pacman_packages[lcl_src.name]:
                    os.remove(pcm_pkg.path)

    if len(succeeded) > 0:
        printInfo("Successfully build:")
        print(" - " + "\n - ".join([p.name for p in succeeded]))
    if len(latest) > 0:
        printInfo("Packges up to date:")
        print(" - " + "\n - ".join([p.name for p in latest]))
    if len(failed) > 0:
        printWarning("Faild to build:")
        print(" - " + "\n - ".join([p.name for p in failed]))

try:
    main(sys.argv[1:])
    exit(0)
except Exception as e:
    printError(str(e))
    exit(1)
