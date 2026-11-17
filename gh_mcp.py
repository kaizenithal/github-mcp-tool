#!/usr/bin/env python3
"""Work with a GitHub repo through GitHub's hosted MCP server, using your own token.

Built for Claude Code cloud sessions, where github.com goes through a proxy that only
serves repos attached with the Claude GitHub App. GitHub's MCP server lives on a different
host (api.githubcopilot.com), so a personal access token in GH_TOKEN reaches the repo there.

GitHub counts every request to that server against the token owner's hourly allowance, which
all sessions using the token share. So this tool asks the server only for what nothing else
can give it: listings, commits, branches, pull requests, CI. File contents come from
raw.githubusercontent.com, which takes the same token and does not count against the allowance.

The tool has no default repo. Name one with --repo, with $GH_REPO, or once per session with
`gh_mcp.py use OWNER/NAME`, which saves it in ~/.gh-mcp-repo.

Standard library only; HTTP goes through curl so the session's proxy settings apply.
See README.md next to this file for setup, commands and limits.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse

ENDPOINT = os.environ.get("GH_MCP_URL", "https://api.githubcopilot.com/mcp/")
RAW = os.environ.get("GH_RAW_URL", "https://raw.githubusercontent.com")
REPO_FILE = os.path.expanduser("~/.gh-mcp-repo")
# Folder names `ls -r` and `pull` leave out, e.g. GH_SKIP_DIRS=node_modules,dist. Nothing is skipped by default.
SKIP_DIRS = {d.strip() for d in os.environ.get("GH_SKIP_DIRS", "").split(",") if d.strip()}
# The server toolset that has get_repository_tree, the one request that lists a whole repo.
TREE_TOOLSETS = "git"
# How many files are downloaded at once.
DOWNLOADS = 8
# Where `clone` and `sync` keep what they know about a work folder, inside its .git folder.
STATE_FILE = "gh-mcp-state.json"


class McpError(RuntimeError):
    pass


class RateLimited(McpError):
    """GitHub has stopped answering this token until its hourly allowance renews."""


def the_token():
    token = (os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        raise McpError("GH_TOKEN is not set. Add it to the cloud environment's variables.")
    return token


RATE_LIMIT_ADVICE = ("The token's hourly allowance is used up, for every session that shares it. "
                     "Wait for the time given; retrying spends more of the same allowance.")


def rpc(method, params=None, toolsets="default", timeout=120):
    token = the_token()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    # The body goes in a temporary file, not on the command line: a commit of several source files is larger
    # than the operating system allows one argument to be. The token goes to curl on stdin as a header file,
    # so it never shows in the process list.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as f:
        f.write(body)
    try:
        cmd = ["curl", "-sS", "-m", str(timeout), ENDPOINT, "-H", "@-",
               "-H", "Content-Type: application/json",
               "-H", "Accept: application/json, text/event-stream",
               "-H", f"X-MCP-Toolsets: {toolsets}", "--data-binary", f"@{f.name}",
               "-w", "\n%{http_code}"]
        try:
            proc = subprocess.run(cmd, input=f"Authorization: Bearer {token}\n", capture_output=True, text=True)
        except FileNotFoundError:
            raise McpError("curl is not installed; this tool sends every request with it.")
    finally:
        os.unlink(f.name)
    if proc.returncode != 0:
        raise McpError(f"could not reach {ENDPOINT} (curl {proc.returncode}): {proc.stderr.strip()[:300]}\n"
                       "If the host is refused, the environment's network must allow api.githubcopilot.com.")
    out, _, status = proc.stdout.rpartition("\n")
    if status == "401":
        raise McpError(f"GitHub rejected the token ({out.strip()[:120]}). It has expired, been revoked, or is not "
                       "a GitHub token. Only the owner can replace it, in the environment's variables.")
    if status == "429" or (status == "403" and "rate limit" in out.lower()):
        raise RateLimited(f"{out.strip()[:200]}\n{RATE_LIMIT_ADVICE}")
    payload = None
    for line in out.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[6:])
    if payload is None:
        try:
            payload = json.loads(out)
        except ValueError:
            raise McpError(f"unexpected response (HTTP {status}): {out[:300]}")
    if "error" in payload:
        text = json.dumps(payload["error"])[:500]
        if "rate limit" in text.lower():
            raise RateLimited(f"{text}\n{RATE_LIMIT_ADVICE}")
        raise McpError(text)
    return payload["result"]


def call(tool, args, toolsets="default"):
    """Call an MCP tool. Returns the result's content list; raises McpError if the tool failed."""
    res = rpc("tools/call", {"name": tool, "arguments": args}, toolsets)
    content = res.get("content", [])
    if res.get("isError"):
        text = " ".join(c.get("text", "") for c in content)[:500]
        if "rate limit" in text.lower():
            raise RateLimited(f"{tool}: {text}\n{RATE_LIMIT_ADVICE}")
        raise McpError(f"{tool}: {text}")
    return content


