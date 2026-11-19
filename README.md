# github-mcp-tool

`gh_mcp.py` lets a Claude Code cloud session work on a GitHub repo with your own token: copy the repo, keep the copy up to date, commit to branches, open pull requests and check CI. It does not need the Claude GitHub App. It is one Python file with no dependencies, and it is not tied to any project.

## Why it exists

In a Claude Code cloud session, every request to `github.com` passes through a proxy that only serves private repos attached with the Claude GitHub App. A token in `GH_TOKEN` doesn't get past it. Two other GitHub hosts accept the token directly, and this script uses both:

- `api.githubcopilot.com`, GitHub's hosted MCP server, for everything that changes or describes the repo: listings, commits, branches, pull requests, CI.
- `raw.githubusercontent.com` for the contents of files.

It sends requests with `curl`, so the session's proxy settings apply.

## Requests and the hourly allowance

GitHub allows each account a fixed number of API requests an hour. Every request to the MCP server counts, and **every session using your token draws on the same allowance**, along with anything else you run under your account. When it is used up, GitHub refuses every session until the hour turns over. Downloads from `raw.githubusercontent.com` do not count.

So the tool is built to make few requests, and a session should use it the same way:

| Command | API requests |
|---|---|
| `clone` | 2, whatever the size of the repo |
| `sync` | 1 if nothing changed, 2 if something did |
| `pull` | 2, whatever the number of files |
| `ls -r` | 2 |
| `cat`, `status` | 0 |
| `ls` | 1 per folder named |
| `use`, `branch`, `pr`, `runs`, `logs`, `call`, `tools` | 1 each |
| `push` | 1 for the whole commit |
| `rm` | 1 per file |

- Work from the folder `clone` made, and run `sync` to bring it up to date. Do not fetch files one at a time.
- Look at CI once after pushing and once when it should have finished. Do not poll it.
- When a command reports that the rate limit is exceeded, stop and wait for the time it gives. Retrying spends more of the same allowance. Building and testing locally needs no requests.

## Set up a project

Do this once per project, in the cloud environment that project's sessions use.

| Setting | Value |
|---|---|
| Environment variable | `GH_TOKEN`: a fine-grained token limited to that project's repo |
| Allowed hosts | `api.githubcopilot.com` and `raw.githubusercontent.com`, and `github.com` to fetch this tool |
| Token permissions | Contents: read and write · Pull requests: read and write · Commit statuses: read · Actions: read |

- Add "Workflows: read and write" only if a session needs to edit `.github/workflows/`.
- **One environment and one token per project.** Anyone who can start a session in an environment can read its `GH_TOKEN`, and a session can write to every repo the token covers. A token shared between projects lets a mistake in one reach the others.
- Give the token an expiry date.
- Add a `HANDOFF.md` to the project's repo. [`HANDOFF_TEMPLATE.md`](HANDOFF_TEMPLATE.md) is a starting point.

## Start a session

A new session has no copy of your repo and no memory of earlier chats. Paste this as the first message, with your repo in place of `OWNER/NAME`:

```
Set up GitHub access for OWNER/NAME with the commands below. They copy the repo into ~/work/NAME.
Then read HANDOFF.md there, follow its "Start here" steps, and tell me what state you found before
changing anything.

git clone --depth 1 https://github.com/kaizenithal/github-mcp-tool ~/gh-mcp
python3 ~/gh-mcp/gh_mcp.py use OWNER/NAME
python3 ~/gh-mcp/gh_mcp.py clone
```

Add what you want done after the pasted text.

- `use` saves the repo in `~/.gh-mcp-repo` and checks the token can read it. Every later command acts on that repo.
- `clone` copies every file on the repo's default branch into `~/work/NAME` and commits it to a local git repository there, so `git status` and `git diff` show what the session changes. A few hundred files take seconds. That repository has no remote and is never pushed.
- This tool repo is public, so fetching it needs no token.
- To run a version you have reviewed, add `--branch TAG` to the `git clone`, with a tag you created on this repo.

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
| Copy the whole repo into a work folder | `gh clone` (or `gh clone ~/somewhere --branch dev`) |
| Bring that folder up to date | `gh sync` |
| List what the folder has changed | `gh status` |
| List a folder | `gh ls src` |
| List every file below a folder | `gh ls -r src` |
| Print a file | `gh cat README.md` |
| Copy some files or folders | `gh pull src tests README.md -o ~/elsewhere` |
| Create a branch | `gh branch claude/my-change --base main` |
| Commit files (one commit) | `gh push -b claude/my-change --root ~/work/NAME -F msg.txt src/a.py src/b.py` |
| Delete files | `gh rm -b claude/my-change -m "Remove {path}" --from-file list.txt` |
| Open a pull request | `gh pr --title "..." --head claude/my-change --body-file body.md` |
| Recent CI runs | `gh runs -n 5` |
| Failed CI job logs | `gh logs <run id>` |
| Any server tool | `gh tools` · `gh call <tool> '<json args>'` |

