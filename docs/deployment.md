# Deployment and data refresh

## Streamlit Community Cloud

1. Push the repository to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) and click **Create app**. Choose the
   repository, branch `main`, and main file `dashboard/app.py`.
3. Under **Advanced settings**, choose Python 3.12. No secrets are needed: the StatBank API is
   public, and the app never calls it.
4. Deploy. `requirements.txt` installs the pinned dependencies and the project package
   (`-e .`). On first start, the app builds its DuckDB database from `data/snapshot/`, which
   takes about 10 seconds.
5. Add the app URL to the README.

The hosting filesystem is temporary, so the app never relies on files it writes there. The
only durable data is the committed snapshot.

## Automated refresh

`.github/workflows/refresh-data.yml` runs on the 15th of every month and can also be started
manually from the **Actions** tab. It goes through these steps:

1. It runs the live API smoke test.
2. It runs the full pipeline against the API, including every quality check.
3. It rebuilds the database offline from the new snapshot and re-validates it.
4. It uploads the snapshot and the run log as a workflow artifact.
5. It opens a pull request with the new snapshot, but only if the data content changed.

For step 5 to work, enable **Settings → Actions → General → Workflow permissions → Allow
GitHub Actions to create and approve pull requests** in the repository settings.

Merging the pull request publishes the data. Streamlit Community Cloud redeploys on the push to
`main`, and the app rebuilds its database from the new snapshot.

If the API is down or a critical check fails, the workflow fails and shows red in the Actions
tab. Nothing is committed, and the published data stays as it was.

## CI badge

Once the first CI run on GitHub has passed, add this under the README title:

```markdown
[![CI](https://github.com/mariusgreiersen/copenhagen-data-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/mariusgreiersen/copenhagen-data-lab/actions/workflows/ci.yml)
```

## Docker (optional)

```bash
docker build -t copenhagen-data-lab .
docker run --rm -p 8501:8501 copenhagen-data-lab
```

The image builds the database from the snapshot at build time. The Dockerfile has not been
tested in CI.
