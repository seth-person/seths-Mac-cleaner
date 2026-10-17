# Signing identity

`mac-cleaner-signing.p12` is a self-signed code-signing certificate (password `mac-cleaner`).
The Release workflow signs every build of Mac Cleaner.app with it.

It isn't for Gatekeeper; only a paid Apple Developer ID can satisfy that. It's here so that
every version of the app has the **same identity**. macOS ties Full Disk Access and the
"allow access to your Downloads folder" answers to that identity. With throwaway (ad-hoc)
signatures, every update would look like a new app and macOS would ask again.

It lives in this private repository on purpose: anyone who can read the repo can already
publish an update, so the key doesn't grant anything extra. Don't reuse it for anything
else. To replace it, generate a new one the same way. macOS will then ask for permissions
once more after the next update.
