# Native scope and sources

The profile is **powershell-automation**. The qualified versions are
**PowerShell 7.7.0** on Linux x86-64.

The profile rejects lexical candidates for using, configuration, and
#requires before native parsing. Some directives consult dependencies during
parsing. This conservative guard can also reject those words in strings
or comments. Parser-sensitive files need a separate reviewed lane. Dynamic
command dispatch, additional aliases, and module or host semantics require
application tests.

Use typed parameters and named cmdlet arguments, with literal paths for data.
Capture the native exit code immediately after invoking a program. The
example passes a space-containing argument to a worker and checks that an
actual worker failure is returned as exit 7.

The Linux x86-64 archive matches the SHA-256 published by GitHub for the PowerShell release asset. The receipt fingerprints both the launched executable and the parser assembly. See the [toolchain manifest](../toolchain.json).

The profile implements the finite rules in the catalogue. Platform branches,
application behaviors beyond the declared examples, and the effectiveness of
project-specific operating practices need their own evidence.

## Primary sources

- [PowerShell ParseInput API](https://learn.microsoft.com/dotnet/api/system.management.automation.language.parser.parseinput)
- [PowerShell 7.7.0 parser implementation](https://github.com/PowerShell/PowerShell/blob/v7.7.0/src/System.Management.Automation/engine/parser/Parser.cs)
- [PowerShell parsing and native arguments](https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_parsing)
- [PSScriptAnalyzer rule guidance](https://learn.microsoft.com/powershell/utility-modules/psscriptanalyzer/rules/readme)
- [PowerShell 7.7.0 release](https://github.com/PowerShell/PowerShell/releases/tag/v7.7.0)
