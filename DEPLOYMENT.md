# Deploying the GO-Canada Dashboard Online

This project is prepared for Streamlit Community Cloud.

The public dashboard can run in read-only mode while password-protected admins edit the database online. Permanent online editing uses Supabase as the database backend. If Supabase is not configured, the app falls back to the CSV files committed in `data/`.

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

For a public read-only dashboard, add this secret:

```toml
GO_CANADA_READ_ONLY = "true"
```

This hides public CSV editing features:

- adding/importing papers
- saving new preset JSON files

Filtering, graphs, data quality checks, manual session exclusions, and CSV exports still work.

For password-protected online editing, also add:

```toml
GO_CANADA_ADMIN_PASSWORD = "choose-a-password"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
```

The service role key must stay in Streamlit secrets only. Do not commit it to GitHub.

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

### 7. Optional: enable online editing with Supabase

1. Create a Supabase project.
2. Open Supabase SQL Editor.
3. Run the SQL in:

```text
docs/supabase_schema.sql
```

If your Supabase project already exists, run the current schema again. It uses
`create table if not exists`, so it will add new tables such as `global_presets`
without replacing existing paper data.

4. In Streamlit Cloud secrets, add:

```toml
GO_CANADA_READ_ONLY = "true"
GO_CANADA_ADMIN_PASSWORD = "choose-a-password"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
```

5. Deploy or reboot the app.
6. Open the app and choose **Admin Editor** in the sidebar.
7. Enter the admin password.
8. Open **Online Database**.
9. Click **Seed / replace Supabase from repository CSVs** once.

After that, the dashboard loads from Supabase and admin edits save directly online.

### 8. Deploy

Click `Deploy`.

Streamlit will install dependencies from `requirements.txt`, run `app.py`, and give you a public link.

### 9. Test the hosted app

Open the Streamlit link and check:

1. The dashboard loads.
2. Filters work.
3. Graphs work.
4. Data Quality page works.
5. Exports download CSVs.
6. The public `Add / Import Papers` page is hidden when read-only mode is on.
7. Public users can load shared presets but cannot edit them.
8. If Supabase is configured, the **Admin Editor** page appears and requires the password.

### 10. Update the online data later

With Supabase configured:

1. Open the hosted Streamlit app.
2. Choose **Admin Editor**.
3. Enter the admin password.
4. Add papers, import a CSV, or change verification status.
5. Create or update shared presets from the **Shared Presets** admin tab.
6. The app saves directly to Supabase.

Without Supabase:

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

## Admin Editing Features

After unlocking **Admin Editor**, admins can:

- add one paper manually
- download a CSV import template
- upload a paper CSV
- change a paper-instrument verification status
- add evidence quotes and notes
- create, update, and delete shared presets visible to everyone
- seed or replace Supabase from the repository CSV database
