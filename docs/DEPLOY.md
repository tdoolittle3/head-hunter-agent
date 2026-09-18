# Deploying

Two ways in: by hand from a checkout, or automatically from GitHub Actions on a
push to `main`. Both end at the same place — a **private** Cloud Run service you
reach through an authenticated tunnel.

Read the warning in `README.md` first: the deployed agent forgets everything on
restart. This is a smoke test until Firestore lands in Phase 3.

## One-time project setup

Replace `head-hunter-agent` with your project id and `362441896728` with its
project number (`gcloud projects describe <id> --format='value(projectNumber)'`).

### 1. Enable the APIs

```bash
make enable-apis PROJECT=head-hunter-agent
```

### 2. Let Cloud Build build

Deploying from source runs a Cloud Build job as the default compute service
account. Out of the box that account cannot read the source bucket Cloud Run
uploads to, and the deploy fails with `PERMISSION_DENIED: Build failed because
the default service account is missing required IAM permissions`.

```bash
gcloud projects add-iam-policy-binding head-hunter-agent \
  --member="serviceAccount:362441896728-compute@developer.gserviceaccount.com" \
  --role="roles/cloudbuild.builds.builder"
```

### 3. Let the running service call Vertex

The same account is the Cloud Run runtime identity. Without this the container
starts and then every model call returns 403.

```bash
gcloud projects add-iam-policy-binding head-hunter-agent \
  --member="serviceAccount:362441896728-compute@developer.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

## Deploying by hand

```bash
make deploy-test TEST_PROJECT=head-hunter-agent
```

### On Windows

`make` is usually absent and `adk` is often not on `PATH` even when `google-adk`
is installed. Both have workarounds — but there is a trap between them.

Run the deploy from **PowerShell**, not Git Bash:

```powershell
python -m google.adk.cli deploy cloud_run --project=head-hunter-agent --region=us-central1 --service_name=head-hunter-test --with_ui --env GOOGLE_GENAI_USE_VERTEXAI=TRUE --env HH_USER_ID=local --env HH_DATA_DIR=/tmp/head-hunter-data head_hunter -- --no-allow-unauthenticated
```

Git Bash rewrites any argument that looks like a Unix path into a Windows one
before the program sees it, so `HH_DATA_DIR=/tmp/head-hunter-data` silently
becomes `HH_DATA_DIR=C:/Users/.../AppData/Local/Temp/head-hunter-data` — a path
that does not exist inside a Linux container. The deploy succeeds and the agent
fails at runtime, which is the worst combination. If you must use Git Bash,
prefix the command with `MSYS_NO_PATHCONV=1`.

## Deploying from GitHub Actions

`.github/workflows/deploy.yml` runs `make check` and then deploys. A push to
`main` goes to the **test** service. Production is manual: run the workflow from
the Actions tab and choose `prod`.

It authenticates with Workload Identity Federation, so there is no service
account key to store or rotate.

### 1. Create the deploy service account

```bash
gcloud iam service-accounts create github-deployer \
  --project=head-hunter-agent \
  --display-name="GitHub Actions deployer"
```

Grant it what a deploy needs — push a container, create a revision, and act as
the runtime service account:

```bash
for ROLE in roles/run.admin roles/cloudbuild.builds.editor \
            roles/artifactregistry.writer roles/storage.admin \
            roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding head-hunter-agent \
    --member="serviceAccount:github-deployer@head-hunter-agent.iam.gserviceaccount.com" \
    --role="$ROLE"
done
```

### 2. Create the identity pool and provider

```bash
gcloud iam workload-identity-pools create github \
  --project=head-hunter-agent --location=global \
  --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github \
  --project=head-hunter-agent --location=global \
  --workload-identity-pool=github \
  --display-name="GitHub" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == 'tdoolittle3/head-hunter-agent'"
```

The `--attribute-condition` is the part that matters. Without it, any GitHub
repository anywhere can mint a token for your project.

### 3. Let this repository impersonate the account

```bash
gcloud iam service-accounts add-iam-policy-binding \
  github-deployer@head-hunter-agent.iam.gserviceaccount.com \
  --project=head-hunter-agent \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/362441896728/locations/global/workloadIdentityPools/github/attribute.repository/tdoolittle3/head-hunter-agent"
