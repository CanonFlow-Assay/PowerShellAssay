# Source verification contract

A receipt covers the files named by one policy, the selected profile, the
qualified native tools observed in that run, and the declared behavior
commands. These sources may form a subset of an application.

## Commands

| Command | Evidence |
| --- | --- |
| doctor | Native tool readiness and versions. Exit 0 means the qualified tools are available. Exit 2 means a tool is missing or unsupported. |
| catalog | Exact rule predicates, admitted severities, native versions, and primary references |
| explain RULE | One catalogue entry |
| scan | Native checks without running policy commands |
| verify | Native checks and the policy's required behavior commands |
| assess | The complete verification receipt inside a versioned assessment envelope |

Scan, verify, and assess accept a required policy path and an optional
output path. They print a JSON object. A successfully written receipt
has identical content on stdout and at the output path.

## Policy and scope

A policy is UTF-8 JSON with exactly five fields.

| Field | Meaning |
| --- | --- |
| schemaVersion | The integer 1 |
| profile | The profile named in the catalogue |
| sources | Up to 32 unique, explicitly named project-relative source files |
| testInputs | Up to 64 unique additional files required by the behavior commands |
| requiredCommands | Up to 16 literal executable and argument arrays, each with 1 to 64 entries |

The policy directory is the working directory for behavior commands. Paths
are canonical relative file paths with no empty, dot, or parent components.
Symlink components are unsupported. Each input is bounded at 1 MiB.
Source must be nonempty UTF-8 without a byte-order mark or NUL. These exact
bytes are sent to the native checker via stdin. The receipt records the
SHA-256 of each observed file and the producer payload.

Required behavior commands are trusted project configuration. Read them
before running verify or assess. They can access the machine and have
ordinary process permissions. The runner supplies literal argument arrays
without constructing a shell command. It inherits the caller's environment
for those commands. Missing files or unsupported source text leave the
required commands unexecuted. Declare the files their conclusions depend on, and
keep credentials out of policy arguments. Additional undeclared process
inputs are outside the recorded closure.

Native analyzers run under a small environment in a disposable working
directory. They receive no user profile or inherited analyzer settings.
The analyzer-specific profile defines guarded parser features. These
measures limit normal native behavior. They provide no hostile-code or
hostile-filesystem sandbox.

## Verdicts

| Verdict | Exit | Meaning |
| --- | ---: | --- |
| Pass | 0 | A nonempty scope produced complete required native evidence and configured behavior commands passed. |
| Fail | 1 | A blocking profile predicate was violated or a required command exited nonzero. |
| Inconclusive | 2 | Required evidence is missing, unavailable, unsupported, stale, or unexecuted. |
| ToolFailure | 3 | Invalid policy or CLI, unexpected native protocol result, or receipt publication failure. |

ToolFailure takes precedence over Fail, which takes precedence over
Inconclusive. A known failure and independent missing evidence both
remain visible. Incomplete evidence sets the authoritative field to false.
A clean scan remains Inconclusive. Advisory findings remain visible.

Each native check and behavior command has a 30-second deadline and a
combined 1 MiB output limit with one detection byte. Native streams
are represented by separate hashes and a combined count. The runner
terminates the owned POSIX process group. A process that escapes that
group is outside its cleanup contract.

The tool re-observes declared files, qualified executable fingerprints,
and the producer after testing. Mutation visible at that check invalidates
freshness. Byte hashes provide integrity relations. Transient edits,
hostile filesystem races, whole runtime dependency graphs, and publisher
authenticity are outside that claim.

Optional receipt publication stages the file in an existing parent
directory, syncs the contents, and atomically replaces its target.
The writer rejects overlap with observed inputs, producer files,
or qualified executables. It rejects symlink traversal and multiply
linked targets. On publication failure the stdout object retains
the observed result.

## Packaging and qualification

The Python 3.12 runtime uses the standard library. The deterministic
zipapp includes the producer and catalogue. The separately installed native
programs remain upstream dependencies. Qualification checks all rules
against native fixtures and executes the zipapp from an independent
directory with the real example behavior commands.
