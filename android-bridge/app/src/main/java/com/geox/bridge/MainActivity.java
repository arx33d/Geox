package com.geox.bridge;

import android.app.Activity;
import android.app.AppOpsManager;
import android.content.Context;
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
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Geox Bridge — receives spoofed coordinates over ADB broadcasts and feeds
 * them into Android's location stack as mock GPS fixes. Supports wireless
 * and unplugged operation.
 */
public class MainActivity extends Activity {

    private LinearLayout root;
    private TextView statusView;
    private TextView coordsView;
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
                + "Supports wireless Wi-Fi and unplugged operation.");
        sub.setTextColor(Color.parseColor("#8b8b93"));
        sub.setTextSize(14);
        sub.setPadding(0, dp(10), 0, dp(18));
        root.addView(sub);

        statusView = makeCard();
        coordsView = makeCard();

        resetBtn = new Button(this);
        resetBtn.setText("Reset Real GPS");
        resetBtn.setBackgroundColor(Color.parseColor("#ef4444"));
        resetBtn.setTextColor(Color.WHITE);
        resetBtn.setTextSize(14);
        resetBtn.setTypeface(Typeface.DEFAULT_BOLD);
        LinearLayout.LayoutParams btnLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        btnLp.topMargin = dp(16);
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
            }
        });
        root.addView(resetBtn);

        TextView steps = new TextView(this);
        steps.setText("Setup & Wireless Mode\n"
                + "1. Enable Developer Options & USB debugging\n"
                + "2. Click 'Setup bridge' on PC to grant permission\n"
                + "3. Switch to Wi-Fi in Geox to unplug the cable\n"
                + "4. Use 'Reset Real GPS' anytime to restore real location.");
        steps.setTextColor(Color.parseColor("#c8c8cc"));
        steps.setTextSize(13);
        steps.setLineSpacing(dp(4), 1f);
        steps.setPadding(0, dp(20), 0, 0);
        root.addView(steps);

        setContentView(root);
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
            coordsView.setText("Last received fix: none yet.\nStart spoofing from Geox.");
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
