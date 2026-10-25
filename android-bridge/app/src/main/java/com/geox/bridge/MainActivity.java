package com.geox.bridge;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.AppOpsManager;
import android.content.Context;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.location.LocationManager;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Geox Bridge — receives spoofed coordinates over ADB broadcasts and feeds
 * them into Android's location stack as mock GPS fixes. Supports wireless,
 * unplugged operation, and standalone on-device location selection.
 */
public class MainActivity extends Activity {

    private LinearLayout root;
    private TextView statusView;
    private TextView coordsView;
    private Button setLocBtn;
    private Button resetBtn;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#0a0a0b"));
        root.setPadding(dp(22), dp(28), dp(22), dp(22));

        TextView logo = new TextView(this);
        logo.setText("GEOX BRIDGE");
        logo.setTextColor(Color.parseColor("#22c55e"));
        logo.setTextSize(22);
        logo.setTypeface(Typeface.DEFAULT_BOLD);
        logo.setLetterSpacing(0.15f);
        root.addView(logo);

        TextView sub = new TextView(this);
        sub.setText("Companion app for Geox GPS spoofer.\n"
                + "Supports wireless Wi-Fi and standalone on-phone control.");
        sub.setTextColor(Color.parseColor("#8b8b93"));
        sub.setTextSize(14);
        sub.setPadding(0, dp(10), 0, dp(18));
        root.addView(sub);

        statusView = makeCard();
        coordsView = makeCard();

