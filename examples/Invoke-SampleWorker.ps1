[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $WorkerPath,

    [Parameter(Mandatory)]
    [string] $Label
)

$ErrorActionPreference = 'Stop'
& python3 $WorkerPath $Label
$workerExit = $LASTEXITCODE
exit $workerExit
