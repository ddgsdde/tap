# Vendored solver sources

These sources are committed so a sandbox can build the proof toolchain without
network access or a package manager.

| Component | Version / commit | Upstream | License |
| --- | --- | --- | --- |
| Kissat | 4.0.4, `8af8e56f174b778aef3aa45af9f739b2a5f492c2` | https://github.com/arminbiere/kissat | MIT (`kissat/LICENSE`) |
| drat-trim | `2e3b2dc0ecf938addbd779d42877b6ed69d9a985` | https://github.com/marijnheule/drat-trim | MIT (`drat-trim/LICENSE`) |

No prebuilt executable is trusted or required. `tools/offline/build.sh` builds
both programs from these pinned sources using the local C compiler.
