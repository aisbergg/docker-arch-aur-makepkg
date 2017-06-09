FROM nfnty/arch-mini
MAINTAINER Andre Lehmann <andre.lehmann@posteo.de>

RUN curl -s -o /etc/pacman.d/mirrorlist "https://www.archlinux.org/mirrorlist/?country=DE&protocol=https&ip_version=6&use_mirror_status=on" && sed -i 's/^#//' /etc/pacman.d/mirrorlist &&\
    pacman -Syuq --noconfirm --noprogressbar --needed gnupg &&\
    mkdir -p /root/.gnupg/ &&\
    touch /root/.gnupg/dirmngr_ldapservers.conf &&\
    pacman-key --refresh-keys &&\
    pacman -S --noconfirm --noprogressbar --needed \
        base-devel \
        pkgbuild-introspection \
        git \
        mercurial \
        bzr \
        subversion \
        wget \
        yajl \
        python \
        python-pip &&\
    `# install python module requirements` &&\
    pip install python-pacman aur &&\
    rm -rf /var/cache/pacman/pkg/* /var/lib/pacman/sync/*

# install package-query
RUN curl -q https://aur.archlinux.org/cgit/aur.git/snapshot/package-query.tar.gz -o /tmp/package-query.tar.gz &&\
    tar -xf /tmp/package-query.tar.gz -C /tmp &&\
    chown -R nobody /tmp/package-query &&\
    pushd /tmp/package-query >/dev/null &&\
    su -s /bin/sh -c "makepkg -i --noconfirm" nobody &&\
    pacman -U --noconfirm --noprogressbar package-query*.pkg.tar.xz &&\
    popd >/dev/null &&\
    rm -r /tmp/package-query

COPY run.py /run.py
COPY pacman.conf /etc/pacman.conf

VOLUME /makepkg \
    /var/cache/pacman/pkg

ENTRYPOINT ["python3", "/run.py"]
