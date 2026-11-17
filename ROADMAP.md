# Geox Development Roadmap

This document outlines the strategic milestones and planned enhancements for the Geox project.

## Current Release: v1.0.0 (Stable)

- Core cross-platform location spoofing engine (iOS Developer Mode tunnel & Android mock provider)
- Interactive web interface with OpenStreetMap map tiles, pin dropping, and real-time movement
- Phone Remote Web App (`/remote`) for untethered control from mobile browser
- Movement models: Fixed coordinates, Roam/Jitter simulation, and OSRM-based turn-by-turn road routes
- Offline tile caching and pre-packaged city coordinates for internet-free simulation
- Self-bootstrapping native Windows launchers (`Geox.exe`, `GeoxSetup.exe`)
- Automated port contention recovery and fallback handling

## Milestone: v1.1.0 - Seamless Wireless & Tunnel Reliability

- [ ] Automatic mDNS discovery for paired iOS devices without manual IP configuration
- [ ] Background heartbeat to keep Wi-Fi userspace tunnels alive during prolonged phone lock
- [ ] Direct QR code scanning in terminal / launcher to open the Remote Web App instantly
- [ ] Automatic recovery if the phone reconnects to a different Wi-Fi access point

## Milestone: v1.2.0 - Advanced Movement & GPX Tools

- [ ] Multi-point waypoint routing with custom pause durations at each stop
- [ ] Variable elevation and speed altitude profiles for realistic flight and mountain tracking
- [ ] Direct import and export of standard `.gpx` and `.kml` tracks in the Web UI
- [ ] Realistic pedestrian pacing with micro-stochastic gait variation

## Milestone: v2.0.0 - Fleet Management & Automation

- [ ] Multi-device concurrent control: simulate multiple phones independently from one dashboard
- [ ] REST API documentation (OpenAPI / Swagger) with webhook event notifications
- [ ] Headless daemon mode for automated CI/CD integration testing of mobile applications
- [ ] macOS and Linux native desktop application packaging (.dmg and .AppImage)
