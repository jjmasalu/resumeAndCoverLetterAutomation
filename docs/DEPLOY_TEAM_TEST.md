# Team Test Deployment

This project now supports a two-layer access model:

1. **Supabase Auth** for individual user accounts
2. **Rotatable team access code** for the shared test environment

The access-code gate is stored in Supabase and is currently **disabled by default** until you enable the first code.

## Recommended Shape

- Frontend: local CLI deploy from `frontend/` to **Vercel**
- Backend: `resume-api-team` on **Cloud Run**
- Database/Auth/Storage: existing **Supabase** project `resumeAndCoverLetterAutomation`
- Region: `us-east1`
- GCP project: `resumeandcoverletterautomation`

## 1. Build Images

Create an Artifact Registry Docker repository once:

```bash
gcloud artifacts repositories create resume-apps \
  --repository-format=docker \
  --location=us-east1 \
  --description="Resume AI team test images"
```

Build the backend image:

```bash
gcloud builds submit . \
  --config cloudbuild.backend.yaml \
  --substitutions _IMAGE=us-east1-docker.pkg.dev/resumeandcoverletterautomation/resume-apps/resume-api-team
```

Deploy the backend first:

```bash
gcloud run deploy resume-api-team \
  --image us-east1-docker.pkg.dev/resumeandcoverletterautomation/resume-apps/resume-api-team \
  --region us-east1 \
  --allow-unauthenticated \
  --port 8000 \
  --set-env-vars SUPABASE_URL=https://hwzptzrjqcniukwrjnrb.supabase.co,SUPABASE_SERVICE_KEY=<service-role-key>,GEMINI_API_KEY=<gemini-key>,TAVILY_API_KEY=<tavily-key>,FIRECRAWL_API_KEY=<firecrawl-key>,FRONTEND_URL=http://localhost:3000
```

## 2. Deploy the Frontend to Vercel

From the repo root, deploy the `frontend/` directory with both build-time and runtime env values:

```bash
vercel deploy frontend \
  --prod \
  --yes \
  --build-env NEXT_PUBLIC_SUPABASE_URL=https://hwzptzrjqcniukwrjnrb.supabase.co \
  --build-env NEXT_PUBLIC_SUPABASE_ANON_KEY=<publishable-key> \
  --build-env NEXT_PUBLIC_API_URL=<backend-url> \
  --env NEXT_PUBLIC_SUPABASE_URL=https://hwzptzrjqcniukwrjnrb.supabase.co \
  --env NEXT_PUBLIC_SUPABASE_ANON_KEY=<publishable-key> \
  --env NEXT_PUBLIC_API_URL=<backend-url>
```

Update backend CORS to the final frontend URL:

```bash
gcloud run services update resume-api-team \
  --region us-east1 \
  --update-env-vars FRONTEND_URL=<frontend-url>
```

## 3. Enable the Shared Team Access Code

Paste [001_enable_initial_code.sql](/Users/aham/projects/dev/resumeAndCoverLetterAutomation/supabase/sql/team_access/001_enable_initial_code.sql)
into the Supabase SQL editor. It generates a random code inside SQL, stores only
the bcrypt hash, and returns the plain code once in the result grid.

Other copy-paste admin scripts live in
[supabase/sql/team_access](/Users/aham/projects/dev/resumeAndCoverLetterAutomation/supabase/sql/team_access).

After that:

- users sign in normally with Supabase
- the app redirects them to `/access-code`
- once they enter the shared code, their profile is stamped with the current access version

## 4. Rotate the Code

Rotating the code invalidates every previously verified session until the new code is entered.

Paste [002_rotate_code.sql](/Users/aham/projects/dev/resumeAndCoverLetterAutomation/supabase/sql/team_access/002_rotate_code.sql)
into the Supabase SQL editor. It generates the new code for you and returns it once.

That is the global revoke-and-rotate path if the old code leaks.

## 5. Revoke or Restore a Single User

Paste one of these into the Supabase SQL editor after replacing the placeholder email:

- [004_block_user_by_email.sql](/Users/aham/projects/dev/resumeAndCoverLetterAutomation/supabase/sql/team_access/004_block_user_by_email.sql)
- [005_unblock_user_and_force_reverify.sql](/Users/aham/projects/dev/resumeAndCoverLetterAutomation/supabase/sql/team_access/005_unblock_user_and_force_reverify.sql)
- [006_force_reverify_user_by_email.sql](/Users/aham/projects/dev/resumeAndCoverLetterAutomation/supabase/sql/team_access/006_force_reverify_user_by_email.sql)

For global shutdown without rotating, use
[003_disable_gate.sql](/Users/aham/projects/dev/resumeAndCoverLetterAutomation/supabase/sql/team_access/003_disable_gate.sql).

## 6. Notes

- The frontend requires `NEXT_PUBLIC_*` values at both build time and runtime.
- If the backend URL changes, redeploy the Vercel frontend so the public client bundle picks up the new API URL.
- The backend gate is enforced server-side, so a user with only a valid Supabase JWT still cannot call protected API routes until their access-code version matches the current version.
- For a longer-lived environment, move backend secrets to Secret Manager and swap `--set-env-vars` for `--set-secrets`.
