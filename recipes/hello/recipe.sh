#!/bin/bash
# vfos: {"abi": "1", "build_depends": [], "depends": [], "name": "hello", "patches": ["glibc-c23.patch"], "sources": [{"filename": "hello-2.12.2.tar.gz", "sha256": "5a9a996dc292cc24dcf411cee87e92f6aae5b8d13bd9c6819b4c7a9dce0818ab", "url": "https://ftp.gnu.org/gnu/hello/hello-2.12.2.tar.gz"}], "version": "2.12.2"}
set -euo pipefail
# Parenthesize gnulib declarations to avoid glibc C23 function-like macros.
prepare() { patch -p1 < "$RECIPE_DIR/glibc-c23.patch"; }
build() { ./configure --prefix=/usr --disable-nls; make -j"$JOBS"; }
check() { make check; }
stage() { make DESTDIR="$DESTDIR" install; }
