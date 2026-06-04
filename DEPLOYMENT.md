# Deploying the GO-Canada Dashboard Online

This project is prepared for Streamlit Community Cloud.

The hosted version should normally run in read-only mode. Users can filter, view graphs, inspect data quality, and export CSVs, but they cannot permanently import or manually add papers from the hosted app. To update the online database, edit the CSV files locally, commit them to GitHub, and redeploy.

## Files Required For Deployment

Your GitHub repository should include:

```text
app.py
requirements.txt
README.md
DEPLOYMENT.md
.streamlit/config.toml
.streamlit/secrets.toml.example
data/
  authors.csv
  instruments.csv
  paper_authors.csv
  paper_instruments.csv
  paper_sources.csv
  papers.csv
  sources.csv
  verification.csv
```

Do not commit a real `.streamlit/secrets.toml` file. Use Streamlit Community Cloud's Secrets UI instead.

## Streamlit Cloud Secret

In Streamlit Community Cloud, add this secret:

```toml
GO_CANADA_READ_ONLY = "true"
```

This disables features that try to write permanent CSV changes:

- adding/importing papers
- saving new preset JSON files

Filtering, graphs, data quality checks, manual session exclusions, and CSV exports still work.

## Step-by-Step: What You Need To Do

### 1. Create a GitHub account

If you do not already have one, create a GitHub account at:

```text
https://github.com
```

### 2. Create a new GitHub repository

Create a repository named something like:

```text
go-canada-dashboard
```

It can be public or private. Public is easier for simple Streamlit Community Cloud deployment. Private can also work if you give Streamlit access.

### 3. Upload this project

Upload the full project folder to the GitHub repository.

Make sure these files and folders are present in GitHub:

```text
app.py
requirements.txt
runtime.txt
README.md
DEPLOYMENT.md
.streamlit/config.toml
.streamlit/secrets.toml.example
data/
```

Do not upload:

```text
__pycache__/
.DS_Store
.venv/
.streamlit/secrets.toml
```

The included `.gitignore` is set up to prevent those files from being committed if you use Git from your computer.

### 4. Create a Streamlit Community Cloud account

Go to:

```text
https://share.streamlit.io
```

Sign in with GitHub and allow Streamlit to access the repository.

### 5. Create the app

In Streamlit Community Cloud:

1. Click `Create app`.
2. Choose `Yup, I have an app`.
3. Select your GitHub repository.
4. Select the branch, usually `main`.
5. Set the main file path to:

```text
app.py
```

6. Choose a custom app URL if you want one.

### 6. Add the read-only secret

Before deploying, open `Advanced settings`.

In the `Secrets` box, paste:

```toml
GO_CANADA_READ_ONLY = "true"
```

Then save the settings.

### 7. Deploy

Click `Deploy`.

Streamlit will install dependencies from `requirements.txt`, run `app.py`, and give you a public link.

### 8. Test the hosted app

Open the Streamlit link and check:

1. The dashboard loads.
2. Filters work.
3. Graphs work.
4. Data Quality page works.
5. Exports download CSVs.
6. The `Add / Import Papers` page is hidden.
7. Preset saving is disabled.

### 9. Update the online data later

To update the hosted dashboard:

1. Run the app locally.
2. Use `Add / Import Papers`, or edit the CSV files in `data/`.
3. Test locally with:

```bash
streamlit run app.py
```

4. Commit and push the updated CSV files to GitHub.
5. Streamlit Community Cloud redeploys from GitHub automatically.

## Local Editing Workflow

Use the local app when you want to edit the database:

```bash
streamlit run app.py
```

Then use the Add / Import Papers page locally. After editing:

1. Check the CSV files in `data/`.
2. Commit the changed CSV files to GitHub.
3. Push to GitHub.
4. Streamlit Cloud will redeploy from the updated repository.

## If You Want Online Editing Later

The current hosted setup is intentionally read-only because Streamlit Cloud file writes are not a good permanent database. If multiple people need to edit online, the next upgrade should be a persistent backend such as:

- SQLite on a controlled server
- PostgreSQL
- Supabase
- Google Sheets
- Airtable

That would let imports and manual edits persist safely online.
