# Hosting the Supply Chain Portal on the office network

This guide makes the portal available to other computers on the office network (LAN).
It does **not** put the portal on the internet.

| Item | Value on this PC |
|---|---|
| Host PC name | `JayaPrakash` |
| Host PC address (Wi-Fi) | `192.168.0.239` |
| Office Wi-Fi | `Vishwa Second Floor 5G 2` |
| Portal link for colleagues | **http://192.168.0.239/** (or **http://jayaprakash/**) |
| Portal link on this PC | http://localhost/ |
| Project folder | `C:\Users\jayap\SupplyChainPortal` |

> The address `192.168.0.239` is given out by the office router and can change. Step 2 prevents that.

---

## Before you start

You need:

- This PC switched on and connected to the office Wi-Fi.
- **Docker Desktop** installed and running (whale icon in the taskbar tray).
- A Windows account that can **Run as administrator** (needed once, in Step 5).
- Other computers on the **same** office network (same Wi-Fi or wired LAN, not guest Wi-Fi).

All commands below are typed in **PowerShell**. Open it with **Start → type `PowerShell` → Enter**.
Unless a step says *as administrator*, a normal PowerShell window is fine.

---

## Step 1 — Find this PC's network address

1. Open PowerShell and run:
   ```powershell
   ipconfig
   ```
2. Under **Wireless LAN adapter Wi-Fi** (or **Ethernet adapter Ethernet** if you use a cable), note the **IPv4 Address**.
   Today it is `192.168.0.239`.
3. Ignore addresses under *vEthernet (WSL)*, *VPN* or *Bluetooth* — those are not the office network.

If your address is different from `192.168.0.239`, use your address everywhere this guide says `192.168.0.239`.

## Step 2 — Keep the address from changing (router)

Ask whoever manages the office router (IT / network admin) to create a **DHCP reservation** for this PC:

- **Device:** `JayaPrakash`
- **IP address:** `192.168.0.239`
- **MAC address:** run the command below and send them the *Physical Address* of the Wi-Fi adapter:
  ```powershell
  Get-NetAdapter -Name "Wi-Fi" | Select-Object Name, MacAddress
  ```

