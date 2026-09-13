#!/bin/bash
# vfos: {"abi": "1", "build_depends": ["make", "pkgconf"], "depends": ["libx11", "libxft", "fontconfig"], "name": "st", "patches": [], "sources": [{"filename": "st-0.9.3.tar.gz", "sha256": "9ed9feabcded713d4ded38c8cebf36a3b08f0042ef7934a0e2b2409da56e649b", "url": "https://dl.suckless.org/st/st-0.9.3.tar.gz"}], "version": "0.9.3"}
set -euo pipefail
prepare() { :; }
build() { make -j"$JOBS" CC=gcc CFLAGS="$CFLAGS $(pkg-config --cflags xft)" LDFLAGS="$LDFLAGS $(pkg-config --libs x11 xft fontconfig)"; }
check() { test -x st; }
stage() { make PREFIX=/usr DESTDIR="$DESTDIR" install; install -Dm644 config.def.h "$DESTDIR/usr/share/vfos/st/config.def.h"; }
