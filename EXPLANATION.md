# GEOX: Everything Explained

Geox is a desktop app that changes the GPS location of a phone while it is connected to your laptop. While spoofing is active, the *phone itself* reports fake coordinates at operating-system level, so **Find My, Snap Map, Google Maps, Weather, WhatsApp live location, and every other app** see the fake place. Your example works exactly as described: you sit in **Vancouver**, and everyone checking your location sees you at **McMurdo Station, Antarctica**.

Read the "Responsible use" section at the bottom before using this. It runs on your own phone and your own PC; that's the only supported use.

## 1. Quick start

```
1. Double-click  run_geox.bat
2. Your browser opens  http://127.0.0.1:7876
3. Plug the phone in with USB, unlock it, accept the trust prompt
4. Click "Refresh devices"  →  select your phone
5. Pick a spot on the map (or search "McMurdo Station", or use a preset)
6. Choose a movement mode  →  press  START SPOOFING
```

### CLI Mode (direct terminal usage)
You can also run Geox directly from your command line without opening a browser:

```bat
# Spoof location with a Google Maps URL (Stay mode):
geox --location "https://www.google.com/maps/place/Toronto,+ON/@43.7164673,-79.6563003,..." --movement stay

# Spoof location with Roam mode (radius 120m, speed 4.5 km/h):
geox --location "Toronto, ON" --movement roam 120 4.5

# Spoof using quick presets:
geox --preset mcmurdo --movement roam 200 5

# Plan and drive a realistic trip:
geox --from "Vancouver" --to "Seattle" --profile car --speed-factor 1.5

# Manage devices and sessions:
geox --devices          # List connected phones and status
geox --stop             # Stop spoofing & restore real GPS
geox --status           # Check active spoofing sessions
```

`run_geox.bat` and `geox.bat` need nothing pre-installed: if Python is missing it downloads a private copy (about 11 MB) plus the app's dependencies automatically. To share Geox with someone, zip this folder and send it; the first run sets everything up (internet required).

Keep the terminal window open: it *is* the connection to the phone. Pressing **Ctrl+C** (or the red STOP button) restores the real GPS immediately.

## 2. One-time setup

### iPhone

| Requirement | How |
|---|---|
| **Apple USB drivers** | Geox starts them automatically: it launches the "Apple Devices" app (or install iTunes from apple.com). If the pill at the top says "Apple drivers missing", install the **Apple Devices** app from the Microsoft Store. |
| **Trust this computer** | Plug in, unlock the phone, tap *Trust*, enter passcode. |
| **Developer Mode ON** | Press START once; Geox reveals the switch, then either enables it for you or tells you exactly where it is: **Settings → Privacy & Security → Developer Mode → ON** (passcode + one reboot). The Geox button in the error card does this. |

Nothing is ever installed on the iPhone. The mechanism is Apple's own built-in developer feature. Works on iOS 15 and newer; iOS 17+ (including the latest releases) is handled through an automatic tunnel session.

### Android

| Requirement | How |
|---|---|
| **ADB** | Click **"Install ADB"** in the app: it downloads Google's official platform-tools by itself. |
| **USB debugging** | Settings → About phone → tap *Build number* 7× → Settings → Developer options → USB debugging ON. |
| **Geox Bridge app** (one build) | Build once from the `android-bridge/` folder (see its README, about 10 minutes with Android Studio), copy the APK to `android-bridge/bin/GeoxBridge.apk`, then click **"Setup bridge"**: Geox installs it and grants the mock-location permission automatically. |

## 3. How it works

```
┌─────────────── your PC ───────────────┐          ┌──── your phone ────┐
│  Browser UI  →  Geox server  →  engine │          │                    │
│   (map/pick)     (Flask, :7876)  │     │          │                    │
│                                   │     │   USB    │                    │
│   iPhone: pymobiledevice3 ────────●─────●────────► │ Apple's DVT        │
│   (Instruments location simulation)   │          │ location service   │
│                                       │          │  → OS reports fake │
│   Android: ADB broadcast every 2 s ───●─────────► │ Geox Bridge app    │
│                                       │          │  → mock GPS fix    │
└───────────────────────────────────────┘          └────────────────────┘
```

