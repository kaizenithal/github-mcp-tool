# github-mcp-tool

`gh_mcp.py` lets a Claude Code cloud session work on a GitHub repo with your own token: read files, commit to branches, open pull requests and check CI. It does not need the Claude GitHub App. It is one Python file with no dependencies, and it is not tied to any project.

## Why it exists

In a Claude Code cloud session, every request to `github.com` passes through a proxy that only serves private repos attached with the Claude GitHub App. A token in `GH_TOKEN` doesn't get past it. GitHub's hosted MCP server is on a different host, `api.githubcopilot.com`, and accepts the same token directly. This script is a small command-line client for that server. It sends requests with `curl`, so the session's proxy settings apply.

## Set up a project

Do this once per project, in the cloud environment that project's sessions use.

| Setting | Value |
|---|---|
| Environment variable | `GH_TOKEN`: a fine-grained token limited to that project's repo |
| Allowed hosts | `api.githubcopilot.com`, and `github.com` to fetch this tool |
| Token permissions | Contents: read and write · Pull requests: read and write · Commit statuses: read · Actions: read |

- Add "Workflows: read and write" only if a session needs to edit `.github/workflows/`.
- **One environment and one token per project.** Anyone who can start a session in an environment can read its `GH_TOKEN`, and a session can write to every repo the token covers. A token shared between projects lets a mistake in one reach the others.
- Give the token an expiry date.
- Add a `HANDOFF.md` to the project's repo. [`HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md) is a starting point.

## Start a session

A new session has no copy of your repo and no memory of earlier chats. Paste this as the first message, with your repo in place of `OWNER/NAME`:

```
Set up GitHub access for OWNER/NAME with the commands below. They print HANDOFF.md: follow its
"Start here" steps, then tell me what state you found before changing anything.

git clone --depth 1 https://github.com/kaizenithal/github-mcp-tool ~/gh-mcp
python3 ~/gh-mcp/gh_mcp.py use OWNER/NAME
python3 ~/gh-mcp/gh_mcp.py cat HANDOFF.md
```

Add what you want done after the pasted text.

- `use` saves the repo in `~/.gh-mcp-repo` and checks the token can read it. Every later command acts on that repo.
- This tool repo is public, so the clone needs no token.
- To run a version you have reviewed, add `--branch TAG` to the clone, with a tag you created on this repo.

## Choosing the repo

There is no built-in default, so the tool never guesses which repo to write to. In order:

1. `--repo OWNER/NAME` on the command, before the subcommand.
2. The `GH_REPO` environment variable.
3. The repo saved by `use`.

`gh_mcp.py which` prints the repo commands will act on. With none chosen, every command stops with an error.

## Commands

The examples write `gh` for `python3 ~/gh-mcp/gh_mcp.py`.

| Task | Command |
|---|---|
| Choose the repo | `gh use OWNER/NAME` |
| Show the chosen repo | `gh which` |
| List a folder | `gh ls src` |
| List every file below a folder | `gh ls -r src` |
| Print a file | `gh cat README.md` |
| Copy files into a work folder | `gh pull src tests README.md -o ~/work` (add `--missing-only` to resume) |
| Create a branch | `gh branch claude/my-change --base main` |
| Commit files (one commit) | `gh push -b claude/my-change --root ~/work -F msg.txt src/a.py src/b.py` |
| Delete files | `gh rm -b claude/my-change -m "Remove {path}" --from-file list.txt` |
| Open a pull request | `gh pr --title "..." --head claude/my-change --body-file body.md` |
| Recent CI runs | `gh runs -n 5` |
| Failed CI job logs | `gh logs <run id>` |
| Any server tool | `gh tools` · `gh call <tool> '<json args>'` |

Every read accepts `--ref <branch or sha>`. `branch` and `pr` assume the base branch is `main`; pass `--base` if yours differs.

### Leaving folders out

`ls -r` and `pull` skip nothing by default. To leave out folders by name, pass `--skip node_modules,dist` or set `GH_SKIP_DIRS=node_modules,dist`. `--all` ignores both. Folders in the repo's `.gitignore` are not in the repo, so they never need skipping.

## Workflow for a change

1. Pull what the change needs from the latest `main` into a work folder, then `git init` and commit it there, so `git diff` shows exactly what changed.
2. Build and run the project's tests, as its `HANDOFF.md` describes.
3. Create a `claude/...` branch from the latest `main`. A branch cut from an older `main` runs CI against old code.
4. Push the changed files in one commit, then open the pull request. Its description says what was run and what wasn't.
5. Check `gh runs` until CI on the branch has passed before calling the pull request ready.
6. Merge with **Squash and merge**.

## Limits

- **No `git clone` or `git push` of the project repo.** Every read and commit is a GitHub API call. Pull only the folders a change needs.
- **Deletions take one commit per file**, so large deletions are slow and noisy. That's why squash merging matters.
- **`push` sends text only.** Files must be UTF-8 text; images and other binary files can't be committed this way.
- **Files over 1 MB come through a download link.** The MCP server doesn't return them inline; it gives a short-lived link on `raw.githubusercontent.com`. `pull` and `cat` follow it and check the file against its git SHA. If a file can't be fetched, `pull` skips it, lists it at the end and exits with an error.
- **No tags or releases.** Create those on GitHub.
- **It depends on GitHub's hosted MCP server.** If GitHub changes that server's tools, this script needs updating.
