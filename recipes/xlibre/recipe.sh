#!/bin/bash
# vfos: {"abi": "xlibre-25.1", "build_depends": ["meson", "ninja", "pkgconf", "xorgproto", "xtrans"], "depends": ["glibc", "seatd", "eudev", "libdrm", "mesa", "libpciaccess", "libepoxy", "libxfont2", "libxcvt", "pixman", "xkeyboard-config", "xkbcomp", "libxshmfence"], "name": "xlibre", "patches": [], "sources": [{"filename": "xlibre-25.1.6.tar.gz", "sha256": "f03fe4a7b1a060ca5100b6e71537bcfe88a998ef9f7a3a8c094e3005d7203276", "url": "https://codeload.github.com/X11Libre/xserver/tar.gz/refs/tags/xlibre-xserver-25.1.6"}], "version": "25.1.6"}
set -euo pipefail
prepare() { :; }
build() {
    meson setup build --prefix=/usr --libdir=lib --buildtype=plain --wrap-mode=nodownload \
        -Dxorg=true -Dseatd_libseat=true -Dsystemd_logind=false -Dsystemd_notify=false \
        -Dsuid_wrapper=false -Dudev=true -Dudev_kms=true -Dglamor=true -Dgbm=true \
        -Dxdmcp=false -Dxdm-auth-1=false -Dlisten_tcp=false \
        -Dxephyr=false -Dxfbdev=false -Dxnest=false -Dxvfb=false -Dxwin=false -Dxquartz=false \
        -Dtests=false -Dxf86-input-inputtest=false -Dlegacy_nvidia_340x=false \
        -Ddocs=false -Ddevel-docs=false -Ddocs-pdf=false -Dxselinux=false -Dhal=false
    meson compile -C build -j "$JOBS"
}
check() {
    test -x build/hw/xfree86/Xorg
    test ! -e build/hw/xfree86/Xorg.wrap
}
stage() { meson install -C build --no-rebuild; }
