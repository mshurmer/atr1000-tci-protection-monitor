# ATR-1000 / TCI Protection Monitor

Windows desktop and simple internal-network web control application for monitoring an ATR-1000 HF antenna tuner and protecting a TCI-controlled radio.

## Current features

- Connect directly to the ATR-1000 over its WebSocket interface.
- User-selectable ATR-1000 IP address.
- Display tuner connection, TUNED/BYPASS state, SWR, forward power, LC/CL network, inductance and capacitance.
- Connect to a radio over TCI with user-selectable radio IP address and TCI port.
- Display TCI protocol/device information, TX/RX state, Tune state and drive value.
- TCI Tune ON/OFF toggle from both the desktop GUI and web page.
- User-selectable SWR emergency-stop threshold.
- If SWR exceeds the configured threshold, send TCI commands to force TX and Tune off.
- If the ATR-1000 reports BYPASS, reduce TCI drive to a user-selected safe value.
- Protection starts DISARMED and must be deliberately enabled.
- The application never automatically restores a higher drive setting after a protection action.
- Built-in simple HTTP web control page for use on a trusted closed internal network.
- Desktop GUI remains available while the web server is running.

## Safety notes

This software can send commands that affect an HF transmitter. Test it carefully at low power or into a dummy load before relying on it.

The web interface in this version has **no authentication and no HTTPS**. It is intended only for a trusted closed LAN/VPN. Do **not** port-forward the web server directly to the public internet.

The TCI `drive` value is a 0-100 drive setting; it should not be assumed to equal RF output power in watts.

## Requirements

- Windows 10/11 recommended
- Python 3.10+ when running from source
- `websocket-client`
- ATR-1000 reachable on the network, normally WebSocket port `60001`
- TCI-compatible radio/software reachable on the configured TCI port, normally `50001`

Install the Python dependency with:

```powershell
python -m pip install -r requirements.txt
```

Run from source with:

```powershell
python atr1000_tci_protection_monitor_v6_no_login.py
```

## Building the Windows EXE

The included `BUILD_EXE.bat` installs/updates PyInstaller and `websocket-client`, then creates a standalone Windows executable.

Put `BUILD_EXE.bat` and `atr1000_tci_protection_monitor_v6_no_login.py` in the same folder and double-click:

```text
BUILD_EXE.bat
```

The resulting executable will be:

```text
dist\ATR1000_Protection_Monitor.exe
```

## Automatic GitHub builds

Every push to `main` runs the **Build Windows EXE** workflow. The completed run contains a downloadable artifact named:

```text
ATR1000_Protection_Monitor_Windows
```

## Creating a GitHub Release

A version tag automatically triggers the **Release Windows EXE** workflow. GitHub builds the Windows program, creates a release, generates release notes, and attaches:

```text
ATR1000_Protection_Monitor.exe
```

For example, to publish version 1.0.0 from a local clone:

```powershell
git checkout main
git pull
git tag v1.0.0
git push origin v1.0.0
```

For the next release, use a new tag such as `v1.0.1` or `v1.1.0`.

## Default ports

| Interface | Default |
|---|---:|
| ATR-1000 WebSocket | 60001 |
| Radio TCI | 50001 |
| Local web control | 8080 |

## Protection behaviour

### ATR-1000 BYPASS

When automatic radio protection is armed and the tuner reports BYPASS, the application sends the configured safe TCI drive value. It does not automatically increase drive again when the tuner returns to TUNED.

### High SWR

When SWR exceeds the configured threshold, the application sends TX-off and Tune-off commands over TCI for both TCI receiver/transmitter indexes used by the current implementation.

### Manual Tune

The Tune control waits until the TCI server reports the current Tune state before enabling the toggle. This prevents the application from guessing whether Tune is already active.

## Web control

Start the web server from the desktop GUI. The application displays the local address, for example:

```text
http://192.168.1.100:8080/
```

The page provides live status plus tuner/radio connection controls, protection settings, ARM/DISARM, Tune toggle and emergency TX stop.

## Project status

This is an actively developed personal radio-station protection/control tool. Treat protection functionality as experimental until it has been thoroughly tested with your specific radio, tuner and station configuration.