def text_json(content):
    """Parse the JSON in the first text item (some tools prefix it with a sentence)."""
    t = content[0].get("text", "")
    starts = [i for i in (t.find("["), t.find("{")) if i >= 0]
    if not starts:
        return t
    return json.JSONDecoder().raw_decode(t[min(starts):])[0]


def split_repo(repo):
    owner, _, name = (repo or "").partition("/")
    if not owner or not name or "/" in name:
        raise McpError(f"repo must be owner/name, got {repo!r}")
    return {"owner": owner, "repo": name}


def saved_repo():
    try:
        with open(REPO_FILE, encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def resolve_repo(flag):
    """--repo wins, then $GH_REPO, then the repo saved by `use`. There is deliberately no built-in default:
    a tool shared between projects must never guess which repo to write to."""
    repo = flag or os.environ.get("GH_REPO") or saved_repo()
    if not repo:
        raise McpError("no repo chosen. Run `gh_mcp.py use OWNER/NAME` once, or pass --repo OWNER/NAME, or set GH_REPO.")
    split_repo(repo)
    return repo


def skip_set(a):
    if a.all:
        return set()
    return SKIP_DIRS | {d.strip() for d in (a.skip or "").split(",") if d.strip()}


def cmd_use(a):
    split_repo(a.name)
    list_dir(a.name, "/")  # fails here, not later, if the token cannot read the repo
    with open(REPO_FILE, "w", encoding="utf-8") as fh:
        fh.write(a.name + "\n")
    print(f"using {a.name} (saved in {REPO_FILE})")


def cmd_which(a):
    print(a.repo)


# ---------- reading ----------

def api_ref(ref):
    """A branch name or commit SHA as the server's get_file_contents wants it."""
    return ref if ref.startswith("refs/") or len(ref) == 40 else f"refs/heads/{ref}"


def list_dir(repo, path, ref=None):
    """One folder's entries. One API request."""
    args = {**split_repo(repo), "path": path or "/"}
    if ref:
        args["ref"] = api_ref(ref)
    return text_json(call("get_file_contents", args))


def blob_sha(data):
    """The checksum git and GitHub give a file with these contents."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def raw_file(repo, ref, path, sha=None):
    """A file's contents from raw.githubusercontent.com. No API request.

    ref is a branch name, a commit SHA, or HEAD for the default branch. With sha, the download is
    checked against the file's git checksum and retried if it does not match."""
    token = the_token()
    url = f"{RAW}/{repo}/{urllib.parse.quote(ref, safe='')}/{urllib.parse.quote(path.lstrip('/'))}"
    problem = ""
    for attempt in range(3):
        if attempt:
            time.sleep(attempt)
        proc = subprocess.run(["curl", "-sS", "-f", "-m", "300", "-H", "@-", url],
                              input=f"Authorization: Bearer {token}\n".encode(), capture_output=True)
        if proc.returncode != 0:
            problem = proc.stderr.decode(errors="replace").strip()[:200]
            if "404" in problem:
                break  # not there, or not readable: trying again will not change that
            continue
        if sha and blob_sha(proc.stdout) != sha:
            problem = f"the download does not match its git checksum {sha}"
            continue
        return proc.stdout
    if "404" in problem:
        problem += (" (no such file at that ref; or the token cannot read this repo's contents; "
                    "or the network does not allow raw.githubusercontent.com)")
    raise McpError(f"{path}: {problem}")


def head_commit(repo, ref=None):
    """The SHA of the newest commit on a branch, or on the repo's default branch with no ref.
    A commit SHA comes back as itself, checked. One API request."""
    args = {**split_repo(repo), "perPage": 1}
    if ref:
        args["sha"] = ref
    commits = text_json(call("list_commits", args))
    if not isinstance(commits, list) or not commits:
        raise McpError(f"{ref or 'the default branch'}: no commits found")
    return commits[0]["sha"]


def repo_files(repo, commit):
    """Every file in the repo at a commit, as {path: {"sha", "size", "mode"}}. One API request."""
    answer = text_json(call("get_repository_tree", {**split_repo(repo), "tree_sha": commit, "recursive": True},
                            toolsets=TREE_TOOLSETS))
    entries = answer.get("tree") if isinstance(answer, dict) else answer
    if not isinstance(entries, list):
        raise McpError(f"unexpected answer listing the repo: {str(answer)[:200]}")
    if isinstance(answer, dict) and answer.get("truncated"):
        raise McpError("the repo has too many files to list in one request; GitHub cut the list short")
    files = {}
    for e in entries:
        if e.get("type") != "blob":
            continue  # folders, and submodules, which are other repos and are not copied
        parts = e["path"].split("/")
        if e["path"].startswith("/") or ".." in parts or ".git" in parts:
            raise McpError(f"refusing a path that could write outside the folder: {e['path']!r}")
        files[e["path"]] = {"sha": e.get("sha"), "size": e.get("size", 0), "mode": e.get("mode", "")}
    return files


def under(path, folder):
    """True if path is the file `folder` or lies below the folder `folder`. "" and "/" mean the whole repo."""
    folder = folder.strip("/")
    return folder in ("", ".") or path == folder or path.startswith(folder + "/")


def skipped(path, skip):
    return any(part in skip for part in path.split("/")[:-1])


def local_sha(path):
    """The git checksum of what is at a local path, or None if nothing is. A symbolic link's
    checksum is that of the path it points to, as in git."""
    try:
        if os.path.islink(path):
            return blob_sha(os.readlink(path).encode())
        with open(path, "rb") as fh:
            return blob_sha(fh.read())
    except OSError:
        return None


def write_file(dst, data, mode):
    """Put a fetched file in place: whole or not at all, with git's executable bit and links kept."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.islink(dst) or mode == "120000":
        if os.path.lexists(dst):
            os.remove(dst)
    if mode == "120000":
        os.symlink(data.decode(), dst)
        return
    tmp = f"{dst}.gh-mcp-part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o755 if mode == "100755" else 0o644)
    os.replace(tmp, dst)


def download(repo, commit, wanted, out, quiet=False):
    """Fetch files into out, several at a time. wanted is {path: entry from repo_files}.
    Returns [(path, what went wrong)] for those that could not be fetched."""
    def one(path):
        data = raw_file(repo, commit, path, wanted[path]["sha"])
        write_file(os.path.join(out, path), data, wanted[path]["mode"])

    failed, done = [], 0
    with concurrent.futures.ThreadPoolExecutor(DOWNLOADS) as pool:
        jobs = {pool.submit(one, path): path for path in wanted}
        for job in concurrent.futures.as_completed(jobs):
            done += 1
            try:
                job.result()
            except (McpError, OSError) as e:
                failed.append((jobs[job], str(e)))
            if not quiet and done % 200 == 0:
                print(f"  {done} of {len(wanted)}", flush=True)
    return sorted(failed)


def cmd_ls(a):
    if not a.recursive:
        for p in a.paths or ["/"]:
            entries = list_dir(a.repo, p, a.ref)
            if not isinstance(entries, list) or not all(isinstance(i, dict) for i in entries):
                raise McpError(f"{p} is a file, not a folder. Print it with `cat`.")
            for i in entries:
                print(f"{i['type']:<4}  {i['path']}{'/' if i['type'] == 'dir' else ''}")
        return
    skip = skip_set(a)
    files = repo_files(a.repo, head_commit(a.repo, a.ref))
    for p in a.paths or ["/"]:
        for f in sorted(files):
            if under(f, p) and not skipped(f, skip):
                print(f"{files[f]['size']:>9}  {f}")


def cmd_cat(a):
    sys.stdout.buffer.write(raw_file(a.repo, a.ref or "HEAD", a.path))


def cmd_pull(a):
    """Copy files or folders from the repo into a local directory, keeping their paths."""
    out = os.path.abspath(a.out)
    skip = skip_set(a)
    commit = head_commit(a.repo, a.ref)
    files = repo_files(a.repo, commit)
    wanted, unknown = {}, []
    for p in a.paths:
        found = {f: e for f, e in files.items() if under(f, p) and not skipped(f, skip)}
        if not found:
            unknown.append(p)
        wanted.update(found)
    # A file already there is left alone if it is identical, or with --missing-only whatever it holds.
    fetch = {f: e for f, e in wanted.items()
             if not (os.path.exists(os.path.join(out, f)) if a.missing_only
                     else local_sha(os.path.join(out, f)) == e["sha"])}
    failed = download(a.repo, commit, fetch, out)
    print(f"pulled {len(fetch) - len(failed)} files into {out} ({len(wanted) - len(fetch)} already there)")
    for p in unknown:
        print(f"NOT IN THE REPO at {commit[:10]}: {p}", file=sys.stderr)
    for f, err in failed:
        print(f"NOT PULLED {f}: {err[:160]}", file=sys.stderr)
    if failed or unknown:
        sys.exit(1)


# ---------- a work folder that follows main ----------

def git(work, *args):
    return subprocess.run(["git", "-C", work, *args], capture_output=True, text=True)


def local_commit(work, message, paths):
    """Commit these paths (present or deleted) to the local repository, and nothing else.

    Paths are named one by one and forced, because a repo can hold files its own .gitignore
    would leave out; they must be in the baseline or their changes would never show."""
    listed = "\0".join(paths)
    for args in (["add", "-f", "-A", "--pathspec-from-file=-", "--pathspec-file-nul"],
                 ["-c", "user.name=gh-mcp", "-c", "user.email=gh-mcp@localhost", "commit", "-q", "--allow-empty",
                  "-m", message, "--pathspec-from-file=-", "--pathspec-file-nul"]):
        # Literal: a path may contain characters such as "[" that git would otherwise read as a pattern.
        done = subprocess.run(["git", "--literal-pathspecs", "-C", work, *args],
                              input=listed, capture_output=True, text=True)
        if done.returncode != 0:
            raise McpError(f"git {args[0]} failed in {work}: {done.stderr.strip()[:300]}")


def work_folder(a):
    return os.path.abspath(a.dir or os.path.expanduser("~/work/" + a.repo.split("/")[1]))


def state_path(work):
    return os.path.join(work, ".git", STATE_FILE)


def save_state(work, repo, branch, commit, files):
    """Record which commit the folder matches and each file's checksum and mode in it."""
    with open(state_path(work), "w", encoding="utf-8") as fh:
        json.dump({"repo": repo, "branch": branch, "commit": commit,
                   "files": {p: [e["sha"], e["mode"]] for p, e in files.items()}}, fh)


def load_state(work, repo):
    try:
        with open(state_path(work), encoding="utf-8") as fh:
            state = json.load(fh)
    except OSError:
        raise McpError(f"{work} was not made by `clone`.")
    if state["repo"] != repo:
        raise McpError(f"{work} is a copy of {state['repo']}, but the chosen repo is {repo}.")
    return state


def cmd_clone(a):
    """Copy the whole repo into a work folder and make it a local git repository.

    The local repository exists so that `git status` and `git diff` show what the session has
    changed. It has no remote and is never pushed; changes go to GitHub with `push`."""
    work = work_folder(a)
    if os.path.exists(state_path(work)):
        raise McpError(f"{work} is already a copy of a repo. Use `sync` to bring it up to date.")
    if os.path.isdir(os.path.join(work, ".git")):
        raise McpError(f"{work} already holds a git repository that this tool did not make. Choose another folder.")
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        raise McpError("git is not installed; `clone` uses it for the local baseline.")
    commit = head_commit(a.repo, a.branch)
    files = repo_files(a.repo, commit)
    name = a.branch or "the default branch"
    # After an interrupted run, files already fetched and intact are not fetched again.
    fetch = {f: e for f, e in files.items() if local_sha(os.path.join(work, f)) != e["sha"]}
    print(f"{len(files)} files in {a.repo} on {name} at {commit[:10]}; fetching {len(fetch)}.", flush=True)
    os.makedirs(work, exist_ok=True)
    failed = download(a.repo, commit, fetch, work)
    for f, err in failed:
        print(f"NOT FETCHED {f}: {err[:160]}", file=sys.stderr)
    if failed:
        raise McpError(f"{len(failed)} file(s) could not be fetched. Run the same command again; it carries on.")
    git(work, "init", "-q")
    # Line endings stay exactly as they are in the repo, so checksums keep matching.
    git(work, "config", "core.autocrlf", "false")
    local_commit(work, f"baseline: {a.repo} {name} at {commit[:10]}", sorted(files))
    save_state(work, a.repo, a.branch, commit, files)
    print(f"All {len(files)} files are in {work}, committed locally as a baseline.")
    print("That repository is local only: it has no remote. Send changes with `push`.")


def cmd_sync(a):
    """Bring a work folder made by `clone` up to date with its branch.

    Fetches only the files that changed on the branch since the folder last matched it. A file the
    session has also changed ends up holding the branch's version; each such file is listed, with
    the command that shows the session's version, which stays in the local history."""
    work = work_folder(a)
    state = load_state(work, a.repo)
    branch, last = state["branch"], state["commit"]
    name = branch or "the default branch"
    then = {p: tuple(v) for p, v in state["files"].items()}  # path: (checksum, mode)
    commit = head_commit(a.repo, branch)
    if commit == last:
        print(f"Already in step with {name} ({commit[:10]}).")
        return
    if git(work, "status", "--porcelain").stdout.strip():
        raise McpError("there are uncommitted changes in the work folder, and sync overwrites files. "
                       "Commit them locally first (git add -A && git commit -m wip), then sync.")

    now = repo_files(a.repo, commit)
    changed = {p: e for p, e in now.items() if then.get(p) != (e["sha"], e["mode"])}
    removed = sorted(set(then) - set(now))
    # What the session holds now, to tell its changes from the branch's.
    mine = {}
    for line in git(work, "ls-tree", "-r", "-z", "HEAD").stdout.split("\0"):
        if line:
            meta, path = line.split("\t", 1)
            mine[path] = meta.split()[2]
    before = git(work, "rev-parse", "HEAD").stdout.strip()
    yours = {p for p in set(mine) | set(then) if mine.get(p) != then.get(p, (None,))[0]}
    # Where both made the same change there is nothing to put back.
    both = sorted(p for p in yours & (set(changed) | set(removed)) if mine.get(p) != now.get(p, {}).get("sha"))

    print(f"{name} moved from {last[:10]} to {commit[:10]}: {len(changed)} file(s) to fetch, {len(removed)} to remove.")
    failed = download(a.repo, commit, changed, work, quiet=True)
    if failed:
        git(work, "checkout", "--", ".")
        git(work, "clean", "-fdq")
        for f, err in failed:
            print(f"NOT FETCHED {f}: {err[:160]}", file=sys.stderr)
        raise McpError(f"{len(failed)} file(s) could not be fetched; the folder was put back as it was. Try again.")
    for p in removed:
        if os.path.lexists(os.path.join(work, p)):
            os.remove(os.path.join(work, p))
    for p in sorted(changed):
        print(f"  fetched {p}")
    for p in removed:
        print(f"  removed {p}")
    local_commit(work, f"sync: {name} at {commit[:10]}", sorted(changed) + removed)
    save_state(work, a.repo, branch, commit, now)
    print(f"In step with {name} at {commit[:10]}.")
    if both:
        print(f"\nATTENTION: {name} also changed {len(both)} file(s) that you had changed. They now hold the")
        print("branch's version, and your changes to them are NOT in the work folder any more. Your version of")
        print(f"each is still in your local commit {before[:10]}. Compare, and put your change back by hand:")
        for p in both:
            print(f"    git diff {before[:10]} HEAD -- '{p}'")
    elif yours:
        print("None of the files you have changed were touched on the branch. Your changes are intact.")


def cmd_status(a):
    """What differs between a work folder and the branch commit it was last in step with: the files
    a `push` would need to send, and those an `rm` would need to delete. No API request."""
    work = work_folder(a)
    state = load_state(work, a.repo)
    then = {p: v[0] for p, v in state["files"].items()}
    # Every file git would consider: tracked, or untracked and not ignored.
    listed = git(work, "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout.split("\0")
    here = {p for p in listed if p and os.path.lexists(os.path.join(work, p))}
    added = sorted(here - set(then))
    modified = sorted(p for p in here & set(then) if local_sha(os.path.join(work, p)) != then[p])
    deleted = sorted(p for p in then if not os.path.lexists(os.path.join(work, p)))
    for mark, paths in (("A", added), ("M", modified), ("D", deleted)):
        for p in paths:
            print(f"{mark}  {p}")
    if not (added or modified or deleted):
        print(f"Nothing differs from {state['branch'] or 'the default branch'} at {state['commit'][:10]}.")


# ---------- writing ----------

def cmd_branch(a):
    call("create_branch", {**split_repo(a.repo), "branch": a.name, "from_branch": a.base})
    print(f"created {a.name} from {a.base}")


def read_message(a):
    if a.message_file:
        try:
            with open(a.message_file, encoding="utf-8") as fh:
                return fh.read()
        except OSError as e:
            raise McpError(f"{a.message_file}: {e.strerror}")
    if not a.message:
        raise McpError("give -m MESSAGE or -F FILE")
    return a.message


def cmd_push(a):
    """Commit local files (paths relative to --root) to a branch in ONE commit."""
    root = os.path.abspath(a.root)
    files = []
    for p in a.files:
        full = os.path.abspath(os.path.join(root, p))
        rel = os.path.relpath(full, root).replace(os.sep, "/")
        if rel.startswith("../"):
            raise McpError(f"{p} is outside --root {root}")
        if os.path.isdir(full):
            raise McpError(f"{p} is a folder. Name the files; `status` lists what has changed.")
        try:
            # newline="" keeps each file's own line endings; the default would turn CRLF into LF.
            with open(full, encoding="utf-8", newline="") as fh:
                files.append({"path": rel, "content": fh.read()})
        except UnicodeDecodeError:
            raise McpError(f"{p} is not UTF-8 text. `push` sends text only; binary files must be committed another way.")
        except OSError as e:
            raise McpError(f"{p}: {e.strerror}. To delete a file on the branch, use `rm`.")
    call("push_files", {**split_repo(a.repo), "branch": a.branch, "message": read_message(a), "files": files})
    print(f"committed {len(files)} file(s) to {a.branch}")


def cmd_rm(a):
    """Delete files on a branch. GitHub's API makes one commit per deleted file."""
    paths = list(a.paths)
    if a.from_file:
        with open(a.from_file, encoding="utf-8") as fh:
            paths += [l.strip() for l in fh if l.strip()]
    msg = read_message(a)
    failed = []
    for i, p in enumerate(paths, 1):
        for attempt in range(4):
            try:
                call("delete_file", {**split_repo(a.repo), "branch": a.branch, "path": p,
                                     "message": msg.replace("{path}", p)})
                break
            except RateLimited:
                raise  # retrying would only spend more of the allowance
            except McpError as e:
                err = str(e)
                time.sleep(5 * (attempt + 1))
        else:
            failed.append((p, err))
        if i % 20 == 0 or i == len(paths):
            print(f"{i}/{len(paths)} deleted, {len(failed)} failed", flush=True)
        time.sleep(0.5)
    for p, err in failed:
        print(f"FAILED {p}: {err}", file=sys.stderr)
    sys.exit(1 if failed else 0)


def cmd_pr(a):
    try:
        with open(a.body_file, encoding="utf-8") as fh:
            body = fh.read()
    except OSError as e:
        raise McpError(f"{a.body_file}: {e.strerror}")
    res = text_json(call("create_pull_request", {**split_repo(a.repo), "title": a.title, "head": a.head,
                                                 "base": a.base, "body": body}))
    print(res.get("url", res) if isinstance(res, dict) else res)


# ---------- CI ----------

def cmd_runs(a):
    args = {**split_repo(a.repo), "method": "list_workflow_runs", "perPage": a.limit}
    d = text_json(call("actions_list", args, toolsets="default,actions"))
    for w in d.get("workflow_runs", []):
        print(f"{w['id']}  {w['event']:<13} {w.get('head_branch') or '':<32} {w['head_sha'][:8]}  "
              f"{w['status']:<11} {w.get('conclusion') or '-'}")


def cmd_logs(a):
    content = call("get_job_logs", {**split_repo(a.repo), "run_id": a.run_id, "failed_only": True,
                                    "return_content": True, "tail_lines": a.tail}, toolsets="default,actions")
    for c in content:
        print(c.get("text", "").replace("\\n", "\n"))


# ---------- raw ----------

def cmd_tools(a):
    for t in rpc("tools/list", toolsets=a.toolsets)["tools"]:
        print(t["name"])


def cmd_call(a):
    try:
        args = json.loads(a.args)
    except ValueError as e:
        raise McpError(f"the arguments are not valid JSON: {e}")
    content = call(a.tool, args, toolsets=a.toolsets)
    print(json.dumps(content, indent=1))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", help="owner/name. Otherwise $GH_REPO, otherwise the repo saved by `use`")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("use", help="choose the repo for this session and check the token can read it")
    s.add_argument("name", help="owner/name"); s.set_defaults(fn=cmd_use)

    s = sub.add_parser("which", help="print the repo commands will act on"); s.set_defaults(fn=cmd_which)

    s = sub.add_parser("ls", help="list a folder (-r: every file below it, in 2 API requests)")
    s.add_argument("paths", nargs="*"); s.add_argument("-r", "--recursive", action="store_true")
    s.add_argument("--all", action="store_true", help="ignore --skip and $GH_SKIP_DIRS"); s.add_argument("--ref")
    s.add_argument("--skip", help="comma-separated folder names to leave out, added to $GH_SKIP_DIRS")
    s.set_defaults(fn=cmd_ls)

    s = sub.add_parser("cat", help="print one file (no API request)"); s.add_argument("path"); s.add_argument("--ref")
    s.set_defaults(fn=cmd_cat)

    s = sub.add_parser("pull", help="copy files/folders into a local dir (2 API requests, any number of files)")
    s.add_argument("paths", nargs="+"); s.add_argument("-o", "--out", default=".")
    s.add_argument("--all", action="store_true", help="ignore --skip and $GH_SKIP_DIRS"); s.add_argument("--ref")
    s.add_argument("--skip", help="comma-separated folder names to leave out, added to $GH_SKIP_DIRS")
    s.add_argument("--missing-only", action="store_true",
                   help="leave every file that exists locally alone, even if it differs (identical files are always left)")
    s.set_defaults(fn=cmd_pull)

    s = sub.add_parser("clone", help="copy the whole repo into a work folder with a local git baseline")
    s.add_argument("dir", nargs="?", help="the work folder; default ~/work/NAME")
    s.add_argument("--branch", help="default: the repo's default branch"); s.set_defaults(fn=cmd_clone)

    s = sub.add_parser("sync", help="bring a work folder made by `clone` up to date with its branch")
    s.add_argument("dir", nargs="?", help="the work folder; default ~/work/NAME"); s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("status", help="what a work folder has changed since it matched its branch (no API request)")
    s.add_argument("dir", nargs="?", help="the work folder; default ~/work/NAME"); s.set_defaults(fn=cmd_status)

    s = sub.add_parser("branch", help="create a branch"); s.add_argument("name")
    s.add_argument("--base", default="main"); s.set_defaults(fn=cmd_branch)

    s = sub.add_parser("push", help="commit local files to a branch in one commit")
    s.add_argument("files", nargs="+", help="paths relative to --root"); s.add_argument("-b", "--branch", required=True)
    s.add_argument("--root", default="."); s.add_argument("-m", "--message"); s.add_argument("-F", "--message-file")
    s.set_defaults(fn=cmd_push)

    s = sub.add_parser("rm", help="delete files on a branch (one commit each)")
    s.add_argument("paths", nargs="*"); s.add_argument("--from-file"); s.add_argument("-b", "--branch", required=True)
    s.add_argument("-m", "--message", help="{path} is replaced by the file's path"); s.add_argument("-F", "--message-file")
    s.set_defaults(fn=cmd_rm)

    s = sub.add_parser("pr", help="open a pull request"); s.add_argument("--title", required=True)
    s.add_argument("--head", required=True); s.add_argument("--base", default="main")
    s.add_argument("--body-file", required=True); s.set_defaults(fn=cmd_pr)

    s = sub.add_parser("runs", help="recent GitHub Actions runs"); s.add_argument("-n", "--limit", type=int, default=10)
    s.set_defaults(fn=cmd_runs)

    s = sub.add_parser("logs", help="failed job logs for a run"); s.add_argument("run_id", type=int)
    s.add_argument("--tail", type=int, default=80); s.set_defaults(fn=cmd_logs)

    s = sub.add_parser("tools", help="list the server's tools"); s.add_argument("--toolsets", default="default")
    s.set_defaults(fn=cmd_tools)

    s = sub.add_parser("call", help="call any tool with JSON arguments"); s.add_argument("tool"); s.add_argument("args")
    s.add_argument("--toolsets", default="default"); s.set_defaults(fn=cmd_call)

    a = p.parse_args()
    try:
        if a.fn is not cmd_use:
            a.repo = resolve_repo(a.repo)
        a.fn(a)
    except McpError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
