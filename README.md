# Vodafone Station (ARRIS) for Home Assistant

Custom integration for ARRIS-made Vodafone Stations (Germany, cable/DOCSIS), which
the built-in `vodafone_station` integration rejects as "not supported".

Tested on: **ARRIS TG6442**, firmware `01.05.069.14.EURO.PC20`
(`AR01.05.069.14_070726_735.PC20.20.VF`), Home Assistant 2026.10.4.
The TG3442DE uses the same web UI protocol and may work too (untested).

## What you get (read-only)

- **Device trackers** for every device on LAN, Wi-Fi and guest Wi-Fi.
  As with other router integrations, trackers for devices HA doesn't otherwise know
  are created **disabled**; enable the ones you care about.
- **Sensors:** connected devices (total / LAN / Wi-Fi / guest), modem status,
  last boot, firmware, WAN IPv4/IPv6, DOCSIS locked channels, downstream SNR min,
  downstream power min/max, upstream power max, last successful read.
- **Binary sensors:** Wi-Fi, guest Wi-Fi, *Web UI in use*.

## The router allows only one web session

Logging in silently takes over any other session. To avoid kicking you out of the
web UI, every poll (60 s):

1. reads the start page **without logging in**: `nonActiveSession` is `'1'` only
   when nobody is logged in;
2. if someone is, skips the poll and keeps the last data (*Web UI in use* turns on);
3. otherwise logs in, reads three pages, and logs out again.

If you log in during the ~1 s HA holds the session and confirm the takeover, HA
notices, keeps its last data and does **not** log out (that could end your session).

A rejected login stops polling and asks for the password again (reauth), because
repeated wrong passwords extend the router's lockout.

## Install

HACS → custom repository → this repo, category *Integration*. Or copy
`custom_components/vodafone_station_arris` into your HA `config/custom_components/`.
Then *Settings → Devices & services → Add integration → Vodafone Station (ARRIS)*.
Log out of the router's web UI first.

## Check your router before installing

```
uv run --with aiohttp --with cryptography python -I scripts/probe.py 192.168.0.1
```

Does one read-only poll with the integration's own client and prints counts and
versions only (no MACs, names, IPs or serial).

## Development

```
uv run --group dev pytest                                                   # client, protocol fake, probe
uv run --python 3.14 --with pytest-homeassistant-custom-component pytest tests_ha   # HA integration
```

`tests/fake_router.py` re-implements the router's login protocol (PBKDF2 + AES-CCM,
single active session, takeover) so the client is tested end to end without hardware.
Fixtures are synthetic.

## Protocol notes

- Start page `/` carries `currentSessionId`, `myIv`, `mySalt` (hex) and `nonActiveSession`.
- Key = PBKDF2-HMAC-SHA256(password, salt, 1000 iterations, 16 bytes).
- `POST php/ajaxSet_Password.php` with `{"EncryptData": hex(AES-CCM(key, iv, aad="loginPassword",
  '{"Password": "<pw>", "Nonce": "<sessionId>"}')), "Name": "admin", "AuthData": "loginPassword"}`.
  Reply `p_status` contains `Match` on success; `Lockout` + `p_waitTime` (seconds) on a wrong password.
  `encryptData` decrypts (aad `"nonce"`) to the CSRF nonce, sent as the `csrfNonce` header.
- `POST php/ajaxSet_Session.php` activates the session (this is the takeover).
- Data: `php/overview_data.php`, `php/status_status_data.php`, `php/status_docsis_data.php`
  (JavaScript assignments: `js_x = '...'`, `json_x = <json>`). `php/logout.php` ends it.

Credit: login flow cross-checked against
[vodafone-station-cli](https://github.com/totev/vodafone-station-cli) (TG3442DE).
