# Handoff

What a new Claude Code cloud session needs to continue PROJECT NAME. Copy this file to the root of your project's
repo as `HANDOFF.md` and replace everything in CAPITALS. Delete sections that don't apply.

**Keep this file current.** Every pull request that finishes a job, starts one or settles a decision updates
"Where the work stands" in the same pull request. Last updated: DATE.

## Start here

1. **GitHub access.** If you are reading this from the start-of-session commands, you have it. The commands and
   their limits are in the README of `kaizenithal/github-mcp-tool`, cloned to `~/gh-mcp`. Use the owner's token
   through that tool. Do not use the built-in GitHub connection unless the owner asks.
2. **Code.** If the start-of-session commands ran `gh_mcp.py clone`, the repo is in `~/work/NAME` with a local
   git baseline, so `git diff` shows what you change. Run `python3 ~/gh-mcp/gh_mcp.py sync` to bring it up to
   date later. Do not fetch files one at a time: API requests are limited per hour and shared by all sessions.
3. **Toolchain.** HOW TO INSTALL WHAT THE PROJECT NEEDS, AND HOW LONG IT TAKES.
4. **Check.** BUILD COMMAND AND TEST COMMAND, WITH THE RESULT TO EXPECT (FOR EXAMPLE "120 TESTS PASS").
5. **Report.** Tell the owner what you found (tests, open pull requests, anything that differs from this file)
   before changing anything.

## Working agreements

- **Pull requests from `claude/...` branches.** One job per pull request, branch cut from the latest `main`. The
  owner merges with Squash and merge.
- **Run it before sending it.** Build and run the full test suite before every pull request. Wait for CI
  (`gh_mcp.py runs`) to pass before calling it ready. The description says what was run and what was not.
- ANY OTHER STANDING PREFERENCES: WHO DECIDES WHAT, HOW RESULTS SHOULD BE SHOWN, WHAT NEVER TO DO.

## Where the work stands

### Done and merged

- WHAT IS FINISHED, WITH PULL REQUEST NUMBERS, AND ANYTHING A NEWCOMER MUST KNOW ABOUT IT.

### Next, in order

1. THE NEXT JOB, AND WHAT IT IS WAITING ON IF ANYTHING.
2. THE ONE AFTER.

### Open decisions for the owner

- A DECISION THAT IS NOT MADE YET, WITH WHAT WAS PROPOSED.

### Known gaps

- THINGS THAT ARE KNOWINGLY UNFINISHED OR UNCHECKED.

## Things that trip a session

- A MISTAKE AN EARLIER SESSION MADE, AND HOW TO AVOID IT.

## Other documents

- WHERE THE DESIGN, THE PROJECT README AND ANY RELATED REPOS ARE.
