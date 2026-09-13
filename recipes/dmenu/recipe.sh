#!/bin/bash
# vfos: {"abi": "1", "build_depends": ["make", "pkgconf"], "depends": ["libx11", "libxft", "libxinerama"], "name": "dmenu", "patches": [], "sources": [{"filename": "dmenu-5.4.tar.gz", "sha256": "8fbace2a0847aa80fe861066b118252dcc7b4ca0a0a8f3a93af02da8fb6cd453", "url": "https://dl.suckless.org/tools/dmenu-5.4.tar.gz"}], "version": "5.4"}
set -euo pipefail
prepare() { :; }
build() { make -j"$JOBS" CC=gcc CFLAGS="$CFLAGS $(pkg-config --cflags xft)" LDFLAGS="$LDFLAGS $(pkg-config --libs x11 xft xinerama)"; }
check() { test -x dmenu; }
stage() { make PREFIX=/usr DESTDIR="$DESTDIR" install; install -Dm644 config.def.h "$DESTDIR/usr/share/vfos/dmenu/config.def.h"; }
