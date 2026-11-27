# Research Connections

A searchable directory of fictional researchers and projects. Find people by their work, expertise, support needs or desired outcomes, then follow the projects that connect them.

The interface uses a search bar. No SQL knowledge is needed.

## Run locally

The database is included. Python's standard library is the only runtime dependency.

```bash
conda env create -f environment.yml
conda run --no-capture-output -n research-connections python playground/server.py
```

Open **http://127.0.0.1:8765**. Stop the server with Ctrl+C.

If you already have a suitable conda environment with Python 3.11 or later, use it instead; no packages need installing. On the original Mac, the existing `base` environment works. The optional [Mac launcher](Start%20Research%20Connections.command) opens the app in your browser and uses `base` unless `RESEARCH_CONDA_ENV` names another environment.

The repository contains the app and dataset. GitHub does not run the Python server; this is a local application, not a hosted website.

## Search

| Input | Meaning |
| --- | --- |
| `cellulose` | Contains this text |
| `carbon capture` | Contains both words |
| `"carbon dioxide"` | Contains the complete phrase |
| `cellulose OR biocomposites` | Contains either term |
| `carbon AND capture OR hydrogen` | Contains carbon and capture, or hydrogen |

Search is case-insensitive for the dataset's English text. Quoted phrases stay together; unquoted words use AND, with OR separating groups. A person's matching words can appear in different fields or different linked projects.

Use **People** or **Projects**, then filter by research area, role or search field. Each result includes an excerpt and its source. Search links preserve the query and filters in the URL. Names and project titles open full profiles.

Search covers:

- People: names, research summaries, expertise, support needs, desired outcomes and linked project descriptions, needs and outcomes.
- Projects: titles, research summaries, required expertise, support needs and desired outcomes.

Search matches literal text, not synonyms or meaning. `biomaterials` will not automatically match `biocomposites`.

A person's profile also offers potential collaborators based on matching expertise tags. Suggestions exclude the same person and current project collaborators. They do not assess availability or scientific suitability.

## Dataset

- 1,000 fictional researchers: 150 PIs, 350 post-docs and 500 PhD researchers.
- 1,500 projects and 3,000 researcher–project links.
- Each person has 1–5 projects, capabilities, support needs and desired outcomes.
- Four areas: Sustainable Energy, Materials Circularity, Green Robotics and Water for Life.

The research themes are inspired by [IIT's SUSTech programme](https://sustech.iit.it/research). **Research Connections is an independent prototype, not an IIT or SUSTech product.** Every person, project, capability, opinion and outcome is invented. No actual staff records were scraped. Numerical outcomes are hypothetical targets, not measured results.

The database retains its original filename, `data/sustech_synthetic.sqlite`. See the [sample profiles](data/sample_profiles.txt), [data model](docs/data-model.md) and [validation report](data/validation_report.json).

## Development

```bash
conda run -n research-connections python -m unittest discover -s playground -v
node --check playground/static/app.js
conda run -n research-connections python scripts/validate_dataset.py data/sustech_synthetic.sqlite
```

The application tests check search logic, phrases, linked projects, excerpts, filters, pagination, collaborator relationships and database write protection. Node is only used for the optional JavaScript syntax check.

The server binds to `127.0.0.1`, opens SQLite in read-only mode, and accepts parameterized searches. There is no arbitrary-SQL web endpoint, external API, tracking or required frontend build. This server is intended for local use.

| Path | Contents |
| --- | --- |
| `playground/server.py` | Python server, search and profile queries |
| `playground/static/` | HTML, CSS and JavaScript |
| `playground/test_server.py` | Search and relationship tests |
| `data/sustech_synthetic.sqlite` | Included relational database |
| `schema.sql` | Tables, keys, indexes and views |
| `example_queries.sql` | SQL examples for inspecting the database directly |
| `scripts/` | Deterministic data generator and validator |

## Regenerate the data

```bash
conda run -n research-connections python scripts/generate_dataset.py --seed 20261126 --force
```

This replaces the generated database and exports. For a separate variation, use `--seed 42 --output data_seed42`. Large nested JSON exports are generated locally and excluded from Git because they duplicate the database.
