#!/bin/bash
# vfos: {"abi": "2.14", "build_depends": ["gcc", "binutils", "make", "bison", "flex", "python", "pkgconf"], "depends": ["glibc", "gettext", "freetype", "fuse3"], "name": "grub", "patches": [], "sources": [{"filename": "grub-2.14.tar.xz", "sha256": "bc8d3c73535b8838d8c8e2654d73edc4e6ae8c8acdb45d5df5dc9a1547446d43", "url": "https://ftp.gnu.org/gnu/grub/grub-2.14.tar.xz"}], "version": "2.14"}
set -euo pipefail
prepare() { :; }
build() {
    for target in i386-pc i386-efi x86_64-efi; do
        mkdir -p "build-$target"
        ( cd "build-$target"
          ../configure --prefix=/usr --sbindir=/usr/sbin --sysconfdir=/etc \
            --target="${target%-*}" --with-platform="${target#*-}" \
            --disable-werror --disable-nls --disable-grub-mount --disable-grub-emu
          make -j"$JOBS"
        )
    done
}
check() {
    for target in i386-pc i386-efi x86_64-efi; do
        for module in xfs luks2 argon2 cryptodisk pbkdf2; do
            test -f "build-$target/grub-core/$module.mod"
        done
    done
}
stage() {
    for target in i386-pc i386-efi x86_64-efi; do
        make -C "build-$target" DESTDIR="$DESTDIR" install
    done
}
