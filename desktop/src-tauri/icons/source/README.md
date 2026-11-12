# Icon source

`reframe.svg` is the app icon. The PNG and ICO files in `icons/` are made from it:

```sh
cd desktop && npx tauri icon src-tauri/icons/source/reframe.svg -o src-tauri/icons
```

Then delete what the desktop packages do not use (`android/`, `ios/`, `Square*Logo.png`,
`StoreLogo.png`, `icon.icns`).
