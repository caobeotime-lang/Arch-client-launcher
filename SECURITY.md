# Security

## What the launcher verifies
- **HTTPS certificate verification is ON** (CA bundle from `certifi`). Earlier builds disabled it; do not use builds older than 1.3.1.
- **Mods from Modrinth** are checked against the SHA-512 (or SHA-1) hash published by the Modrinth API before they are saved into `mods/`.
- **Java (Eclipse Temurin)** is checked against the official SHA-256 from the Adoptium API before it is extracted. If the checksum can't be fetched or doesn't match, Java is **not** installed.
- Downloaded archives are rejected if they contain paths that escape the target folder (zip-slip / tar traversal).
- The Microsoft access token is kept in memory only; it is not written to the config file.

## Verifying a release
Download `ArchClient-windows.zip` and `SHA256SUMS.txt` from the Releases page, then in PowerShell:

```powershell
(Get-FileHash .\ArchClient-windows.zip -Algorithm SHA256).Hash.ToLower()
```

The output must equal the hash in `SHA256SUMS.txt`. Only download from this repository's Releases page.

## Known limitations
- The `.exe` is **not code-signed** (needs a paid certificate), so SmartScreen may warn on first run.
- If you are behind a proxy/antivirus that intercepts HTTPS, downloads can now fail with a certificate error instead of silently succeeding. Add the proxy's root CA to the system trust store rather than disabling verification.

## Reporting a vulnerability
Open a private security advisory on GitHub (Security tab -> Report a vulnerability) or an issue without exploit details.
