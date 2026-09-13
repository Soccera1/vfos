#!/bin/bash
# vfos: {"abi": "libseat-1", "build_depends": ["meson", "ninja", "pkgconf"], "depends": ["glibc"], "name": "seatd", "patches": [], "sources": [{"filename": "seatd-0.9.1.tar.gz", "sha256": "819979c922a0be258aed133d93920bce6a3d3565a60588d6d372ce9db2712cd3", "url": "https://git.sr.ht/~kennylevinsen/seatd/archive/0.9.1.tar.gz"}], "version": "0.9.1"}
set -euo pipefail
prepare() { :; }
build() {
    meson setup build --prefix=/usr --libdir=lib --buildtype=plain --wrap-mode=nodownload \
        -Dlibseat-seatd=enabled -Dlibseat-logind=disabled -Dlibseat-builtin=disabled \
        -Dserver=enabled -Dexamples=disabled -Dman-pages=disabled -Ddefaultpath=/run/seatd.sock
    meson compile -C build -j "$JOBS"
}
check() { meson test -C build --print-errorlogs; }
stage() {
    meson install -C build --no-rebuild
    rm -f "$DESTDIR/usr/bin/seatd-launch"
}
