$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false, $true)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

# The engine excludes parser-time dependency directives before this call.
$source = [Console]::In.ReadToEnd()
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput(
    $source, [ref] $tokens, [ref] $parseErrors
)
$findings = [System.Collections.Generic.List[object]]::new()

function Add-Finding {
    param(
        [string] $Id,
        [System.Management.Automation.Language.IScriptExtent] $Extent,
        [object] $NativeId
    )

    $findings.Add([ordered] @{
        id = $Id
        line = [Math]::Max(1, $Extent.StartLineNumber)
        column = [Math]::Max(1, $Extent.StartColumnNumber)
        nativeId = $NativeId
    })
}

if ($parseErrors.Count -gt 0) {
    foreach ($problem in $parseErrors) {
        Add-Finding -Id PS001 -Extent $problem.Extent -NativeId $problem.ErrorId
    }
} else {
    $nodes = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.CommandAst] -or
            $node -is [System.Management.Automation.Language.CatchClauseAst] -or
            $node -is [System.Management.Automation.Language.VariableExpressionAst]
    }, $true)

    foreach ($node in $nodes) {
        if ($node -is [System.Management.Automation.Language.CommandAst]) {
            $name = $node.GetCommandName()
            if ($name -in @('Invoke-Expression', 'iex', 'Microsoft.PowerShell.Utility\Invoke-Expression')) {
                Add-Finding -Id PS003 -Extent $node.Extent
            }

            for ($index = 1; $index -lt $node.CommandElements.Count; $index++) {
                $parameter = $node.CommandElements[$index]
                if ($parameter -isnot [System.Management.Automation.Language.CommandParameterAst] -or
                    $parameter.ParameterName -ne 'ErrorAction') {
                    continue
                }
                $argument = $parameter.Argument
                if ($null -eq $argument -and $index + 1 -lt $node.CommandElements.Count) {
                    $argument = $node.CommandElements[$index + 1]
                }
                if ($argument -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
                    $argument.Value -in @('SilentlyContinue', 'Ignore')) {
                    Add-Finding -Id PS005 -Extent $parameter.Extent
                }
            }
        } elseif ($node -is [System.Management.Automation.Language.CatchClauseAst]) {
            if ($node.Body.Statements.Count -eq 0 -and $node.Body.Traps.Count -eq 0) {
                Add-Finding -Id PS004 -Extent $node.Extent
            }
        } elseif ($node.VariablePath.IsGlobal) {
            Add-Finding -Id PS006 -Extent $node.Extent
        }
    }
}

ConvertTo-Json -InputObject ($findings.ToArray()) -Compress -Depth 4
