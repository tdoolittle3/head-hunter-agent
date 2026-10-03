# Deploying

Two ways in: by hand from a checkout, or automatically from GitHub Actions on a
push to `main`. Both build the `Dockerfile` and run it on Cloud Run.

What runs there is the **signed-in server** (`head_hunter/server.py`), not the
`adk web` dev UI. The service is **public**: anyone can load the page, but every
API route needs a verified Google sign-in token, and the agent runs as the person
in that token. Their profile, jobs, resumes and conversations live in Firestore
under their own user id, so they survive restarts and instance changes.

`adk web` has no login and is never deployed. Use it locally with `make dev`.

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

### 3. Create the Firestore database

Deployments store through Firestore, so this has to exist before the first
deploy. One database per project; `(default)` is the one you get unless you name
another.

```bash
gcloud firestore databases create --location=us-central1 --project=head-hunter-agent --type=firestore-native
```

Give the runtime service account access to it. Firestore uses the Datastore IAM
roles — `roles/firestore.*` does not exist, which is a reliable half-hour lost
if you go looking for it:

```bash
gcloud projects add-iam-policy-binding head-hunter-agent \
  --member="serviceAccount:362441896728-compute@developer.gserviceaccount.com" \
  --role="roles/datastore.user"
```

### 4. Let the running service call Vertex

The same account is the Cloud Run runtime identity. Without this the container
starts and then every model call returns 403.

```bash
gcloud projects add-iam-policy-binding head-hunter-agent \
  --member="serviceAccount:362441896728-compute@developer.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### 5. Let the sign-in page work on the Cloud Run hostname

Firebase refuses to sign people in from a hostname it does not know. After the
first deploy, copy the service URL's host (the workflow prints it in its
summary) and add it, **without `https://` and with no wildcard**, under
**Authentication > Settings > Authorized domains** in the Firebase project
named in `head_hunter/web/firebase-config.json`.

That is a different Google Cloud project from the one hosting Cloud Run if you
created Firebase separately, so check the project picker before adding it.
Sign-in fails with `auth/unauthorized-domain` until this is done.

## Deploying by hand

```bash
make deploy-test TEST_PROJECT=head-hunter-agent
```

### On Windows

`make` is usually absent. Run the command it would run — `make -n deploy-test
TEST_PROJECT=...` prints it — from **PowerShell**, not Git Bash.

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

## Using a deployed service

Open the service URL, click **Sign in with Google**, and chat. Nothing to
install and no tunnel. Different Google accounts get different profiles.

```bash
gcloud run services describe head-hunter-test --project=head-hunter-agent   --region=us-central1 --format='value(status.url)'
```

The workflow smoke-tests every deploy: `/healthz` must answer, and chat with no
token, or a forged one, must be refused with a `401`. If either check fails the
deploy is marked failed. Run the same check by hand any time:

```bash
URL=https://your-service-url
curl -s -o /dev/null -w "%{http_code}
" -X POST -H 'Content-Type: application/json'   -d '{"message":"hi"}' "$URL/api/chat"    # must print 401
```

## Cost protection

The service is public and every message is a paid Gemini call, so three limits
stand between a bad actor and your bill:

- **Per-user limits** in the app: 10 messages a minute and 200 a day by default
  (`HH_RATE_PER_MINUTE`, `HH_RATE_PER_DAY`). They are counted per instance, so
  the real ceiling is the limit times `--max-instances`.
- **`--max-instances`**, 3 by default (`make deploy-test MAX_INSTANCES=5`). This
  bounds how much traffic can ever be processed at once.
- **Sign-in required.** Anonymous callers are refused before any model call.

Be aware that **anyone with a Google account can sign in**. There is no allow-list
yet, so the limits above are the only brake on a determined person with many
accounts. Set a budget alert on the billing account too:
**Billing > Budgets & alerts**.

## Turning it off in an emergency

Public access is one IAM binding. Remove it and the service is private again
within seconds; nothing is lost:

```bash
gcloud run services remove-iam-policy-binding head-hunter-test   --project=head-hunter-agent --region=us-central1   --member=allUsers --role=roles/run.invoker
```

The next `make deploy-test` puts it back.

## Debugging a deployed service

- **Page loads, sign-in popup fails with `auth/unauthorized-domain`** — step 5 above.
- **Sign-in works, every chat says "Your sign-in was not accepted"** — the server
  trusts a different Firebase project than the page signs in against. The server
  checks this on startup, so look at the revision logs; it will have refused to
  start. A deploy that cannot start never takes traffic.
- **Revision fails to start with `HH_SINGLE_USER is set`** — a leftover pin. The
  deploy replaces the service's whole environment, so this means it was set in
  the command or workflow variables. Remove it there.
- **403 from Vertex in the logs** — the runtime service account needs
  `roles/aiplatform.user` (step 4).
