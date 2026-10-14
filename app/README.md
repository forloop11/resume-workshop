# The Resume Workshop editor

The desktop editor: a [Tauri](https://tauri.app/) app with the
[tauri-ui](https://github.com/agmmnn/tauri-ui) stack (React,
[shadcn/ui](https://ui.shadcn.com/), and Tailwind CSS) for its window, and
the project's own Python behind it. What it does, and how to use it, is in
the main [README](../README.md#local-editor); this is how it is built.

## How it is put together

- [src/](src/) is the window, in TypeScript and React: the block editor
  ([components/blocks.tsx](src/components/blocks.tsx)), the PDF preview
  ([components/pdf-view.tsx](src/components/pdf-view.tsx), drawn with
  [PDF.js](https://mozilla.github.io/pdf.js/)), the ATS check, Page Setup,
  and the menus ([App.tsx](src/App.tsx)).
- [backend/server.py](backend/server.py) is everything that isn't drawing:
  opening and saving resume folders, checking a resume, and building it,
  with the modules in [backend/](backend/) and the generators in
  [../scripts/](../scripts/), so the editor and `make build` follow the
  same rules. The window sends it requests as lines of JSON and reads its
  answers.
- [src-tauri/](src-tauri/) is the Tauri shell, in Rust: it opens the
  window, runs the backend as a child process, and passes requests between
  them ([src/lib.rs](src-tauri/src/lib.rs)).

## Running it

From the repository's root, after `pip install jsonschema`:

- `make app-web` builds the window and serves it, with the backend, at
  <http://127.0.0.1:3210/> for a web browser. It needs Node, and no Rust.
  The folder and file dialogs, which the Tauri shell provides, are stood in
  for by typing a path.
- `make app-test` drives that in a headless Chrome
  ([tests/smoke.mjs](tests/smoke.mjs)): it opens a new resume folder, edits
  it, waits for the live preview, saves, and builds.
- `make editor` runs the Tauri app itself (`npm run tauri dev`). It needs Rust
  with Cargo, and the system packages Tauri lists in its
  [prerequisites](https://tauri.app/start/prerequisites/); on Fedora:

  ```sh
  sudo dnf install cargo webkit2gtk4.1-devel gtk3-devel libsoup3-devel openssl-devel librsvg2-devel libappindicator-gtk3-devel
  ```

`make app-window-test` drives the app itself, through WebDriver
([tests/window.mjs](tests/window.mjs)): the Tauri window, its web view, and
the backend it starts. It needs `cargo install tauri-driver --locked` and
the system's WebKitWebDriver, and shows the window while it runs.

`npm run screenshots` retakes the pictures in the main README
([tests/screenshots.mjs](tests/screenshots.mjs)), and `npm run demo`
records the animated tour at its top
([tests/demo.mjs](tests/demo.mjs)), which needs ffmpeg as well.

### As something to install

`make appimage` builds `dist/Resume_Workshop-x86_64.AppImage` with
[../packaging/build_app.py](../packaging/build_app.py), and
`make install-appimage` installs it for your user. It carries a Python of
its own with jsonschema, the backend, Tectonic, and the TeX packages the
layout loads, so it needs nothing installed and builds PDFs without a
network. Tauri's bundler adds WebKitGTK and GTK from the machine it is
built on, so the AppImage runs on systems at least as new as that one.

The same script builds a `.dmg` on macOS and an installer on Windows, and
the release workflow runs it on all three
([../.github/workflows/release.yml](../.github/workflows/release.yml)).

`make test` runs the backend's tests ([../tests/test_backend.py](../tests/test_backend.py))
with the rest.

## What hasn't been done

- The app has been used on Linux only. The macOS and Windows builds are
  made by the release workflow and haven't been run by anyone: they aren't
  signed, and nothing of what an app store asks for (signing, the Mac App
  Store's sandbox and its entitlements, an MSIX package for the Microsoft
  Store) has been done.
- In the app itself, drag and drop, printing, and the folder and file
  dialogs are tried by hand only; the tests don't reach them.
- Five of the Rust crates Tauri is built from (cssparser, cssparser-macros,
  selectors, dtoa-short, and option-ext) are under the Mozilla Public
  License 2.0, where the rest are MIT, Apache 2.0, BSD, or the like; and on
  Linux the web view is WebKitGTK (LGPL), which the AppImage carries and
  the `.deb` and `.rpm` packages leave to the system.