**iPhone.** Apple ships a hidden developer feature: the *Instruments location-simulation channel*, the exact mechanism Xcode uses when you tick "Simulate Location". Geox opens that channel over the USB pairing and pushes coordinates. The phone's OS then **reports the fake fix as if it were real GPS**. That's why Find My and Snap Map show the fake place: they ask the OS "where is this device", and the OS answers with the simulated fix. The session must stay open, so the phone stays connected while spoofing.

On modern iOS the developer channel runs through an encrypted tunnel that Geox establishes for you; the first connection also mounts Apple's developer image automatically. You just press START, and the log shows each step.

**Android.** Android has an official *mock location provider* API. Geox installs the Geox Bridge companion app, grants it the mock-location capability over ADB, and broadcasts new coordinates to it every 2 seconds. The bridge feeds them into the OS as GPS fixes.

**Movement.** A frozen pin is suspicious. Geox can move:

| Mode | What the phone reports |
|---|---|
| **Stay** | Parked at the chosen point. |
| **Roam** | Drifts between random points inside a radius (e.g. 120 m) at walking speed, so it looks like you're actually hanging around somewhere. |
| **Draw** | Click waypoints on the map; the location travels between them at a speed you choose. |
| **Trip** | A real itinerary; see next section. |

## 4. Trip mode: following a real itinerary

This is what makes the spoof believable: your location **follows actual streets** to a destination instead of teleporting.

1. Switch to **Trip**.
2. Type a destination (or paste a **Google Maps link**; Geox reads route links, pinned places, and `@lat,lng` map views).
3. Pick a profile: **Car, Bike, Walk, Bus/Metro**.
4. Set a **speed factor** (1 = real road speeds). Speeds already follow the real road, so the location speeds up on highways and slows down in city streets; a factor of 2 travels twice as fast, 0.5 half as fast.
5. The start point is **the map marker**; put it where the phone really is.
6. Press **Plan**. Geox queries OpenStreetMap routers (free, no API key) and draws the real road route, segment by segment with each segment's real travel time.
7. Press **START SPOOFING**. The phone travels the itinerary at those per-road speeds, then **stays parked at the destination** when it arrives.

Bus/Metro follows the road network at a transit-like average speed (about 22 km/h door to door): free routers don't publish live timetables, so this is an approximation of taking the bus. For the exact shape of a metro line, use Draw mode and trace it.

Trips work across town or across countries. Vancouver to Seattle is a real 230 km drive that the location will follow at real driving speed.

## 5. Using the app

* **1 · Device**: every connected phone with status badges (paired, developer mode, bridge ready). Click one to select it.
* **2 · Destination**: search any place, click the map, drag the green marker, type coordinates, or use a preset (McMurdo and the South Pole are there).
* **3 · Movement**: Stay / Roam / Draw / Trip.
* **4 · Control**: START SPOOFING turns it on; the card shows a live "now at" position. STOP restores the real GPS instantly.
* **Log**: every engine event, in plain language.

While spoofing, the phone's own Maps app shows the fake position too. That's your confirmation before anyone checks Find My or Snap Map.

## 6. Being realistic (and what can still give you away)

Geox spoofs **GPS**. It cannot change everything a service might look at:

* **Your IP address** still says Vancouver. A VPN at the same location as your spoof closes that hole; a mismatch (GPS says Antarctica, IP says Vancouver) is the classic giveaway.
* **Wi-Fi / Bluetooth** around you can fingerprint your real area on some apps.
* **History**: Snap Map and Google Timeline remember past points. Teleporting 15,000 km in one minute looks impossible; use Trip mode, or make jumps plausible.
* **Find My** shows the spoofed location, but Apple keeps other telemetry (e.g. "significant locations") that may still reflect real patterns.
* Some apps (banking, some games) use extra anti-spoof checks.

