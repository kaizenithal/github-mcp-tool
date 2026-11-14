# github-mcp

`gh_mcp.py` lets a Claude Code cloud session read this repo, commit to branches, open pull requests and check CI. It uses the owner's own GitHub token and does not need the Claude GitHub App.

## Why it exists

In a Claude Code cloud session, every request to `github.com` passes through a proxy, and that proxy only serves repos attached with the Claude GitHub App. A token in `GH_TOKEN` doesn't get past it. GitHub's hosted MCP server is on a different host, `api.githubcopilot.com`, and accepts the same token directly. This script is a small command-line client for that server. It uses only the Python standard library and sends requests with `curl`, so the session's proxy settings apply.

## Requirements (cloud environment settings)

| Setting | Value |
|---|---|
| Environment variable | `GH_TOKEN`: a fine-grained token for this repo |
| Allowed host | `api.githubcopilot.com` |
| Token permissions | Contents: read and write · Pull requests: read and write · Commit statuses: read · Actions: read |

Add "Workflows: read and write" only if a session needs to edit `.github/workflows/`.

## Starting a new session

A new session doesn't have this repo, so it can't read this file yet. Paste this as the first message of the chat:

```
Bootstrap GitHub access: run the one-liner in tools/github-mcp/README.md of
kaizenithal/universe-godot (shown below), then read that README and follow its workflow.

mkdir -p ~/gh-mcp && curl -sS https://api.githubcopilot.com/mcp/ -H "Authorization: Bearer $GH_TOKEN" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_file_contents","arguments":{"owner":"kaizenithal","repo":"universe-godot","path":"tools/github-mcp/gh_mcp.py"}}}' | sed -n 's/^data: //p' | python3 -c 'import sys,json; c=json.load(sys.stdin)["result"]["content"]; print(next(x["resource"]["text"] for x in c if "resource" in x), end="")' > ~/gh-mcp/gh_mcp.py && python3 ~/gh-mcp/gh_mcp.py cat tools/github-mcp/README.md
```

The one-liner downloads `gh_mcp.py` to `~/gh-mcp/` and prints this README.

## Commands

The examples below write `gh` for `python3 ~/gh-mcp/gh_mcp.py`. The default repo is `kaizenithal/universe-godot`; change it with `--repo owner/name` or `GH_REPO`.

| Task | Command |
|---|---|
| List a folder | `gh ls Universe.Sim` |
| List every file below a folder | `gh ls -r Universe.Sim` (skips `bin`, `obj`, `.godot`, `.idea` unless `--all`) |
| Print a file | `gh cat Universe.sln` |
| Copy files into a work folder | `gh pull Universe.sln Universe.Sim Universe.Sim.Tests -o ~/work` (add `--missing-only` to resume) |
| Create a branch | `gh branch claude/my-change --base main` |
| Commit files (one commit) | `gh push -b claude/my-change --root ~/work -F msg.txt path/a.cs path/b.cs` |
| Delete files | `gh rm -b claude/my-change -m "Remove {path}" --from-file list.txt` |
| Open a pull request | `gh pr --title "..." --head claude/my-change --body-file body.md` |
| Recent CI runs | `gh runs -n 5` |
| Failed CI job logs | `gh logs <run id>` |
| Any server tool | `gh tools` · `gh call <tool> '<json args>'` |

Every read accepts `--ref <branch or sha>`.

## Workflow for a change

1. Pull what the change needs from the latest `main` into a work folder, then `git init` and commit it there, so `git diff` shows exactly what changed.
2. Install the toolchain (see the root README or the handoff doc), then build and run the tests: `dotnet test Universe.Sim.Tests`.
3. Create a `claude/...` branch from the latest `main`. A branch cut from an older `main` runs CI against old code.
4. Push the changed files in one commit, then open the pull request. Its description says what was run, what wasn't, and any design choice for the owner.
5. Check `gh runs` until CI on the branch is green before calling the PR ready.
6. The owner merges with **Squash and merge**.

## Limits

- **No `git clone` or `git push`.** Every read and commit is a GitHub API call. Pull only the folders a change needs.
- **Deletions take one commit per file**, so large deletions are slow and noisy. That's why squash merging matters.
- **`push` sends text only.** Binary files such as images can't be committed this way.
- **Files over 1 MB come through a download link.** The MCP server doesn't return them inline; it gives a short-lived link on `raw.githubusercontent.com`. `pull` and `cat` follow it and check the file against its git SHA. Today that's the two Drone atlases in `Universe.Game/Assets/v3/atlas/`. If a file can't be fetched, `pull` skips it, lists it at the end and exits with an error.
- **The token is only as safe as the environment.** Anyone who can start a session in that environment can read `GH_TOKEN`. Keep the token limited to the repos in use and give it an expiry date.