Without this, the router may give the PC a new address after a restart and the portal link will stop working (see *If the PC's address changes* below).

## Step 3 — Check the portal's network settings

The settings are in the file `C:\Users\jayap\SupplyChainPortal\.env`. Open it in Notepad or VS Code.

Make sure these lines look like this (they are already set on this PC):

```ini
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.0.239,jayaprakash
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost,http://127.0.0.1,http://192.168.0.239,http://jayaprakash
WEB_BIND=0.0.0.0
WEB_PORT=80
```

What they mean:

| Setting | Meaning |
|---|---|
| `WEB_BIND=0.0.0.0` | Accept connections from the network. `127.0.0.1` would mean *this PC only*. |
| `WEB_PORT=80` | Standard web port, so the link needs no `:8000` at the end. |
| `DJANGO_ALLOWED_HOSTS` | Every address people type in the browser, without `http://`. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | The same addresses **with** `http://`. Needed for sign-in and forms to work. |
| `DJANGO_DEBUG=0` | Production mode: no technical error pages shown to users. |

Do **not** share this file — it also contains the database password and the secret key.

## Step 4 — Start (or restart) the portal

1. In PowerShell:
   ```powershell
   cd C:\Users\jayap\SupplyChainPortal
   docker compose up -d
   ```
2. Check it is running:
   ```powershell
   docker compose ps
   ```
   The `web` line should show **healthy** and `0.0.0.0:80->8000/tcp`.
3. On **this PC**, open http://192.168.0.239/ — the sign-in page should appear.

If `docker compose up -d` says *ports are not available … port 80*, wait 10 seconds and run it again (the old container was still releasing the port).

## Step 5 — Allow other computers in (once, as administrator)

Windows currently treats the office Wi-Fi as a **Public** network, which blocks incoming connections. Change it to **Private** and open port 80.

### Option A — Use the prepared script (recommended)

1. Click **Start**, type `PowerShell`, **right-click Windows PowerShell → Run as administrator**, click **Yes**.
2. Run:
   ```powershell
   cd C:\Users\jayap\SupplyChainPortal
   powershell -ExecutionPolicy Bypass -File .\setup-lan-access.ps1
   ```
3. You should see:
   ```
   Network 'Vishwa Second Floor 5G 2' on Wi-Fi set to Private.
   Firewall rule 'Supply Chain Portal (HTTP 80)' added.
   Done. From another computer on this network open:  http://192.168.0.239/
   ```

### Option B — Do it by hand in Windows Settings

1. **Settings → Network & internet → Wi-Fi → Vishwa Second Floor 5G 2 (properties)** → set **Network profile type** to **Private network**.
2. **Start → type `Windows Defender Firewall with Advanced Security` → open it**.
3. Click **Inbound Rules → New Rule…**
4. **Port** → Next → **TCP**, *Specific local ports*: `80` → Next.
5. **Allow the connection** → Next.
6. Tick **Domain** and **Private** only (leave **Public** unticked) → Next.
7. Name: `Supply Chain Portal (HTTP 80)` → Finish.

## Step 6 — Test from another computer

1. On a colleague's computer connected to the same office network, open a browser.
2. Go to **http://192.168.0.239/**
3. The VISHWA sign-in page should appear. Sign in with an account created on the **Users** page.

If `http://jayaprakash/` does not work but the IP address does, that is normal on some networks — use the IP address.

## Step 7 — Keep the portal available all day

The portal only works while this PC is on. Do these once:

1. **Stop the PC sleeping while plugged in** (PowerShell, normal window):
   ```powershell
   powercfg /change standby-timeout-ac 0
   ```
   Or: **Settings → System → Power & battery → Screen and sleep → When plugged in, put my device to sleep after: Never**.
2. **Start Docker Desktop automatically:** Docker Desktop → **Settings (gear) → General → tick "Start Docker Desktop when you sign in to your computer"** → Apply.
   The portal containers restart by themselves once Docker is running.
3. After a Windows restart, sign in to Windows once so Docker Desktop starts.

## Step 8 — Create accounts for colleagues

1. Sign in as an administrator and open **Users** in the top menu.
2. Enter a username and password, choose **Access**:
   - **Read only** — can search and view suppliers and subcontractors.
   - **Administrator** — can also add, edit and upload data, and manage users.
3. Give each colleague their own account; do not share the administrator login.

---

## If the PC's address changes

If `ipconfig` shows a new address (for example `192.168.0.150`):

1. Edit `.env` and replace `192.168.0.239` with the new address in **both** `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`.
2. Apply it:
   ```powershell
   cd C:\Users\jayap\SupplyChainPortal
   docker compose up -d
   ```
3. Tell colleagues the new link, and ask IT for the DHCP reservation in Step 2 so it does not happen again.

## Troubleshooting

| What you see | Likely cause | Fix |
|---|---|---|
| Works on this PC, not on others | Network is Public or firewall rule missing | Run Step 5 as administrator. Check with `Get-NetConnectionProfile` (should say **Private**). |
| *This site can't be reached* everywhere | Portal or Docker not running | Start Docker Desktop, then `docker compose up -d`, then `docker compose ps`. |
| **Bad Request (400)** | The address typed is not in `DJANGO_ALLOWED_HOSTS` | Add it (Step 3) and run `docker compose up -d`. |
| **Forbidden (403) CSRF** when signing in | Address missing from `DJANGO_CSRF_TRUSTED_ORIGINS` | Add it with `http://` (Step 3) and run `docker compose up -d`. |
| `localhost:8000` stopped working | Portal now uses port 80 | Use http://localhost/ |
| Colleague on guest Wi-Fi or mobile data can't connect | Different network | They must be on the office network. |
| Worked yesterday, not today | PC slept, restarted, or got a new IP | See Step 7 and *If the PC's address changes*. |

Useful checks (PowerShell):

```powershell
docker compose ps                                   # is the portal running and healthy?
docker compose logs web --tail 50                   # recent portal log messages
Get-NetConnectionProfile                            # network should be Private
Get-NetFirewallRule -DisplayName 'Supply Chain Portal (HTTP 80)'   # rule exists?
Invoke-WebRequest http://192.168.0.239/health/ -UseBasicParsing   # should return {"status": "ok"}
```

## Switching network access off again

To make the portal reachable from this PC only:

1. In `.env` set:
   ```ini
   WEB_BIND=127.0.0.1
   WEB_PORT=8000
   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
   DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
   ```
2. Run `docker compose up -d`. The portal is then at http://localhost:8000/.
3. Optionally remove the firewall rule (PowerShell **as administrator**):
   ```powershell
   Remove-NetFirewallRule -DisplayName 'Supply Chain Portal (HTTP 80)'
   ```

## Security notes

- The portal is reachable from the **office network only**; no router port-forwarding is set up, so it is **not** on the internet. Do not add port forwarding or tunnels without a proper HTTPS setup.
- Traffic uses plain **HTTP**, so passwords travel unencrypted over the office Wi-Fi. Acceptable for a trusted internal network; add HTTPS (a reverse proxy with a certificate) before wider use.
- Everyone needs their own account; only administrators can change data.
- Keep `.env` and `_revert/env.before-lan.bak` private — they contain the database password and secret key.
- Take regular database backups and copy them off this PC. A backup is one command:
  ```powershell
  cd C:\Users\jayap\SupplyChainPortal
  $stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
  docker compose exec -T db pg_dump -U supplychain -d supplychain -Fc -f /tmp/backup.dump
  docker compose cp db:/tmp/backup.dump "backups\supplychain_$stamp.dump"
  ```
