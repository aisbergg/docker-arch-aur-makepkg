FROM nfnty/arch-mini
MAINTAINER Andre Lehmann <andre.lehmann@posteo.de>

# install software
RUN curl -o /etc/pacman.d/mirrorlist "https://www.archlinux.org/mirrorlist/?country=all&protocol=https&ip_version=6&use_mirror_status=on" && sed -i 's/^#//' /etc/pacman.d/mirrorlist && \
    pacman -Syuq --noconfirm --noprogressbar --needed gnupg && \
    mkdir -p /root/.gnupg/ && \
    touch /root/.gnupg/dirmngr_ldapservers.conf && \
    pacman-key --refresh-keys && \
    pacman -S --noconfirm --noprogressbar --needed \
        base-devel \
        namcap \
        pkgbuild-introspection \
        git \
        mercurial \
        bzr \
        subversion \
        python \
        python-pip && \
    pip install aur && \
    rm -rf /var/cache/pacman/pkg/*

# create user and create build dir
RUN useradd -d /tmp/build -u 1000 -g 0 build-user && \
    mkdir -p /tmp/build && \
    chown build-user /tmp/build

# copy files
COPY run.py /run.py
COPY sudoers /etc/sudoers

VOLUME "/makepkg"

ENTRYPOINT ["python3", "/run.py"]
