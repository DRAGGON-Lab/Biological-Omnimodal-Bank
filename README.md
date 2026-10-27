# BOB: Biological Omnimodal Bank

BOB stores, links, and visualizes characterization data for synthetic biology. Raw instrument files are kept unchanged and identified by their SHA-256, a declarative JSON mapping turns each instrument's export into BOB's shared data model, and every study exports as SBOL 2.3 so the measurements link back to the designs they came from.

BOB 1.0 reads plate readers: BioTek Gen5 kinetic exports, as Excel workbooks or as tab- or comma-separated text, the form SynBioSuite sends. Flow cytometry (FCS 3.1 and 3.2) is next on the roadmap, followed by omics and microscopy.

## What it does

- **Original files kept intact.** BOB saves every instrument export byte for byte and identifies it by its SHA-256.
- **Code-free mapping.** A guided form configures how to read a new instrument, without JSON or regular expressions, and validates the mapping against a real file before saving.
- **Samples linked to their designs.** Each sample points to its SBOL design in SynBioHub, including its medium, host, plasmids, and supplement quantities.
- **Analysis with explicit provenance.** Five workflows, from growth curve to growth and production profiles, each with the control wells you select.
- **Results you can keep.** Results in JSON, figures in SVG, tables in CSV, and figure recipes that reopen with the same selection.
- **Versioned publication.** Studies are published with a license and their authors, and every previous version remains readable.
- **Open standards.** Each study exports as SBOL 2.3, ISA-JSON, and RO-Crate.

## Quick start

Requires Docker. **Start Docker Desktop first** and wait until it reports that it is running; `docker compose` fails at once if the Docker daemon is stopped.

```sh
docker compose up --build
```

Open http://localhost:8000 (use `localhost` or `127.0.0.1`; other host names are refused unless listed in `BOB_ALLOWED_HOSTS`) and sign in with the demo account:

| Email | Password |
|---|---|
| `demo@bob.local` | `bob-demo-2026` |

This account exists because `docker-compose.yml` sets `BOB_SEED_DEMO=1`, and its password is public. On any server other people can reach, set `BOB_SEED_DEMO=0` before the first start. Seeding runs only once, so turning it off later leaves an existing demo account in place: delete it or change its password.

The demonstration workspace contains a synthetic plate with sample wells, untransformed host cells, and medium blanks. Its example IRIs point to example.org, not to real strains.

Interactive API documentation is at http://localhost:8000/docs once BOB is running.

## Documentation

The wiki covers the details:

- [Install and deploy](../../wiki/Install-and-deploy): prebuilt image, API-only mode, PostgreSQL, settings, running without Docker
- [Using BOB](../../wiki/Using-BOB): how the data is organized, publishing and versions, analysis workflows, exports
- [Standards and integrations](../../wiki/Standards-and-integrations): SBOL, ISA-JSON and RO-Crate, SynBioHub, workbooks and SynBioSuite
- [Development](../../wiki/Development): tests, migrations, standards checks

## License

BOB is free for noncommercial use under the [PolyForm Noncommercial License 1.0.0](LICENSE): research, teaching, personal projects, and use by universities, public research organizations and charities, whatever their funding. Keep the license and its `Required Notice` line with every copy you share.

Commercial use, such as use by a company in its business or as part of a paid product or service, needs a separate commercial license. Ask at carolus.vitalis@outlook.com.

The CC BY 4.0 and CC0 1.0 licenses a study can be published under apply to the data it carries, not to this code.

If you use BOB in published work, please cite it; `CITATION.cff` has the details.
