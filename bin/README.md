# Runtime binaries

The source repository intentionally does not track the portable runtime payload stored in this directory.

Official release archives populate `bin/` with the exact runtime components required by that release. These may include the embedded Python environment, media tools, GPU runtime files, native workers, and other release-only dependencies. Many of these files are large, generated, prebuilt, or distributed under separate third-party licenses, so they are shipped with GitHub Releases instead of being committed to the source repository.

## Source checkout

A normal Git clone or GitHub-generated **Source code** archive is not the ready-to-run portable application. Use an official packaged release when you need the complete runtime.

## Development

Local development and packaging may populate `bin/` with the runtime files required by the current application version. Everything in this directory is ignored by Git except this `README.md` and `.gitignore`.

Runtime locations and required files are defined and validated by the application itself. This document intentionally does not duplicate binary versions, hashes, exact filenames, or per-release folder layouts, so routine dependency and runtime updates do not require documentation changes here.

## Third-party components

Third-party software and runtime components remain subject to their respective licenses and distribution terms. The project's MIT license applies only to original project code and does not relicense third-party binaries.

Applicable notices and license information should be preserved in packaged releases and in the project's main third-party/license documentation.
