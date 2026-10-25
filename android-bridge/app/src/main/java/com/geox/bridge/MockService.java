package com.geox.bridge;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.location.LocationManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/**
 * Background mock location service for cable-free / unplugged operation.
 * Continues injecting mock coordinates into the Android location stack
 * even when the USB cable is disconnected or the computer is turned off.
 */
public class MockService extends Service {

    public static final String ACTION_START = "com.geox.bridge.MOCK_START";
    public static final String ACTION_STOP = "com.geox.bridge.MOCK_STOP";
    private static final String CHANNEL_ID = "geox_mock_channel";
    private static final int NOTIF_ID = 7876;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean isRunning = false;
    private double lat = 0.0;
    private double lng = 0.0;
    private double alt = 10.0;
    private double acc = 5.0;
    private double speed = -1.0;

    private final Runnable tickRunnable = new Runnable() {
        @Override
        public void run() {
            if (!isRunning) return;
            LocationManager lm = getSystemService(LocationManager.class);
            if (lm != null) {
                LocationReceiver.mock(lm, LocationManager.GPS_PROVIDER, lat, lng, alt, acc, speed);
                try {
                    LocationReceiver.mock(lm, LocationManager.NETWORK_PROVIDER, lat, lng, alt, Math.max(acc, 20.0), speed);
                } catch (Exception ignored) {
                }
            }
            handler.postDelayed(this, 1500);
        }
    };

    public static void start(Context context, double lat, double lng, double alt, double acc, double speed) {
        Intent intent = new Intent(context, MockService.class);
        intent.setAction(ACTION_START);
        intent.putExtra("lat", lat);
        intent.putExtra("lng", lng);
        intent.putExtra("alt", alt);
        intent.putExtra("acc", acc);
        intent.putExtra("speed", speed);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
    }

    public static void stop(Context context) {
        Intent intent = new Intent(context, MockService.class);
        intent.setAction(ACTION_STOP);
        context.stopService(intent);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || ACTION_STOP.equals(intent.getAction())) {
            stopSelf();
            return START_NOT_STICKY;
        }

        lat = intent.getDoubleExtra("lat", lat);
        lng = intent.getDoubleExtra("lng", lng);
        alt = intent.getDoubleExtra("alt", alt);
        acc = intent.getDoubleExtra("acc", acc);
        speed = intent.getDoubleExtra("speed", speed);

        Notification notification = buildNotification(lat, lng);
        startForeground(NOTIF_ID, notification);

        if (!isRunning) {
            isRunning = true;
            handler.post(tickRunnable);
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        isRunning = false;
        handler.removeCallbacks(tickRunnable);
        LocationManager lm = getSystemService(LocationManager.class);
        if (lm != null) {
            LocationReceiver.remove(lm, LocationManager.GPS_PROVIDER);
            LocationReceiver.remove(lm, LocationManager.NETWORK_PROVIDER);
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    "Geox Mock Location",
                    NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Active mock location provider (cable unplugged)");
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification(double latitude, double longitude) {
        Intent notifIntent = new Intent(this, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                this, 0, notifIntent,
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0
        );

        String text = String.format("Spoofed fix active: %.5f, %.5f (unplug safe)", latitude, longitude);
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }
        return builder.setContentTitle("Geox Bridge - Wireless Spoofing")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .setContentIntent(pendingIntent)
                .setOngoing(true)
                .build();
    }
}
