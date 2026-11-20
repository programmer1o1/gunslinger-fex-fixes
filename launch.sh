#!/bin/bash
set -euo pipefail

if [[ $# == 0 ]]; then
    printf 'Usage: %s /path/to/CoJ Gunslinger [game arguments]\n' "$0" >&2
    exit 2
fi

repo=$(cd -- "$(dirname -- "$0")" && pwd -P)
game=$(cd -- "$1" && pwd -P)
shift
app=$(cd -- "${COJ_CROSSOVER_APP:-/Applications/CrossOver Preview.app}" && pwd -P)
cx="$app/Contents/SharedSupport/CrossOver"
bottle=${COJ_CROSSOVER_BOTTLE:-Steam}
exe=CoJGunslinger-FEX.exe

if [[ ! -f "$game/$exe" || ! -f "$repo/codec/plugins/libgstlibav.dylib" ||
      ! -f "$repo/codec/.crossover-root" || $(cat "$repo/codec/.crossover-root") != "$cx" ]]; then
    printf 'Run setup.sh with this game directory and CrossOver app first.\n' >&2
    exit 1
fi

export GST_PLUGIN_PATH="$repo/codec/plugins${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"
export SteamAppId=204450 SteamGameId=204450 FEX_X87REDUCEDPRECISION=1
windows_game="Z:${game//\//\\}"
exec "$cx/bin/wine" --bottle "$bottle" --workdir "$windows_game" \
    --cx-app "$windows_game\\$exe" "$@"
