# Geox

**Change the GPS location of a phone connected to your PC — and every app on it believes it.**
Plug an iPhone or Android into the computer with a USB cable, pick any spot on a map, and the phone reports that location at operating-system level: Find My, Snap Map, Google Maps, WhatsApp live location — everything.

You are in Vancouver. Everyone checking your location sees you at McMurdo Station, Antarctica.

![Geox](docs/screenshot.png)

## Features

- **Map picker** — search any place, click the map, drag the pin, or use presets (McMurdo and the South Pole included). Dark UI, no clutter.
- **Trip mode** — the location follows a *real itinerary*: car, bike, or walking routes on actual streets, at realistic speed, arriving and parking at the destination. Can parse a pasted **Google Maps link** (route links, pinned places, `@lat,lng` views).
- **Roam mode** — drifts between random points inside a radius at walking speed, so your pin looks alive instead of frozen.
- **Draw mode** — click waypoints on the map and travel between them at a speed you choose.
- **iPhone, iOS 15 through current** — uses Apple's own Instruments location-simulation channel (the mechanism Xcode uses), including the iOS 17+ tunnel. Nothing is installed on the phone.
- **Android** — official mock-location provider via a tiny companion app, driven over ADB.
- **Self-installing** — `run_geox.bat` needs no Python and no admin rights: first run downloads everything automatically. Zip the folder and share it as-is.
- **Self-healing sessions** — the fake fix is re-asserted every second, tunnel blips auto-reconnect, and a phone that drops off USB is waited for and resumed.

## Quick start

```
1. Double-click  run_geox.bat          (or run ./run_geox.sh)
2. The browser opens http://127.0.0.1:7876
3. Plug the phone in with USB, unlock it, accept the trust prompt
4. Refresh devices → select your phone
5. Pick a destination, choose a movement mode, press START SPOOFING
```

The terminal window is the live connection to the phone — keep it open.
The red **STOP** button (or closing the window) restores the real GPS instantly.

## Requirements

| Platform | Needed once |
|---|---|
| **iPhone** | Apple's USB drivers (the *Apple Devices* app from the Microsoft Store, or iTunes — Geox starts the service for you), *Trust this computer*, Developer Mode ON (Geox reveals the switch and walks you through it) |
| **Android** | USB debugging enabled; build the `Geox Bridge` app once from [`android-bridge/`](android-bridge) (about 10 minutes with Android Studio), then press *Setup bridge* and Geox installs and configures it by itself |

## How it works

On **iPhone**, Geox opens Apple's hidden developer channel for location
simulation over the USB pairing. The OS then reports the simulated fix as if
it were real GPS — which is why Find My and Snap Map show the fake place:
they ask the OS where the device is, and the OS answers with the spoof.

On **Android**, the Geox Bridge companion app receives coordinates over ADB
and feeds them into the OS as mock GPS fixes.

**Trip mode** queries OpenStreetMap routers (free, no API key) for real road
geometry, then travels the route at the route's real average speed.

The long version — architecture, setup walkthroughs, what can still give you
away, troubleshooting, FAQ — is in **[EXPLANATION.md](EXPLANATION.md)**.

## Documentation

- [EXPLANATION.md](EXPLANATION.md) — everything: setup, internals, realism tips, troubleshooting, FAQ
- [android-bridge/README.md](android-bridge/README.md) — building the Android companion app

## Disclaimer

Geox changes the location of **your own device**. It does not access, hack,
or monitor anyone else. Location spoofing is legal in most places, but how
you use it may not be — faking attendance, cheating delivery or ride apps, or
deceiving people whose safety depends on your location can be fraud, a
terms-of-service violation, or worse. Provided as-is, for personal and lawful
use. You are responsible for what you do with it.

## License

Geox is free to use, modify, and redistribute — **but not to sell**. It's
licensed under MIT with a Commons Clause addendum: anyone may use it, change
it, and share it for free, but nobody may sell the software itself or charge
for it. Donations and free distribution are fine. See [LICENSE](LICENSE).
