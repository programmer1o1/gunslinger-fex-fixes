#!/bin/bash
set -euo pipefail

if [[ $# != 1 ]]; then
    printf 'Usage: %s /path/to/CoJ Gunslinger\n' "$0" >&2
    exit 2
fi

repo=$(cd -- "$(dirname -- "$0")" && pwd -P)
game=$(cd -- "$1" && pwd -P)
app=$(cd -- "${COJ_CROSSOVER_APP:-/Applications/CrossOver Preview.app}" && pwd -P)
cx="$app/Contents/SharedSupport/CrossOver"
host_lib="$cx/lib/aarch64"
if [[ $(uname -m) != arm64 || ! -x "$cx/bin/wine" ||
      ! -f "$host_lib/libglib-2.0.0.dylib" ||
      ! -f "$host_lib/libgstreamer-1.0.0.dylib" ]]; then
    printf 'This setup needs Apple Silicon and an ARM64 CrossOver Preview runner.\n' >&2
    exit 1
fi

game_stage=$(mktemp -d "$game/.gunslinger-fex.XXXXXX")
build_stage=
trap 'rm -rf -- "$game_stage"; if [[ -n "$build_stage" ]]; then rm -rf -- "$build_stage"; fi' EXIT

exe=CoJGunslinger-FEX.exe
python3 "$repo/make-sprint-trace.py" --sprint-clock-fix \
    "$game/CoJGunslinger.exe" "$game_stage/$exe"
if [[ -e "$game/$exe" ]] && ! cmp -s "$game_stage/$exe" "$game/$exe"; then
    printf 'A different %s already exists in the game folder.\n' "$exe" >&2
    exit 1
fi

if [[ -d "$repo/codec" ]]; then
    if [[ ! -f "$repo/codec/.crossover-root" ||
          $(cat "$repo/codec/.crossover-root") != "$cx" ||
          ! -f "$repo/codec/plugins/libgstlibav.dylib" ]]; then
        printf 'The existing codec directory belongs to a different setup.\n' >&2
        exit 1
    fi
else
    xcrun --find clang >/dev/null
    build_stage=$(mktemp -d "$repo/.codec-build.XXXXXX")
    pkg="$build_stage/gstreamer.pkg"
    if [[ -n ${COJ_GSTREAMER_PKG:-} ]]; then
        pkg=$COJ_GSTREAMER_PKG
    else
        curl --fail --location --retry 2 --show-error \
            https://gstreamer.freedesktop.org/pkg/macos/1.28.4/gstreamer-1.0-1.28.4-universal.pkg \
            --output "$pkg"
    fi
    expected=9f9ae8ba1a25eb42d6740c4e5f15b09ee6b9127b7359e9662c45a2b9a5029f85
    actual=$(shasum -a 256 < "$pkg" | awk '{print $1}')
    if [[ "$actual" != "$expected" ]]; then
        printf 'The GStreamer package checksum did not match.\n' >&2
        exit 1
    fi

    pkgutil --expand-full "$pkg" "$build_stage/expanded"
    libav="$build_stage/expanded/gstreamer-1.0-libav-1.28.4-universal.pkg/Payload/lib"
    bzip="$build_stage/expanded/base-system-1.0-1.28.4-universal.pkg/Payload/lib/libbz2.1.dylib"
    codec="$build_stage/codec"
    mkdir -p "$codec/lib" "$codec/plugins"
    plugin="$codec/plugins/libgstlibav.dylib"
    xcrun lipo -thin arm64 "$libav/gstreamer-1.0/libgstlibav.dylib" -output "$plugin"
    for name in libavcodec.61 libavfilter.10 libavformat.61 libavutil.59 libswresample.5 libswscale.8; do
        xcrun lipo -thin arm64 "$libav/$name.dylib" -output "$codec/lib/$name.dylib"
    done
    xcrun lipo -thin arm64 "$bzip" -output "$codec/lib/libbz2.1.dylib"

    for library in "$plugin" "$codec/lib/"*.dylib; do
        base=@loader_path
        if [[ "$library" == "$plugin" ]]; then
            base=@loader_path/../lib
        fi
        dependencies=$(xcrun otool -L "$library" | tail -n +3 | awk '{print $1}')
        for dependency in $dependencies; do
            name=$(basename -- "$dependency")
            if [[ -f "$codec/lib/$name" ]]; then
                xcrun install_name_tool -change "$dependency" "$base/$name" "$library"
            fi
        done
    done

    xcrun install_name_tool -add_rpath "$host_lib" "$plugin"
    shim="$codec/lib/libcoj-glib-once.dylib"
    glib="$host_lib/libglib-2.0.0.dylib"
    xcrun clang -arch arm64 -dynamiclib -install_name @rpath/libcoj-glib-once.dylib \
        -Wl,-rpath,"$host_lib" -Wl,-reexport_library,"$glib" "$repo/glib-once.c" -o "$shim"
    glib_id=$(xcrun otool -D "$glib" | tail -1)
    if [[ "$glib_id" != @rpath/libglib-2.0.0.dylib ]]; then
        xcrun install_name_tool -change "$glib_id" @rpath/libglib-2.0.0.dylib "$shim"
    fi
    xcrun install_name_tool -change @rpath/libglib-2.0.0.dylib \
        @loader_path/../lib/libcoj-glib-once.dylib "$plugin"
    for library in "$plugin" "$codec/lib/"*.dylib; do
        codesign --force --sign - "$library"
        codesign --verify --strict "$library"
    done
    printf '%s\n' "$cx" > "$codec/.crossover-root"
    mv -- "$codec" "$repo/codec"
fi

chmod +x "$game_stage/$exe"
mv -n -- "$game_stage/$exe" "$game/$exe"
printf 'Setup complete. Run launch.sh with the same game directory.\n'
