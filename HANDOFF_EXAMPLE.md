# Handoff

What a new Claude Code cloud session needs to continue the provided example "Universe". It replaces the Claude doc "Universe — Handoff to Claude Code", which is no longer kept up to date.

**Keep this file current.** Every pull request that finishes a job, starts one or settles a decision updates
"Where the work stands" in the same pull request. Last updated: 13 November 2026.

## Start here

1. **GitHub access.** If you are reading this from the bootstrap one-liner, you have it. If not, the one-liner is in
   [`tools/github-mcp/README.md`](tools/github-mcp/README.md), with the commands and their limits. Use the provided token through that tool. Do not use the built-in GitHub connection (`add_repo`) unless the owner asks.
2. **Code.** `##Example\n python3 -I ~/gh-mcp/gh_mcp.py pull Universe.sln Universe.Sim Universe.Sim.Tests Universe.Game README.md -o ~/work`,
   then `git init` and commit there, so `git diff` shows what you changed. There is no `git clone` or `git push`.
3. **Toolchain.** Download `setup.sh` from the latest release of `kaizenithal/universe-toolchain`, read it, then run
   it with `bash setup.sh`. Piping the download straight into a shell is refused in cloud sessions. Then
   `source ~/.universe-toolchain/env.sh`. This takes two to three minutes.
4. **Check.** `dotnet build Universe.sln` (expect 0 warnings) and `dotnet test Universe.Sim.Tests` (expect every
   test to pass; 113 on 13 November). `godot --headless --path Universe.Game --import` before the first render.
5. **Report.** Tell the owner what you found (tests, open pull requests, anything that differs from this file)
   before changing anything.

## Seeing the screen

There is no phone or window in a cloud session. The developer UI tour renders the real UI to images:

```
xvfb-run -a -s "-screen 0 720x1280x24" godot --path Universe.Game --rendering-method gl_compatibility \
  --rendering-driver opengl3 --resolution 720x1280 --fixed-fps 30 --write-movie /path/to/out/f.png \
  --quit-after 215 -- --preview=ui-tour
```

It writes one PNG per frame. `Universe.Game/Scripts/Main.Tour.cs` lists which frames show which state (frame 13 +
15 per step for the first six; a camp near frame 125 and a nest near frame 175). `-- --preview=statuses` is a
second preview, for unit status markers. Frames check layout only: they use the Compatibility renderer, and feel,
touch and performance are judged by the owner on a phone.

## Working agreements

- **Cloud only.** The owner's computer is not needed for development.
- **Pull requests from `claude/...` branches.** One job per pull request, branch cut from the latest `main`. The
  owner merges with Squash and merge.
- **Run it before sending it.** Build and the full test suite before every pull request. Wait for CI
  (`gh_mcp.py runs`) to pass before calling it ready. The description says what was run and what was not.
- **Show UI changes.** Send before and after frames with every UI pull request.
- **Design decisions are the owner's.** Propose a rule change and get an answer before building it. Name any
  choice you made for them in the pull request.
- **No guessed fixes.** When a cause is unknown, add a diagnostic or a test first.
- **Challenge the plan.** The owner has asked for assumptions to be questioned, with an argument, before work starts.
- **Plain language.** The owner reads summaries, not code. Lead with what changed for the player.

## Where the work stands

### Done and merged

- **Scenario mode (#15).** The game starts in `Scenario.Outbreak`: three nests that send growing waves, four camps
  that guard caches, win by destroying every nest. `WaveDirector` spends a strength budget on units at their own
  prices, so new units need no enemy-side change. Difficulty is `WaveSettings` (Easy, Medium, Hard).
- **The Remnant AI is parked.** `RemnantBrain`, `AiProfile` and `Simulation.CreateSlice` still exist and their tests
  run, but the game does not start that mode. When a rule change breaks those tests, skip them; do not teach the
  AI the new rule. A future AI should score its options from game data, not follow hand-written build orders.
- **UI: clear selection (#13)** and **squad editor with − / + steppers (#14).** Shared colours and styles are in
  `Universe.Game/Scripts/Ui.cs`; build new UI on them, not on Godot's default theme.
- **Earlier:** unit status markers (#11), Charger ambush (#9), large-file support in the GitHub tool (#12), CI.

### Next, in order

1. **Play the scenario and tune it.** Nobody has played it yet. The owner plays on a phone; wave sizes, spacing and
   nest guards in `Scenario.cs` are first guesses.
2. **Supply.** A faction-wide supply pool replaces the 12-per-squad cap, so squad size is the player's choice.
   Player-only now that the enemy has no economy. Waiting on the decisions below.
3. **More room for the map.** Tapping the open tab collapses the bottom panel; the help line only shows while
   placing something.
4. **Research tab.** Progress bars and a layout by tier.

### Open decisions for the owner

- **Supply: where it comes from.** Proposed: a repeatable purchase at the Hub (+8 for 100 Ore), not a building.
- **Supply: whether Drones use it.** Proposed: yes.
- **Supply: a ceiling.** Proposed: about 80.
- **Supply: the owner's other issue.** The owner said supply touches another concern they have; ask what it is.
- **Recall highlight.** Recall lights up while a squad is idle at base. Alternative: light nothing when idle.
- **Hold-to-repeat** on the squad editor's − / + buttons. Not built.
- **Wave warnings.** Every warning pauses the game. Option: warnings for nests not yet found do not pause.
- **Nest guards** grow with each wave, up to double. Judge when playing.

### Known gaps

- **Nest art.** Nests are drawn with the Remnant Hub art and a name tag.
- **New squads have no card.** Squad cards are created when the match starts.
- **.NET 8** is out of support since 10 November 2026. The project builds and runs on it.
- **No taps in previews.** The UI tour sets state directly; button presses are not exercised.

## Things that trip a session

- **Stale Godot imports.** If an asset fails to load after a pull, delete its `.import` file and run the import again.
- **Deleting with a variable path** (`rm -f $DIR/*`) is refused. Write `"${DIR:?}"/*`.
- **Scenario enemies need a composition.** A squad whose composition is smaller than its units loses them to the
  Reserve at the next reinforce pass. Use `Simulation.SpawnSquad`, which sets it.
- **The Remnant AI is live in every `CreateSlice` test.** It builds, researches and raids while a test runs.
- **Throwaway diagnostics.** A temporary xUnit class that prints through `ITestOutputHelper` is the quick way to
  read a simulation run. Delete it before committing.

## Other documents

- "Universe — Core Design Document": the game design, a Claude doc. Ask the owner for the link. It still describes
  squads of 4 to 12 and the Remnant as the opponent; this file is newer where they differ.
- `README.md`: what the game is and how its projects are laid out.
- `tools/github-mcp/README.md`: the GitHub tool.
- `kaizenithal/universe-toolchain`: the pinned .NET SDK, NuGet packages and Godot, and how to update them.