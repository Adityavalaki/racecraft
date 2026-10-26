# Packaging Racecraft for Windows (personal / sideload)

This builds Racecraft into a standalone Windows app and, optionally, a signed
MSIX you can install without the Microsoft Store. It is for your own use and
sideloading — **not** Store publishing, which raises F1 data and trademark
questions that are out of scope here.

Everything runs from the repo root, in the project venv.

## What you get

- `dist\Racecraft\Racecraft.exe` — the whole app frozen, no Python needed.
  Zip the `dist\Racecraft` folder and copy it to any Windows 10/11 machine; it
  runs as-is. This alone is enough for sideloading by hand.
- `dist\Racecraft.msix` — the same app as an installer that puts Racecraft in
  the Start menu and updates cleanly. Needs the Windows SDK to build and a
  one-time certificate trust to install.

Frozen, the app keeps its data (lake, caches, logs) in
`%LOCALAPPDATA%\Racecraft`, not in the install folder — so the install stays
read-only, which MSIX requires. A source checkout is unchanged: it still uses
`data\` beside the code.

## 1. Build the app (always)

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_app.ps1
```

Builds the interface if needed, then freezes with
[`Racecraft.spec`](Racecraft.spec). Output: `dist\Racecraft\Racecraft.exe`
(~340 MB; a scientific-Python app carries numpy, scipy, pyarrow and duckdb).

To stop here and sideload by hand: zip `dist\Racecraft`, copy it over, run the
exe. Done.

## 2. Build an MSIX (optional)

Prerequisites, once per machine:

- **Windows SDK** (for `makeappx.exe` and `signtool.exe`):
  `winget install Microsoft.WindowsSDK.10.0.22621`
- **A signing certificate** (self-signed is fine for personal use):
  ```powershell
  powershell -ExecutionPolicy Bypass -File packaging\make_cert.ps1
  ```
  Its subject is `CN=Racecraft Dev` and must match the `Publisher` in
  [`msix\AppxManifest.xml`](msix/AppxManifest.xml). Keep the resulting
  `RacecraftDev.pfx` private.

Then pack and sign:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_msix.ps1
```

Output: `dist\Racecraft.msix`, signed.

## 3. Install the MSIX

In an **elevated** PowerShell (trusting the cert writes to the machine store):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\install_msix.ps1
```

This trusts `RacecraftDev.cer` once and installs the package. Afterwards,
Racecraft is in the Start menu. New builds signed with the same cert install
without re-trusting — bump `Version` in the manifest so Windows sees an update.

Remove it with:

```powershell
Get-AppxPackage *Racecraft* | Remove-AppxPackage
```

## Notes and limits

- **The assets** (`msix\Assets`) are generated from the app icon by
  [`make_msix_assets.py`](make_msix_assets.py); re-run it if the icon changes.
- **WebView2 runtime** must be present on the target. Windows 11 ships it;
  Windows 10 usually has it via Edge, otherwise install the Evergreen runtime.
- **The certificate and the manifest Publisher must match exactly.** If you
  change one, change the other, or installation fails with a signature error.
- **Do not commit** `*.pfx`, `*.cer`, `dist\` or `build\` — they are ignored in
  `.gitignore`. The `.pfx` is a private key.
- **Store publishing is deliberately not covered here.** See the project
  discussion: the F1 data terms, licensing and trademarks need resolving first.
