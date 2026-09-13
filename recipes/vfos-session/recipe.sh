#!/bin/bash
# vfos: {"abi": "1", "build_depends": [], "depends": ["vfos-tools", "seatd", "dbus", "pipewire", "wireplumber"], "local_files": {"sessions/vfos-session": "files/vfos-session", "sessions/vfos-session-child": "files/vfos-session-child"}, "name": "vfos-session", "patches": [], "sources": [], "version": "0.1.0"}
set -euo pipefail
prepare() { :; }
build() { :; }
check() { test -s "$RECIPE_DIR/files/vfos-session"; }
stage() {
    install -Dm755 "$RECIPE_DIR/files/vfos-session" "$DESTDIR/usr/bin/vfos-session"
    install -Dm755 "$RECIPE_DIR/files/vfos-session-child" "$DESTDIR/usr/libexec/vfos-session-child"
}
