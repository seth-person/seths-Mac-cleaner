# Signing identity

Every build of Mac Cleaner.app is signed with one self-signed code-signing certificate:
`mac-cleaner-signing.cert.pem` here (SHA-1 `87E3B0B19C279F3DA12D671B134BB640D124C9A6`).
Only the public certificate is in this repo.

It isn't for Gatekeeper; only a paid Apple Developer ID can satisfy that. It does two jobs:

- **macOS remembers the app's permissions across updates.** Full Disk Access and the
  "allow access to Downloads" answers are tied to the app's signing identity.
- **The updater only installs genuine builds.** `macclean/updater.py` pins this certificate
  and refuses any downloaded update that isn't signed with it.

The private key lives only in the repository's encrypted Actions secret
`MACOS_SIGNING_P12_BASE64` (a base64 .p12, password `mac-cleaner`). The Release workflow
refuses to publish without it.

## History

Versions 0.3.0 and 0.3.1 were signed with an earlier key that was committed to this repo
while it was private. That key is retired. Since 0.4.0 the app clears permissions granted
to older builds the first time it runs (`reset_permissions_if_new_identity`), so the old
key can't inherit them.

## Replacing the key

1. Make a new self-signed code-signing certificate and a .p12 with password `mac-cleaner`.
2. Put the base64 .p12 in the `MACOS_SIGNING_P12_BASE64` secret, and the certificate here.
3. Installed apps only accept updates signed with the pinned certificate. So first ship a
   release signed with the *current* key whose `SIGNING_CERT_SHA1` is the *new* one, then
   switch the secret.
