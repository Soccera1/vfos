#!/bin/bash
# vfos: {"abi": "1", "build_depends": ["make", "pkgconf"], "depends": ["libx11", "libxft", "libxinerama"], "name": "dwm", "patches": [], "sources": [{"filename": "dwm-6.6.tar.gz", "sha256": "7cfc2c6d9386c07c49e2c906f209c18ba3364ce0b4872eae39f56efdb7fc00a3", "url": "https://dl.suckless.org/dwm/dwm-6.6.tar.gz"}], "version": "6.6"}
set -euo pipefail
prepare() { :; }
build() { make -j"$JOBS" CC=gcc CFLAGS="$CFLAGS $(pkg-config --cflags xft)" LDFLAGS="$LDFLAGS $(pkg-config --libs x11 xft xinerama)"; }
check() { test -x dwm; }
stage() { make PREFIX=/usr DESTDIR="$DESTDIR" install; install -Dm644 config.def.h "$DESTDIR/usr/share/vfos/dwm/config.def.h"; }
