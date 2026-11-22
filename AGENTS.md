# PowerShellAssay contributor instructions

Read README.md, CONTRACT.md, and docs/native.md before changing verification
authority. Use the CanonFlow evidence-bounded-verification skill.
Use the CanonFlow idiomatic-powershell skill when changing this native lane.
Keep target sources as data during native inspection. Treat behavior commands
as trusted, explicit policy. Preserve missing evidence, tool failures, observed
source identity, and the four-state verdict contract.

Run python3 eng/qualify.py for the pinned native suite and isolated package
consumer. Add a native positive or negative specimen for each changed rule.
Keep test artifacts and tool downloads ignored.