        setLocBtn = new Button(this);
        setLocBtn.setText("Set Location On-Phone");
        setLocBtn.setBackgroundColor(Color.parseColor("#22c55e"));
        setLocBtn.setTextColor(Color.parseColor("#000000"));
        setLocBtn.setTextSize(14);
        setLocBtn.setTypeface(Typeface.DEFAULT_BOLD);
        LinearLayout.LayoutParams setLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        setLp.topMargin = dp(16);
        setLocBtn.setLayoutParams(setLp);
        setLocBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showLocationPickerDialog();
            }
        });
        root.addView(setLocBtn);

        resetBtn = new Button(this);
        resetBtn.setText("Reset Real GPS");
        resetBtn.setBackgroundColor(Color.parseColor("#ef4444"));
        resetBtn.setTextColor(Color.WHITE);
        resetBtn.setTextSize(14);
        resetBtn.setTypeface(Typeface.DEFAULT_BOLD);
        LinearLayout.LayoutParams btnLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        btnLp.topMargin = dp(10);
        resetBtn.setLayoutParams(btnLp);
        resetBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                MockService.stop(MainActivity.this);
                LocationManager lm = getSystemService(LocationManager.class);
                if (lm != null) {
                    LocationReceiver.remove(lm, LocationManager.GPS_PROVIDER);
                    LocationReceiver.remove(lm, LocationManager.NETWORK_PROVIDER);
                }
                SharedPreferences.Editor ed = getSharedPreferences("geox", Context.MODE_PRIVATE).edit();
                ed.clear();
                ed.apply();
                refresh();
                Toast.makeText(MainActivity.this, "Real GPS restored", Toast.LENGTH_SHORT).show();
            }
        });
        root.addView(resetBtn);

        TextView steps = new TextView(this);
        steps.setText("Standalone & Wireless Control\n"
                + "1. Tap 'Set Location On-Phone' to pick coordinates directly on-device without a PC.\n"
                + "2. Or open the Geox Mobile Web App (http://<pc-ip>:7876/remote) in your browser.\n"
                + "3. Tap 'Reset Real GPS' anytime to restore your real hardware location.");
        steps.setTextColor(Color.parseColor("#c8c8cc"));
        steps.setTextSize(13);
        steps.setLineSpacing(dp(4), 1f);
        steps.setPadding(0, dp(20), 0, 0);
        root.addView(steps);

        setContentView(root);
    }

    private void showLocationPickerDialog() {
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle("Set Location On-Phone");

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(20), dp(10), dp(20), dp(10));

        final EditText latInput = new EditText(this);
        latInput.setHint("Latitude (e.g. 48.8566)");
        layout.addView(latInput);

        final EditText lngInput = new EditText(this);
        lngInput.setHint("Longitude (e.g. 2.3522)");
        layout.addView(lngInput);

        TextView presetsLabel = new TextView(this);
        presetsLabel.setText("Quick Presets:");
        presetsLabel.setPadding(0, dp(12), 0, dp(6));
        presetsLabel.setTextSize(12);
        layout.addView(presetsLabel);

        LinearLayout presetRow = new LinearLayout(this);
        presetRow.setOrientation(LinearLayout.HORIZONTAL);

        String[] presetNames = {"Paris", "Tokyo", "New York", "McMurdo"};
        final double[][] presetCoords = {
                {48.8566, 2.3522},
                {35.6762, 139.6503},
                {40.7128, -74.0060},
                {-77.8419, 166.6863}
        };

        for (int i = 0; i < presetNames.length; i++) {
            final int idx = i;
            Button pBtn = new Button(this);
            pBtn.setText(presetNames[i]);
            pBtn.setTextSize(11);
            pBtn.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    latInput.setText(String.valueOf(presetCoords[idx][0]));
                    lngInput.setText(String.valueOf(presetCoords[idx][1]));
                }
            });
            LinearLayout.LayoutParams pLp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.0f);
            pLp.rightMargin = dp(4);
            presetRow.addView(pBtn, pLp);
        }
        layout.addView(presetRow);

        builder.setView(layout);

        builder.setPositiveButton("Apply Fix", new DialogInterface.OnClickListener() {
            @Override
            public void onClick(DialogInterface dialog, int which) {
                try {
                    double lat = Double.parseDouble(latInput.getText().toString().trim());
                    double lng = Double.parseDouble(lngInput.getText().toString().trim());
                    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
                        Toast.makeText(MainActivity.this, "Coordinates out of range", Toast.LENGTH_SHORT).show();
                        return;
                    }
                    LocationManager lm = getSystemService(LocationManager.class);
                    if (lm != null) {
                        LocationReceiver.mock(MainActivity.this, lm, LocationManager.GPS_PROVIDER, lat, lng, 10.0f, true);
                        MockService.start(MainActivity.this, lat, lng, 10.0f);
                    }
                    SharedPreferences.Editor ed = getSharedPreferences("geox", Context.MODE_PRIVATE).edit();
                    ed.putLong("lat", Double.doubleToRawLongBits(lat));
                    ed.putLong("lng", Double.doubleToRawLongBits(lng));
                    ed.putBoolean("persist", true);
                    ed.putLong("t", System.currentTimeMillis());
                    ed.apply();
                    refresh();
                    Toast.makeText(MainActivity.this, "Location set to: " + lat + ", " + lng, Toast.LENGTH_SHORT).show();
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this, "Invalid coordinates", Toast.LENGTH_SHORT).show();
                }
            }
        });

        builder.setNegativeButton("Cancel", null);
        builder.show();
    }

    private TextView makeCard() {
        TextView tv = new TextView(this);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor("#141416"));
        bg.setCornerRadius(dp(16));
        bg.setStroke(dp(1), Color.parseColor("#26262b"));
        tv.setBackground(bg);
        tv.setTextColor(Color.parseColor("#e8e8ea"));
        tv.setTextSize(14);
        tv.setPadding(dp(16), dp(14), dp(16), dp(14));
        tv.setLineSpacing(dp(3), 1f);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(10);
        root.addView(tv, lp);
        return tv;
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }

    private void refresh() {
        boolean allowed = mockLocationAllowed();
        statusView.setText(allowed
                ? "Mock-location permission: GRANTED\nThis app is allowed to inject GPS fixes."
                : "Mock-location permission: MISSING\nClick 'Setup bridge' in Geox desktop app.");
        statusView.setTextColor(Color.parseColor(allowed ? "#22c55e" : "#f59e0b"));

        SharedPreferences prefs = getSharedPreferences("geox", Context.MODE_PRIVATE);
        double lat = Double.longBitsToDouble(prefs.getLong("lat", 0));
        double lng = Double.longBitsToDouble(prefs.getLong("lng", 0));
        boolean persist = prefs.getBoolean("persist", false);
        long t = prefs.getLong("t", 0);
        if (t == 0) {
            coordsView.setText("Last received fix: none yet.\nStart spoofing from Geox or tap 'Set Location On-Phone'.");
            coordsView.setTextColor(Color.parseColor("#8b8b93"));
            resetBtn.setVisibility(View.GONE);
        } else {
            String modeStr = persist ? " (Persisting unplugged)" : "";
            coordsView.setText(String.format("Active spoof fix%s:\n%.6f, %.6f\nUpdated: %s",
                    modeStr, lat, lng,
                    android.text.format.DateFormat.getTimeFormat(this).format(new java.util.Date(t))));
            coordsView.setTextColor(Color.parseColor("#22c55e"));
            resetBtn.setVisibility(View.VISIBLE);
        }
    }

    private boolean mockLocationAllowed() {
        AppOpsManager ops = (AppOpsManager) getSystemService(Context.APP_OPS_SERVICE);
        if (ops == null) return false;
        try {
            int mode = ops.checkOpNoThrow("android:mock_location",
                    android.os.Process.myUid(), getPackageName());
            return mode == AppOpsManager.MODE_ALLOWED;
        } catch (Exception e) {
            return false;
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
