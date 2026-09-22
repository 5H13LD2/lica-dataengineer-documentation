# AGENTS.md - Gulong Chatbot Runtime

## Deployment Restrictions

- Do not bypass the normal Cloud Build trigger pipeline for staging or live
  deploys unless the user explicitly forces a manual deploy path.
- Staging deploys must come from the staging branch. Live deploys must come from
  the live branch. Feature branches should be merged or pushed into the target
  release branch and deployed by the configured trigger.
- Manual `gcloud run deploy`, direct image promotion, or traffic movement from a
  feature-branch build is an anti-pattern for this repo unless explicitly
  approved for an emergency.
- When a deploy is requested, verify the deployed revision, `git_sha` or
  `release_version`, and Cloud Run traffic after the trigger completes.
