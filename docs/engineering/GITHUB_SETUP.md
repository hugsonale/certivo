# GitHub settings to apply by hand

These are settings that live on github.com, not in the repo, so they cannot be shipped as files. GitHub's menus change from time to time; if a name differs slightly, look for the closest match.

## 1. Merge settings

1. Open the repo on GitHub, then **Settings** and **General**.
2. Scroll to **Pull Requests**.
3. Tick **Allow squash merging**. Untick **Allow merge commits** and **Allow rebase merging**.
4. Tick **Automatically delete head branches**.

## 2. Labels

The `labels` workflow creates the 33 labels from `.github/labels.json` on the first push of that file. Check under **Issues**, then **Labels**. If they are missing, open the **Actions** tab, choose **labels**, and read the error. Existing labels that are not in the file are left alone.

## 3. Branch protection

Goal: nobody (including you) can push straight to `main` or `rebuild`, force-push, or delete them, and nothing merges until the checks pass.

**Check your plan first.** On GitHub's Free plan, branch protection and rulesets are generally not available on private repositories; GitHub shows an upgrade prompt. If you see that prompt:

- **Option A: pay for a plan that supports it.** Check GitHub's current pricing page. Some reports say private repos owned by a *personal* account can still show a "not enforced" notice on Pro, in which case an organisation on the Team plan is what enforces it. Read the notice on the settings page before paying.
- **Option B: keep the repo private and rely on discipline for now.** The checks still run on every pull request; they just cannot be made mandatory by GitHub. The rule is: never push directly to `main` or `rebuild`; always open a pull request and wait for green.
- **Option C: make the repo public.** Not recommended while the specification documents are marked confidential.

If your plan supports it:

1. **Settings**, then **Rules**, then **Rulesets**, then **New ruleset**, then **New branch ruleset**.
2. Name it `protect-trunk`. Set **Enforcement status** to **Active**.
3. Under **Target branches**, add `main` and `rebuild` (use "Add target", then "Include by pattern").
4. Tick: **Restrict deletions**, **Block force pushes**, **Require a pull request before merging** (set required approvals to **0**, since you work alone), and **Require status checks to pass**.
5. In the status checks box, add the checks from the table below. A check only appears in the search box after it has run at least once, so open the first pull request and let it run before this step.
6. Save.

## 4. Required status checks

| Check name (exactly as shown on the PR) | Workflow |
|---|---|
| Test and lint (platform) | platform-ci |
| Tests and migration check on Postgres | platform-ci |
| Docker compose smoke test | platform-ci |
| PR title is a Conventional Commit | governance |
| Secret scan (gitleaks) | security-scan |
| Dependency audit (pip-audit) | security-scan |
| Dependency audit (npm) | security-scan |

"PR names a build step (warning only)" is deliberately **not** required.

## 5. Dependabot

Under **Settings**, then **Code security** (or **Advanced Security**), turn on **Dependabot alerts** and **Dependabot security updates**. The `.github/dependabot.yml` file handles weekly version updates. Dependabot only reads that file from the repository's **default branch**. If your default branch is `main` and these files are only on `rebuild`, it will not start until they reach `main`. To start it sooner, set `rebuild` as the default branch under **Settings**, then **General**, then **Default branch**.

## 6. What the secret scan does and does not do

GitHub's own secret scanning and push protection need a paid add-on on private repositories. Our `gitleaks` check in CI is the replacement. Today it scans only the commits in each pull request (and the current files on pushes), because the old history still contains an exposed `.env`. After that history is purged, change the scan to cover the full history (see the TODO in `.github/workflows/security-scan.yml`).

## 7. Scheduled runs

The weekly security scan (`schedule:`) only runs from the repository's default branch. It starts working once these workflow files are on `main`.
