#!/usr/bin/env bash
# Scenarios for `sync` when the work folder and the branch have both lost, gained or changed files.
# Needs no token and makes no requests: tests/mock_github.py stands in for GitHub.
#
#   bash tests/sync_scenarios.sh              test gh_mcp.py in this repo
#   bash tests/sync_scenarios.sh /other/dir   test the gh_mcp.py in another folder
#
# Prints ok or FAIL per check and exits 1 if any failed.
set -u
here="$(cd "$(dirname "$0")" && pwd)"; export TOOL_DIR="${1:-$(dirname "$here")}" GH_REPO=o/r GH_TOKEN=x
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
G="python3 $here/mock_github.py"; fail=0
fresh() { rm -rf $T/src $T/w; mkdir -p $T/src/d; for f in a b c d/e d/f; do echo "$f v1" > $T/src/$f; done; export MOCK_SRC=$T/src; $G clone $T/w >/dev/null || { echo "clone failed"; fail=1; }; }
lc() { git -C $T/w add -A; git -C $T/w -c user.name=t -c user.email=t@t commit -qm "$1"; }
check() { if eval "$2"; then echo "  ok    $1"; else echo "  FAIL  $1"; fail=1; fi; }
clean() { [ -z "$(git -C $T/w status --porcelain)" ]; }

echo "1. deleted on the branch, already deleted and committed locally"
fresh; rm $T/w/b; lc "mine: drop b"; rm $T/src/b; echo "c v2" > $T/src/c
out="$($G sync $T/w 2>&1)"; rc=$?
check "sync succeeds" "[ $rc -eq 0 ]"; [ $rc -ne 0 ] && echo "$out" | tail -3 | sed 's/^/        /'
check "c updated" "grep -q 'c v2' $T/w/c"; check "b gone" "[ ! -e $T/w/b ]"; check "tree clean" clean
check "sync again is a no-op" "$G sync $T/w 2>&1 | grep -q 'Already in step'"

echo "2. only change on the branch is a deletion the folder already made"
fresh; rm $T/w/b; lc "mine"; rm $T/src/b
out="$($G sync $T/w 2>&1)"; rc=$?; check "sync succeeds" "[ $rc -eq 0 ]"; [ $rc -ne 0 ] && echo "$out" | tail -3 | sed 's/^/        /'
check "tree clean" clean; check "status shows nothing" "$G status $T/w | grep -q 'Nothing differs'"

echo "3. a whole folder deleted on the branch and already deleted locally"
fresh; rm -r $T/w/d; lc "mine"; rm -r $T/src/d; echo "a v2" > $T/src/a
out="$($G sync $T/w 2>&1)"; rc=$?; check "sync succeeds" "[ $rc -eq 0 ]"; [ $rc -ne 0 ] && echo "$out" | tail -3 | sed 's/^/        /'
check "a updated" "grep -q 'a v2' $T/w/a"; check "tree clean" clean

echo "4. deleted on the branch, still present locally (the ordinary case)"
fresh; rm $T/src/b; out="$($G sync $T/w 2>&1)"; rc=$?; check "sync succeeds" "[ $rc -eq 0 ]"; check "b gone" "[ ! -e $T/w/b ]"; check "tree clean" clean

echo "5. deleted on the branch, modified locally"
fresh; echo "b mine" > $T/w/b; lc "mine"; rm $T/src/b; out="$($G sync $T/w 2>&1)"; rc=$?
check "sync succeeds" "[ $rc -eq 0 ]"; check "b gone" "[ ! -e $T/w/b ]"; check "says ATTENTION for b" "echo \"$out\" | grep -q \"'b'\""; check "tree clean" clean

echo "6. deleted locally, changed on the branch"
fresh; rm $T/w/b; lc "mine"; echo "b v2" > $T/src/b; out="$($G sync $T/w 2>&1)"; rc=$?
check "sync succeeds" "[ $rc -eq 0 ]"; check "b back with the branch's version" "grep -q 'b v2' $T/w/b"; check "says ATTENTION for b" "echo \"$out\" | grep -q \"'b'\""; check "tree clean" clean

echo "7. added on the branch where the folder has an ignored file of that name"
fresh; echo "*.log" > $T/w/.gitignore; lc "mine"; echo "local" > $T/w/x.log; echo "branch" > $T/src/x.log
out="$($G sync $T/w 2>&1)"; rc=$?; check "sync succeeds" "[ $rc -eq 0 ]"; [ $rc -ne 0 ] && echo "$out" | tail -3 | sed 's/^/        /'
check "x.log is the branch's" "grep -q branch $T/w/x.log"; check "x.log is tracked" "git -C $T/w ls-files | grep -q x.log"

echo "8. a file replaced by a folder of the same name on the branch"
fresh; rm $T/src/a; mkdir $T/src/a; echo "inner" > $T/src/a/inner; out="$($G sync $T/w 2>&1)"; rc=$?
check "sync succeeds" "[ $rc -eq 0 ]"; [ $rc -ne 0 ] && echo "$out" | tail -3 | sed 's/^/        /'
check "a/inner present" "[ -f $T/w/a/inner ]"; check "tree clean" clean

echo "9. a folder replaced by a file of the same name on the branch"
fresh; rm -r $T/src/d; echo "now a file" > $T/src/d; out="$($G sync $T/w 2>&1)"; rc=$?
check "sync succeeds" "[ $rc -eq 0 ]"; [ $rc -ne 0 ] && echo "$out" | tail -3 | sed 's/^/        /'
check "d is a file" "[ -f $T/w/d ]"; check "tree clean" clean

echo "10. a sync whose local commit fails puts the folder back, and works when run again"
fresh; echo "c v2" > $T/src/c; rm $T/src/b; printf '#!/bin/sh\nexit 1\n' > $T/w/.git/hooks/pre-commit; chmod +x $T/w/.git/hooks/pre-commit
out="$($G sync $T/w 2>&1)"; rc=$?; rm -f $T/w/.git/hooks/pre-commit
check "sync reports the failure" "[ $rc -ne 0 ]"; check "c is back to what it was" "grep -q 'c v1' $T/w/c"; check "b is back" "[ -f $T/w/b ]"; check "tree clean" clean
out="$($G sync $T/w 2>&1)"; rc=$?; check "second sync succeeds" "[ $rc -eq 0 ]"; check "c updated" "grep -q 'c v2' $T/w/c"; check "b gone" "[ ! -e $T/w/b ]"

echo "11. a folder the branch turned into a file still holds a file of the session's"
fresh; echo "mine" > $T/w/d/keep; lc "mine"; rm -r $T/src/d; echo "now a file" > $T/src/d
out="$($G sync $T/w 2>&1)"; rc=$?; check "sync refuses" "[ $rc -ne 0 ]"; check "says why" "echo \"$out\" | grep -q 'still has files'"
check "the session's file is untouched" "grep -q mine $T/w/d/keep"; check "tree clean" clean

echo "12. the folder stuck by the old fault recovers: commit what is there, then sync"
fresh; rm $T/w/b; lc "mine"; rm $T/src/b; echo "c v2" > $T/src/c; echo "c v2" > $T/w/c
check "sync refuses while uncommitted" "! $G sync $T/w >/dev/null 2>&1"; lc "wip"
out="$($G sync $T/w 2>&1)"; rc=$?; check "sync succeeds after committing" "[ $rc -eq 0 ]"; check "tree clean" clean
check "status shows nothing" "$G status $T/w | grep -q 'Nothing differs'"
exit $fail
