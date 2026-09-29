# Geox Bridge (Android companion app)

A tiny app that receives coordinates from the Geox desktop app over ADB and
injects them into Android as **mock GPS fixes**. It has no UI to operate:
everything is controlled from the PC.

Full instructions: see `../EXPLANATION.md` → "Android setup".

## Build (one time, ~10 minutes)

1. Install [Android Studio](https://developer.android.com/studio).
2. Open Android Studio → **Open** → select this `android-bridge` folder.
3. Let Gradle sync (it downloads the build tools automatically).
4. **Build → Build App Bundle(s) / APK(s) → Build APK(s).**
5. Click *locate* on the finished APK, and copy it to:

   ```
   android-bridge/bin/GeoxBridge.apk
   ```

From then on, Geox can install and configure it on any connected phone by
itself ("Setup bridge" button).

## Manual install (no Android Studio needed if you already have an APK)

```
adb install -r -t GeoxBridge.apk
adb shell pm grant com.geox.bridge android.permission.ACCESS_FINE_LOCATION
adb shell appops set com.geox.bridge android:mock_location allow
```
