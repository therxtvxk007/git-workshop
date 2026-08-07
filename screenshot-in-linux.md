# Taking Screenshots on Linux

Unlike macOS or Windows, Linux has no single built-in screenshot command. What
works depends on your **display server** (X11 or Wayland) and your **desktop
environment**. Start by identifying those, then pick a tool from the matching
section.

## 1. Find out what you're running

```sh
echo "$XDG_SESSION_TYPE"      # x11, wayland, or tty
echo "$XDG_CURRENT_DESKTOP"   # GNOME, KDE, XFCE, sway, ...
```

If `$XDG_SESSION_TYPE` is empty, fall back to:

```sh
loginctl show-session "$(loginctl | awk '/'"$USER"'/{print $1; exit}')" -p Type
```

Rules of thumb:

- `wayland` → X11 tools (scrot, maim, `import`) will fail or capture a black
  rectangle. Use `grim` or the desktop's own tool.
- `x11` → almost everything works, including X11-only tools.
- `tty` → no graphical session at all; see [Console / framebuffer](#7-console--framebuffer-no-x-or-wayland).

## 2. Desktop shortcuts (no install needed)

| Desktop | Full screen | Region | Active window |
|---|---|---|---|
| GNOME | `PrtSc` | `Shift`+`PrtSc` | `Alt`+`PrtSc` |
| KDE Plasma | `PrtSc` (opens Spectacle) | `Shift`+`PrtSc` | `Meta`+`PrtSc` |
| XFCE | `PrtSc` (xfce4-screenshooter) | `Shift`+`PrtSc` | `Alt`+`PrtSc` |
| Cinnamon | `PrtSc` | `Shift`+`PrtSc` | `Alt`+`PrtSc` |

On GNOME 42+ `PrtSc` opens an interactive overlay with screen/window/region
buttons and a screen-recording toggle. Files land in `~/Pictures/Screenshots`.

## 3. X11 command line

### scrot — simplest

```sh
sudo apt install scrot          # or: dnf install scrot / pacman -S scrot

scrot shot.png                  # whole screen
scrot -s region.png             # select a region or click a window
scrot -u -d 3 window.png        # active window, after a 3 second delay
scrot -d 5 -c countdown.png     # 5s delay, print a countdown
scrot '%Y-%m-%d_%H%M%S.png'     # strftime patterns in the filename
```

### maim — sharper, better multi-monitor support

```sh
maim shot.png
maim -s region.png                            # interactive region select
maim -i "$(xdotool getactivewindow)" win.png  # active window (needs xdotool)
maim -s | xclip -selection clipboard -t image/png   # straight to clipboard
```

### ImageMagick `import`

Already present on many systems as part of ImageMagick.

```sh
import -window root shot.png    # whole screen
import region.png               # click-drag to select a region
```

### xwd (ships with X.org, no extra packages)

```sh
xwd -root | convert xwd:- shot.png
```

## 4. Wayland command line

X11 tools cannot read other clients' buffers under Wayland — that's a
deliberate security boundary, not a bug. Use compositor-aware tools.

### grim + slurp (wlroots: sway, Hyprland, river, Wayfire)

```sh
sudo apt install grim slurp

grim shot.png                       # whole screen
grim -g "$(slurp)" region.png       # drag to select a region
grim -o DP-1 monitor.png            # a specific output; list them with `wlr-randr`
grim - | wl-copy                    # to the clipboard
```

On sway, `grimshot` wraps these with friendlier subcommands:

```sh
grimshot save area ~/Pictures/shot.png
grimshot copy window
```

### GNOME / KDE on Wayland

`grim` is blocked on GNOME (Mutter doesn't implement the wlroots protocol). Use
the desktop's own tooling or the portal:

```sh
# GNOME, via its D-Bus screenshot interface
gdbus call --session \
  --dest org.gnome.Shell.Screenshot \
  --object-path /org/gnome/Shell/Screenshot \
  --method org.gnome.Shell.Screenshot.Screenshot \
  true false "$HOME/Pictures/shot.png"

# KDE Plasma
spectacle -b -n -o ~/Pictures/shot.png    # background, no notification
spectacle -r                              # rectangular region
```

The portable path is the freedesktop portal
(`org.freedesktop.portal.Screenshot`), which works across compositors but
prompts the user for permission. Tools like `flameshot` and browser
screen-sharing use it under the hood.

## 5. GUI tools worth installing

- **Flameshot** — annotation (arrows, blur, text) right in the capture overlay.
  Best all-rounder. `flameshot gui`, `flameshot full -p ~/Pictures`. Wayland
  support needs `flameshot gui` with the portal and can be fiddly on GNOME.
- **Spectacle** (KDE) — delay, window-under-cursor, region memory.
- **Shutter** — capture plus a built-in editor and plugin effects.
- **ksnip** — cross-platform, good annotation, works on X11 and Wayland.

## 6. Screenshots on headless machines and in CI

No display? Create one, then capture it.

```sh
# Run a GUI app on a virtual X server and grab the result
sudo apt install xvfb x11-utils imagemagick
xvfb-run -a --server-args="-screen 0 1920x1080x24" sh -c '
  your-gui-app &
  sleep 5
  import -window root -display "$DISPLAY" /tmp/shot.png
'
```

For web pages, skip X entirely — headless browsers render straight to a file:

```sh
chromium --headless --disable-gpu \
         --screenshot=/tmp/page.png --window-size=1920,1080 https://example.com

# or with Playwright
npx playwright screenshot --viewport-size=1920,1080 https://example.com shot.png
```

Playwright and Puppeteer are the right answer for scripted, reliable page
captures — they wait for load/network-idle instead of racing a `sleep`.

### Capturing a remote machine over SSH

```sh
ssh user@host 'DISPLAY=:0 scrot /tmp/shot.png'
scp user@host:/tmp/shot.png .
```

`DISPLAY=:0` targets the physical session. This needs X11 on the remote host and
`xhost` permission for your user; note that `ssh -X` forwarding gives you a
*separate* display, not the one on the monitor.

## 7. Console / framebuffer (no X or Wayland)

```sh
sudo fbgrab tty.png             # from the fbcat package
sudo fbcat /dev/fb0 > tty.ppm   # raw, then convert
```

## 8. Recording video instead of a still

```sh
# X11
ffmpeg -f x11grab -framerate 30 -video_size 1920x1080 -i :0.0 out.mp4

# Wayland (wlroots)
wf-recorder -f out.mp4
wf-recorder -g "$(slurp)" -f region.mp4
```

GNOME and KDE both record with `Ctrl`+`Alt`+`Shift`+`R` out of the box.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Black or empty image | X11 tool on a Wayland session | Use `grim` or the desktop's tool |
| `Can't open display` | `$DISPLAY` unset (SSH, cron, systemd unit) | Export `DISPLAY=:0`, or use `xvfb-run` |
| Region select does nothing | `slurp`/`xdotool` missing | Install it |
| Blurry on a HiDPI screen | Tool captures logical, not physical pixels | Prefer `maim` (X11) or `grim` (Wayland) |
| Cursor missing | Most tools omit it by default | `scrot -p`, `maim --showcursor`, `grim -c` |
| Only one of several monitors | Default is the focused output | `grim -o <output>`, or `maim` which spans by default |
