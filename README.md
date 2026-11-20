# Call of Juarez Gunslinger FEX fixes

Fixes intermittent sprinting and missing prerendered cutscenes in the Steam version of Call of Juarez Gunslinger on Apple Silicon with CrossOver Preview and FEX.

## Setup

You need your own Windows Steam installation of the game, the ARM64/FEX build of CrossOver Preview, Python 3.9 or newer, and the Xcode Command Line Tools. The reference CrossOver build is **27.0.0.41073**, which bundles GStreamer 1.28.4. The patcher checks the SHA-256 of the original Steam executable before creating a patched copy.

Download and extract the source archive from the release, then open Terminal in the extracted directory. Replace the example path with your Steam game folder.

```sh
./setup.sh "/path/to/CoJ Gunslinger"
```

Leave the Windows Steam client open in the CrossOver bottle and launch the game from the same directory.

```sh
./launch.sh "/path/to/CoJ Gunslinger"
```

The default app is CrossOver Preview in Applications and the default bottle is `Steam`. Set `COJ_CROSSOVER_APP` to the app’s absolute path for both commands if it lives elsewhere. Set `COJ_CROSSOVER_BOTTLE` for the launch command if your bottle has a different name. The launcher uses the bottle’s standard `Z:` drive mapping to the macOS filesystem.

## What the fixes do

- **Sprint.** The game uses 24-bit x87 arithmetic and stores its sprint deadline in a 32-bit float. Reduced-precision FEX retains extra bits during arithmetic. With zero grace, the current time can compare greater than its own rounded deadline and cancel sprint immediately. The patch rounds the current time to the same format immediately before the comparison, preserving the timeout and leaving FEX’s fast mode enabled.
- **Cutscenes.** The game uses `wmvcore.dll` to play WMV3 video with WMA audio. The setup script extracts ARM64 `gst-libav` and its dependencies from a checksum-pinned official [GStreamer package](https://gstreamer.freedesktop.org/pkg/macos/1.28.4/). It builds the small GLib compatibility shim and stages the libraries beside the launcher. The launcher sets the codec path for this session.

Setup creates `CoJGunslinger-FEX.exe` beside your original EXE and a `codec/` directory here. To remove the fixes, delete those two generated outputs. The distribution contains the patcher, setup code, and launcher. It uses the original executable and movies from your installation.

## Sprint-only patch

You can generate the sprint fix independently of the macOS codec setup.

```sh
python3 make-sprint-trace.py --sprint-clock-fix "/path/to/CoJGunslinger.exe" "/path/to/CoJGunslinger-FEX.exe"
```
