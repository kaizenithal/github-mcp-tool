"""Runs gh_mcp.py with GitHub answered from a local folder, so clone, sync and status can be tested
with no token, no network and no API requests.

    MOCK_SRC=/path/to/folder python3 tests/mock_github.py sync /path/to/work

MOCK_SRC is a folder standing for the branch: change the files in it and the "branch" has moved.
tests/sync_scenarios.sh uses this.
"""
import sys, os, json, hashlib
sys.path.insert(0, os.environ.get("TOOL_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gh_mcp
src = os.environ["MOCK_SRC"]
def blob(data): return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
def tree():
    out = []
    for root, _, names in os.walk(src):
        for n in names:
            full = os.path.join(root, n); rel = os.path.relpath(full, src).replace(os.sep, "/")
            out.append({"path": rel, "type": "blob", "mode": "100644", "sha": blob(open(full, "rb").read()), "size": 1})
    return out
def head(): return hashlib.sha1(json.dumps(sorted((e["path"], e["sha"]) for e in tree())).encode()).hexdigest()
def call(tool, args, toolsets="default"):
    if tool == "list_commits": return [{"text": json.dumps([{"sha": head()}])}]
    if tool == "get_repository_tree": return [{"text": json.dumps({"tree": tree(), "truncated": False})}]
    raise gh_mcp.McpError("mock: unexpected " + tool)
gh_mcp.call = call
gh_mcp.raw_file = lambda repo, ref, path, sha=None: open(os.path.join(src, path), "rb").read()
gh_mcp.main()
