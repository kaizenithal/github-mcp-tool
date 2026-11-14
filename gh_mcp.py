#!/usr/bin/env python3
"""Work with a GitHub repo through GitHub's hosted MCP server, using your own token.

Built for Claude Code cloud sessions, where github.com goes through a proxy that only
serves repos attached with the Claude GitHub App. GitHub's MCP server lives on a different
host (api.githubcopilot.com), so a personal access token in GH_TOKEN reaches the repo there.

The tool has no default repo. Name one with --repo, with $GH_REPO, or once per session with
`gh_mcp.py use OWNER/NAME`, which saves it in ~/.gh-mcp-repo.

Standard library only; HTTP goes through curl so the session's proxy settings apply.
See README.md next to this file for setup, commands and limits.
"""
import argparse
import base64
import hashlib
import json
import re
import os
import subprocess
import sys
import tempfile
import time

ENDPOINT = os.environ.get("GH_MCP_URL", "https://api.githubcopilot.com/mcp/")
REPO_FILE = os.path.expanduser("~/.gh-mcp-repo")
# Folder names `ls -r` and `pull` leave out, e.g. GH_SKIP_DIRS=node_modules,dist. Nothing is skipped by default.
SKIP_DIRS = {d.strip() for d in os.environ.get("GH_SKIP_DIRS", "").split(",") if d.strip()}


class McpError(RuntimeError):
    pass


def rpc(method, params=None, toolsets="default", timeout=120):
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise McpError("GH_TOKEN is not set. Add it to the cloud environment's variables.")
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
               "-H", f"X-MCP-Toolsets: {toolsets}", "--data-binary", f"@{f.name}"]
        proc = subprocess.run(cmd, input=f"Authorization: Bearer {token}\n", capture_output=True, text=True)
    finally:
        os.unlink(f.name)
    if proc.returncode != 0:
        raise McpError(f"curl failed ({proc.returncode}): {proc.stderr.strip()[:300]}")
    out = proc.stdout
    payload = None
    for line in out.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[6:])
    if payload is None:
        try:
            payload = json.loads(out)
        except ValueError:
            raise McpError(f"unexpected response: {out[:300]}")
    if "error" in payload:
        raise McpError(json.dumps(payload["error"])[:500])
    return payload["result"]


def call(tool, args, toolsets="default"):
    """Call an MCP tool. Returns the result's content list; raises McpError if the tool failed."""
    res = rpc("tools/call", {"name": tool, "arguments": args}, toolsets)
    content = res.get("content", [])
    if res.get("isError"):
        raise McpError(f"{tool}: " + " ".join(c.get("text", "") for c in content)[:500])
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

def list_dir(repo, path, ref=None):
    args = {**split_repo(repo), "path": path or "/"}
    if ref:
        args["ref"] = ref if ref.startswith("refs/") or len(ref) == 40 else f"refs/heads/{ref}"
    return text_json(call("get_file_contents", args))


def read_file(repo, path, ref=None):
    args = {**split_repo(repo), "path": path}
    if ref:
        args["ref"] = ref if ref.startswith("refs/") or len(ref) == 40 else f"refs/heads/{ref}"
    content = call("get_file_contents", args)
    for c in content:
        res = c.get("resource")
        if res is not None:
            if "text" in res:
                return res["text"].encode("utf-8")
            if "blob" in res:
                return base64.b64decode(res["blob"])
            return b""  # empty file
    # Over 1 MB the server returns a short-lived download link instead of the content.
    note = " ".join(c.get("text", "") for c in content)
    link = re.search(r"https://raw\.githubusercontent\.com/\S+", note)
    sha = re.search(r"SHA: ([0-9a-f]{40})", note)
    if link:
        return download_large(path, link.group(0), sha.group(1) if sha else None)
    raise McpError(f"{path}: no file content returned (is it a directory?)")


def download_large(path, url, sha):
    """Fetches a large file from GitHub's download link and checks it against the file's git blob SHA."""
    proc = subprocess.run(["curl", "-sS", "-f", "-m", "300", url], capture_output=True)
    if proc.returncode != 0:
        raise McpError(f"{path}: download failed: {proc.stderr.decode(errors='replace').strip()[:200]}")
    data = proc.stdout
    if sha and hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != sha:
        raise McpError(f"{path}: downloaded file does not match its git SHA {sha}")
    return data


