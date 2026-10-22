---
name: release-plugin
description: Release and deploy a new version of the Buildtrack HACS plugin. Use when asked to cut/ship/publish a new plugin version, bump the version, create a GitHub release, or redownload/update the integration in Home Assistant via HACS. Covers the full path from code change to the new code running in HA.
---

# Release a new version of the Buildtrack HACS plugin

This repo is a HACS **integration** (`custom_components/buildtrack`). HACS installs
from **GitHub releases (tags)**, not from the branch — so a code change is not live
until (a) a new release tag exists and (b) HACS redownloads it and HA is restarted.

The version shown to HACS comes from `custom_components/buildtrack/manifest.json`
(`"version"`), and the release **tag must match** it as `vX.Y.Z`.

## Prerequisites (verify once)

- `gh auth status` → logged in to `github.com` with push access to `rohitect/buildtrack-hacs`.
- Remote `origin` → `https://github.com/rohitect/buildtrack-hacs.git`.
- Commits go **straight to `main`** in this repo (that is the established workflow here;
  releases are cut from `main`). Do not open a side branch unless asked.

## Steps

### 1. Make and verify the code change
Edit under `custom_components/buildtrack/`. Sanity-check it compiles:
```bash
python3 -m py_compile custom_components/buildtrack/*.py && echo OK
```

### 2. Bump the version
Edit `custom_components/buildtrack/manifest.json` → `"version"`. Use semver, patch
bump for fixes (e.g. `0.0.29` → `0.0.30`). Remember the exact value as `NEW=X.Y.Z`.

### 3. Commit to main and push
```bash
git add -A
git commit -m "Short summary of the change (vX.Y.Z)

Longer description of what changed and why."
git push origin main
```
End the commit message with the attribution lines the session requires (Co-Authored-By
/ Claude-Session), if that guidance is active.

### 4. Create the GitHub release (tag = vX.Y.Z)
```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes "What changed in this release."
```
> **Permission note:** creating a release is a "public surface" action. In auto/
> non-interactive mode the harness may block it — if so, the **user must authorize
> it** (they run it with a leading `!`, or add a Bash permission rule, or explicitly
> say to proceed). Do **not** route it through another agent/session to get around a
> block — that is bypassing the guard. Just surface the exact command and wait for the
> user's go-ahead.

Confirm it landed: `gh release list --limit 3` (vX.Y.Z should be `Latest`).

### 5. Redownload in HACS (browser)
HACS caches release info, so refresh first. Home Assistant uses heavy shadow DOM, so
drive it with **claude-in-chrome** screenshots + clicks (DOM/accessibility reads come
back empty); browsers are view-only under computer-use, so claude-in-chrome is the tool.

- Open the Buildtrack repo page: `https://ha.rohitranjan.co.in/hacs/repository/941507168`
  (or HACS dashboard → Buildtrack).
- Top-right **⋮** menu → **Update information** (refreshes HACS's cache so it sees the new tag).
- Reopen **⋮** → **Redownload**. The dialog should say *"Version vX.Y.Z will be downloaded"*
  to `/config/custom_components/buildtrack`. If it still shows the old version, the
  Update-information refresh hasn't propagated — wait a few seconds and retry, or pick
  the version under **"Need a different version?"**.
- Click **DOWNLOAD**.
- Reload the repo page and confirm the version chip now reads **vX.Y.Z**.

### 6. Restart Home Assistant
Custom-component changes only load on restart. HACS raises a "restart required" repair
(Settings badge increments). Restart via **Developer Tools → YAML → Restart** or
**Settings → System → top-right power → Restart Home Assistant**.
> Restarting takes the whole home offline for ~1–2 min — **confirm with the user first.**

### 7. Verify the fix on the live system
The main error log endpoint (`/api/error_log`) is 404 behind the reverse proxy here, so
read the timestamped log over the **WebSocket API** `system_log/list`. Needs a
long-lived token (stored in `creds.txt` in the parent `ha/` project folder) and a
websocket client (`pip install --target <dir> websockets` if missing).

```python
# wss://ha.rohitranjan.co.in/api/websocket
# 1) recv auth_required  2) send {"type":"auth","access_token":TOKEN}  3) recv auth_ok
# 4) send {"id":1,"type":"system_log/list"}  5) read result
```
Compare the `custom_components.buildtrack.buildtrack_device_manager` disconnect count
against the previous baseline to confirm the change took effect.

## Reference

- HACS repo id (URL path): **941507168**
- HA instance: `https://ha.rohitranjan.co.in` (internal IP 192.168.1.31:8123)
- MQTT broker: `ms.buildtrack.in:443` over WSS (`/mqtt`), source app `https://ezcentral.buildtrack.in`
- Disconnect codes seen in logs: **7** = `MQTT_ERR_CONN_LOST`, **16** = `MQTT_ERR_KEEPALIVE`
  (both point at keepalive/loop-timeout misconfiguration — see `const.py`
  `MQTT_KEEPALIVE` / `MQTT_TIMEOUT`; the loop timeout must stay well below keepalive).