Tips: use Roam/Trip rather than a frozen pin, keep jumps physically possible, and stop the spoof in the same "story" you started it with.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| "Apple drivers missing" pill | Install the **Apple Devices** app (Microsoft Store) or iTunes; Geox starts the service by itself |
| iPhone not in device list | Use a *data* cable, unlock phone, tap **Trust**, press Refresh |
| "Developer Mode is OFF" error card | Press the **Enable Developer Mode** button in the card (passcode phones: flip the switch in Settings → Privacy & Security → Developer Mode), wait for the reboot, START again |
| iOS 17+ first connect is slow | Normal: a tunnel and the developer image are being set up (first time only) |
| Spoof stops when unplugged | Expected: the session lives on the cable. Keep connected. |
| "The iPhone disappeared from USB" | The session waits up to 2 minutes for the phone to come back, then stops. Replug the cable (a different USB port helps), press START. |
| Location briefly flickers back to real | Geox re-asserts the fake fix every second and reconnects through tunnel blips automatically. Persistent flicker usually means a loose cable or a weak USB port; also keep USB selective suspend disabled (power plan → USB settings) |
| Android "needs bridge setup" | Build the APK (§2), then press **Setup bridge** |
| "ADB missing" pill | Press **Install ADB** (auto-downloads Google's tools) |
| Android "unauthorized" | Unlock the phone, allow the USB-debugging prompt |
| Map tiles blank | Tiles load from the internet; everything else works offline |
| Something else | Read the Log panel; messages are written in plain language |

## 8. Responsible use & legal notes

* This tool changes the location of **your own device**. It does not hack, access, or monitor anyone else.
* Laws differ by country; location spoofing itself is legal in most places, but *using it* can be fraud or a terms-of-service violation depending on context (faking attendance, cheating delivery/ride apps, games, evading court-ordered or safety-related location sharing).
* Don't use it to deceive people in ways that put anyone at risk.
* Geox is provided as-is, for personal, lawful use. You are responsible for how you use it.

## 9. File map

```
Geox/
├─ run_geox.bat / run_geox.sh     launch the app (self-installing)
├─ EXPLANATION.md                 this file
├─ README.md                      short pointer
├─ requirements.txt
├─ geox/                          the engine (Python)
│  ├─ server.py                   Flask server + JSON API (port 7876)
│  ├─ engine.py                   session manager, device scan, logs
│  ├─ ios_backend.py              iPhone: DVT simulation + tunnel session,
│  │                              Apple service auto-start, dev-mode helper
│  ├─ android_backend.py          Android: ADB + bridge broadcasts, ADB auto-install
│  ├─ router.py                   real itineraries (OSRM) + Google Maps link parsing
│  └─ motion.py                   movement maths (stay / roam / route)
├─ web/                           the UI (index.html, app.js, style.css)
├─ android-bridge/                companion APK source (build once)
├─ tools/bootstrap_python.ps1     downloads a private Python when none exists
├─ runtime/                       private Python (created by the bootstrap)
├─ tools/platform-tools/          ADB lands here after auto-install
└─ var/gpx/                       generated movement tracks (iOS tunnel mode)
```

## 10. FAQ

**Does Find My show the fake location?** Yes. Find My reads the OS location services, which report the simulated fix while a session is open.

**Does the phone need to stay plugged in?** Yes, while spoofing. The simulation is a live session over USB.

**Does anything get installed on my iPhone?** No. Nothing is installed; it uses Apple's built-in developer mechanism.

**Is it safe for the phone?** It's the same mechanism Xcode uses every day. Press STOP (or close Geox) and the phone is back to its real GPS.

**How do I fully stop spoofing?** The red STOP button, or just close the Geox window. On Android the bridge is also told to clear its mock provider.