def walk(repo, path, ref=None, skip=SKIP_DIRS):
    """Yield (path, size) for every file under path, leaving out folders named in skip."""
    for item in list_dir(repo, path, ref):
        if item["type"] == "dir":
            if item["name"] in skip:
                continue
            yield from walk(repo, item["path"], ref, skip)
        elif item["type"] == "file":
            yield item["path"], item.get("size", 0)


def cmd_ls(a):
    paths = a.paths or ["/"]
    for p in paths:
        if a.recursive:
            for f, size in walk(a.repo, p, a.ref, skip_set(a)):
                print(f"{size:>9}  {f}")
        else:
            for i in list_dir(a.repo, p, a.ref):
                print(f"{i['type']:<4}  {i['path']}{'/' if i['type'] == 'dir' else ''}")


def cmd_cat(a):
    sys.stdout.buffer.write(read_file(a.repo, a.path, a.ref))


def cmd_pull(a):
    """Copy files or folders from the repo into a local directory, keeping their paths."""
    out = os.path.abspath(a.out)
    skip = skip_set(a)
    n, failed = 0, []
    for p in a.paths:
        try:
            files = list(walk(a.repo, p, a.ref, skip))
        except (McpError, TypeError, KeyError):
            files = [(p, 0)]  # a single file, not a folder
        for f, size in files:
            dst = os.path.join(out, f)
            if a.missing_only and os.path.exists(dst):
                continue
            try:
                data = read_file(a.repo, f, a.ref)
            except McpError as e:
                failed.append((f, size, str(e)))
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(data)
            n += 1
    print(f"pulled {n} files into {out}")
    for f, _, err in failed:
        print(f"NOT PULLED {f}: {err[:160]}", file=sys.stderr)
    if failed:
        sys.exit(1)


# ---------- writing ----------

def cmd_branch(a):
    call("create_branch", {**split_repo(a.repo), "branch": a.name, "from_branch": a.base})
    print(f"created {a.name} from {a.base}")


def read_message(a):
    if a.message_file:
        with open(a.message_file, encoding="utf-8") as fh:
            return fh.read()
    if not a.message:
        raise McpError("give -m MESSAGE or -F FILE")
    return a.message


def cmd_push(a):
    """Commit local files (paths relative to --root) to a branch in ONE commit."""
    files = []
    for p in a.files:
        with open(os.path.join(a.root, p), encoding="utf-8") as fh:
            files.append({"path": p, "content": fh.read()})
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
    with open(a.body_file, encoding="utf-8") as fh:
        body = fh.read()
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
    content = call(a.tool, json.loads(a.args), toolsets=a.toolsets)
    print(json.dumps(content, indent=1))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", help="owner/name. Otherwise $GH_REPO, otherwise the repo saved by `use`")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("use", help="choose the repo for this session and check the token can read it")
    s.add_argument("name", help="owner/name"); s.set_defaults(fn=cmd_use)

    s = sub.add_parser("which", help="print the repo commands will act on"); s.set_defaults(fn=cmd_which)

    s = sub.add_parser("ls", help="list a folder (-r: every file below it)")
    s.add_argument("paths", nargs="*"); s.add_argument("-r", "--recursive", action="store_true")
    s.add_argument("--all", action="store_true", help="ignore --skip and $GH_SKIP_DIRS"); s.add_argument("--ref")
    s.add_argument("--skip", help="comma-separated folder names to leave out, added to $GH_SKIP_DIRS")
    s.set_defaults(fn=cmd_ls)

    s = sub.add_parser("cat", help="print one file"); s.add_argument("path"); s.add_argument("--ref")
    s.set_defaults(fn=cmd_cat)

    s = sub.add_parser("pull", help="copy files/folders into a local dir")
    s.add_argument("paths", nargs="+"); s.add_argument("-o", "--out", default=".")
    s.add_argument("--all", action="store_true", help="ignore --skip and $GH_SKIP_DIRS"); s.add_argument("--ref")
    s.add_argument("--skip", help="comma-separated folder names to leave out, added to $GH_SKIP_DIRS")
    s.add_argument("--missing-only", action="store_true", help="skip files that already exist locally")
    s.set_defaults(fn=cmd_pull)

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


if __name__ == "__main__":
    main()
