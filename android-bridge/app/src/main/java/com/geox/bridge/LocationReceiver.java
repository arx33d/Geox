package com.geox.bridge;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.location.Criteria;
import android.location.Location;
import android.location.LocationManager;
import android.os.SystemClock;

/**
 * Receives coordinates broadcast by the Geox desktop app over ADB and
 * injects them as mock GPS/network fixes. Requires the mock-location
 * appop (granted by the desktop app via `adb shell appops set … allow`).
 */
public class LocationReceiver extends BroadcastReceiver {

    public static final String ACTION_SET = "com.geox.bridge.SET_LOCATION";
    public static final String ACTION_CLEAR = "com.geox.bridge.CLEAR";

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if (action == null) return;
        LocationManager lm = context.getSystemService(LocationManager.class);
        if (lm == null) return;

        if (ACTION_CLEAR.equals(action)) {
            remove(lm, LocationManager.GPS_PROVIDER);
            remove(lm, LocationManager.NETWORK_PROVIDER);
            return;
        }

        if (!ACTION_SET.equals(action)) return;

        double lat = intent.getDoubleExtra("lat", Double.NaN);
        double lng = intent.getDoubleExtra("lng", Double.NaN);
        if (Double.isNaN(lat) || Double.isNaN(lng)) return;
        double alt = intent.getDoubleExtra("alt", 10.0);
        double acc = intent.getDoubleExtra("acc", 5.0);
        double speed = intent.getDoubleExtra("speed", -1.0);

        mock(lm, LocationManager.GPS_PROVIDER, lat, lng, alt, acc, speed);
        try {
            mock(lm, LocationManager.NETWORK_PROVIDER, lat, lng, alt, Math.max(acc, 20.0), speed);
        } catch (Exception ignored) {
            // some builds refuse to mock the network provider — GPS is what matters
        }

        SharedPreferences.Editor prefs =
                context.getSharedPreferences("geox", Context.MODE_PRIVATE).edit();
        prefs.putLong("lat", Double.doubleToRawLongBits(lat));
        prefs.putLong("lng", Double.doubleToRawLongBits(lng));
        prefs.putLong("t", System.currentTimeMillis());
        prefs.apply();
    }

    private static void mock(LocationManager lm, String provider, double lat, double lng,
                             double alt, double acc, double speed) {
        try {
            try {
                lm.addTestProvider(provider, false, false, false, false,
                        true, true, true,
                        Criteria.POWER_LOW, Criteria.ACCURACY_FINE);
            } catch (IllegalArgumentException | SecurityException e) {
                // already added, or permission missing (the SecurityException is
                // reported back through the appop check in the UI)
            }
            lm.setTestProviderEnabled(provider, true);

            Location loc = new Location(provider);
            loc.setLatitude(lat);
            loc.setLongitude(lng);
            loc.setAltitude(alt);
            loc.setAccuracy((float) acc);
            loc.setBearing(0f);
            if (speed >= 0) loc.setSpeed((float) speed);
            loc.setTime(System.currentTimeMillis());
            loc.setElapsedRealtimeNanos(SystemClock.elapsedRealtimeNanos());
            loc.setExtras(null);
            lm.setTestProviderLocation(provider, loc);
        } catch (Exception ignored) {
            // never crash the receiver — the desktop app re-broadcasts every 2s
        }
    }

    private static void remove(LocationManager lm, String provider) {
        try {
            lm.setTestProviderEnabled(provider, false);
            lm.removeTestProvider(provider);
        } catch (Exception ignored) {
        }
    }
}