`ls`, `cat` and `pull` accept `--ref <branch or sha>` and read the repo's default branch without it. `clone` takes `--branch`. `branch` and `pr` assume the base branch is `main`; pass `--base` if yours differs.

### `clone`, `sync` and `status`

`clone` is for the folder a session works in. `sync` brings it up to date with its branch by comparing checksums and fetching only the files that differ, so it takes seconds. `status` lists what the folder has changed since it last matched the branch: `A` added, `M` modified, `D` deleted. Those are the files a `push` needs to name, and the ones an `rm` needs to delete.

- Run `sync` before cutting each branch, and again before opening a pull request if the work took a while. Other sessions and the owner merge while you work, and a copy does not follow them by itself.
- `sync` refuses to run while there are uncommitted changes, because it overwrites files. Commit locally first; the local repository goes nowhere.
- If the branch changed a file the session had also changed, that file ends up holding the branch's version. `sync` prints `ATTENTION` with each such file and the `git diff` command that shows the session's version, which is still in the local history. Put the change back by hand.
- A `clone` that is interrupted can be run again; it fetches only what is missing.
- `sync` copes with a folder that is already part of the way there: a file the branch deleted that the session had deleted too, a file the session already holds in the branch's new form, a file the branch turned into a folder or a folder into a file. If anything fails after it has started changing files, it puts the folder back as it was, so it can simply be run again.
- `status` leaves out files the repo's `.gitignore` ignores, as `git status` does. It reads only the work folder, so it costs nothing.
- The local repository holds exactly the repo's files, including any that the repo's own `.gitignore` would leave out, so a change to one of those still shows in `git diff`.

### `pull`

`pull` copies named files or folders anywhere, without a local repository. Use it for a look at another branch (`--ref`), not for the folder you work in. Files that are already there and identical are left alone. `--missing-only` also leaves alone files that differ.

### Leaving folders out

`ls -r` and `pull` skip nothing by default. To leave out folders by name, pass `--skip node_modules,dist` or set `GH_SKIP_DIRS=node_modules,dist`. `--all` ignores both. `clone` always copies everything. Folders in the repo's `.gitignore` are not in the repo, so they never need skipping.

## Workflow for a change

1. `gh sync`, so the work folder matches the latest `main`.
2. Make the change. Build and run the project's tests, as its `HANDOFF.md` describes.
3. Create a `claude/...` branch from `main`. A branch cut from an older `main` runs CI against old code.
4. Push the changed files in one commit, then open the pull request. `gh status` lists them. Leave out anything the project generates per machine. The description says what was run and what wasn't.
5. Check `gh runs` once CI on the branch has had time to finish, before calling the pull request ready.
6. Merge with **Squash and merge**.

## Testing the tool

`bash tests/sync_scenarios.sh` runs `clone`, `sync` and `status` through a dozen situations against a stand-in for GitHub (`tests/mock_github.py`): a folder on disk plays the branch. It needs no token and makes no requests. Run it after changing anything in `clone`, `sync`, `status` or the way files are written.

## Limits

- **No `git clone` or `git push` of the project repo.** Reads and commits go through the two hosts above. The work folder's git repository is local only.
- **Deletions take one commit and one request per file**, so large deletions are slow and noisy. That's why squash merging matters.
- **`push` sends text only.** Files must be UTF-8 text; images and other binary files can't be committed this way. Line endings are sent as they are.
- **`push` commits ordinary files.** The server gives every file it commits the plain file mode, so a script pushed this way is not marked executable on GitHub, and a symbolic link becomes a file. Set those on GitHub or from a real clone.
- **`push` adds and changes files; it does not delete.** Delete with `rm`.
- **Submodules are not copied.** They are other repos.
- **Every download is checked** against the file's git checksum and retried if it does not match. If a file can't be fetched, the command lists it and exits with an error.
- **Very large repos.** GitHub cuts a listing short above about 100,000 files. The tool reports that instead of copying part of a repo.
- **No tags or releases.** Create those on GitHub.
- **It depends on GitHub's hosted MCP server and on `raw.githubusercontent.com` accepting the token.** If GitHub changes either, this script needs updating.
