#!/bin/bash
# vfos: {"abi": "7.0", "build_depends": ["make", "pkgconf", "bash"], "depends": ["glibc", "util-linux", "liburcu", "inih"], "name": "xfsprogs", "patches": [], "sources": [{"filename": "xfsprogs-7.0.1.tar.xz", "sha256": "4a8ca83a7acb8cd92c997d63b69ae64f170056b366a2924a753e47d4bb4b8b06", "url": "https://www.kernel.org/pub/linux/utils/fs/xfs/xfsprogs/xfsprogs-7.0.1.tar.xz"}], "version": "7.0.1"}
set -euo pipefail
prepare() { :; }
build() {
    ./configure --prefix=/usr --sbindir=/usr/sbin --libdir=/usr/lib \
        --enable-lib64=no --enable-gettext=no --enable-editline=no --enable-termcap=no \
        --enable-scrub=no --enable-healer=no --enable-libicu=no \
        --enable-ubsan=no --enable-addrsan=no --enable-threadsan=no --enable-lto=no
    make -j"$JOBS"
}
check() { ./mkfs/mkfs.xfs -V; ./db/xfs_db -V; }
stage() {
    make DESTDIR="$DESTDIR" install install-dev
    rm -f "$DESTDIR/.chown.quiet"
}