```

### 4. Tell the repository where to deploy

```bash
gh variable set GCP_PROJECT_ID --body "head-hunter-agent"
gh variable set GCP_REGION --body "us-central1"

gh secret set GCP_DEPLOY_SA --body "github-deployer@head-hunter-agent.iam.gserviceaccount.com"
gh secret set GCP_WIF_PROVIDER --body "projects/362441896728/locations/global/workloadIdentityPools/github/providers/github"
```

Set `HH_MODEL` as a variable too if your project does not serve the default
model. Leave it unset otherwise — the workflow passes an empty `MODEL`, which
the Makefile ignores.

## Reaching a deployed service

Both services deploy with `--no-allow-unauthenticated`, so there is no URL you
can simply open.

```bash
make proxy-test TEST_PROJECT=head-hunter-agent
```

That serves the ADK web UI on `http://localhost:8080`, authenticated as you.
gcloud may install the `cloud-run-proxy` component the first time.

### If the UI is a blank page

Your browser's origin is not in `ALLOWED_ORIGINS`. The default covers both
supported routes — `http://localhost:8080` for the proxy on a laptop, and a
`regex:` pattern for Cloud Shell Web Preview, whose host carries a per-session
id and cannot be written out literally.

The dev UI is an Angular app loaded as ES modules, and module scripts are always
fetched in CORS mode, so they carry an `Origin` header even same-origin. ADK
answers every one with `403 Forbidden: origin not allowed` and no script ever
runs. Stylesheets are not fetched in CORS mode, so the CSS loads and you get a
styled blank page rather than an obvious error.

To confirm that is what you are hitting, ask for a script with an `Origin`
header. A `403` means the origin is missing from the list:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "Origin: $YOUR_ORIGIN" "$YOUR_URL/dev-ui/"
```

Reaching it from somewhere else again — a different port, a tunnel — means
adding that origin. The variable is a space-separated list:

```bash
make deploy-test TEST_PROJECT=head-hunter-agent \
  ALLOWED_ORIGINS="http://localhost:8080 https://my-tunnel.example"
```

Widening this does not widen access. The service stays private and IAM decides
who may call it; the origin list only decides whose browser can render the UI.

For a scripted check, call the API with an identity token instead:

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$(gcloud run services describe head-hunter-test --project=head-hunter-agent --region=us-central1 --format='value(status.url)')/list-apps"
```

## Giving a collaborator access

Grant the invoker role — do not make the service public:

```bash
gcloud run services add-iam-policy-binding head-hunter-test \
  --project=head-hunter-agent --region=us-central1 \
  --member="user:them@example.com" --role="roles/run.invoker"
```

Then send them this, which needs nothing installed:

> 1. Open <https://shell.cloud.google.com> and sign in with the Google account
>    you were granted access on.
> 2. Paste this and press Enter:
>
>    ```
>    gcloud run services proxy head-hunter-test --project=head-hunter-agent --region=us-central1
>    ```
>
>    Say yes if it offers to install a component. Leave it running — it will sit
>    there printing nothing, which is correct.
> 3. Click **Web Preview** (the eye icon, top right of the Cloud Shell toolbar)
>    and choose **Preview on port 8080**.
> 4. A new tab opens with the chat UI. Pick `head_hunter` from the dropdown at
>    the top and start typing.
>
> If the page is blank, tell me the port — Web Preview sometimes picks 8081 and
> the address has to be allowed before it will load.

Two things they should know before they spend real effort in it:

- **Nothing is saved.** Cloud Run wipes the container's disk on restart and
  sessions are held in memory, so a profile can vanish between visits. Until
  Firestore lands (Phase 3) this is for trying the agent, not for building a
  real career profile.
- **You share one profile.** `HH_USER_ID` is fixed to `local`, so everyone who
  reaches the service reads and writes the same record — and because each Cloud
  Run instance has its own disk, two people can even see different versions of
  it at the same time.
