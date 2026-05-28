param(
    [string]$BaseUrl = "https://localhost",
    [string[]]$ExpectedAllowedOrigins = @()
)

$ErrorActionPreference = "Stop"

function Write-CheckResult {
    param(
        [string]$Label,
        [bool]$Passed,
        [string]$Details
    )

    if ($Passed) {
        Write-Host "PASS: $Label - $Details"
    } else {
        Write-Host "FAIL: $Label - $Details"
    }
}

function Get-HeaderValue {
    param(
        [object]$Headers,
        [string]$Name
    )

    if (-not $Headers) {
        return $null
    }

    foreach ($key in $Headers.Keys) {
        if ($key -ieq $Name) {
            return $Headers[$key]
        }
    }

    return $null
}

function Get-ResponseHeaders {
    param(
        [string]$Url
    )

    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl) {
        throw "curl.exe is required for this script."
    }

    $rawHeaders = & curl.exe -k -sS -D - -o NUL $Url
    if ($LASTEXITCODE -ne 0) {
        throw "curl.exe failed to fetch $Url (exit code $LASTEXITCODE)."
    }

    $headers = @{}
    $lines = $rawHeaders -split "`r?`n"

    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        if ($line.StartsWith("HTTP/")) {
            continue
        }

        $separatorIndex = $line.IndexOf(':')
        if ($separatorIndex -lt 1) {
            continue
        }

        $key = $line.Substring(0, $separatorIndex).Trim()
        $value = $line.Substring($separatorIndex + 1).Trim()

        if ($headers.ContainsKey($key)) {
            $headers[$key] = "$($headers[$key]), $value"
        } else {
            $headers[$key] = $value
        }
    }

    return $headers
}

function Display-Value {
    param(
        [string]$Value,
        [string]$Fallback = "(missing)"
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Fallback
    }

    return $Value
}

$base = $BaseUrl.TrimEnd('/')
$failures = 0

try {
    $publicHeaders = Get-ResponseHeaders -Url "$base/public-board.html"
} catch {
    Write-Host "FAIL: Could not fetch $base/public-board.html - $($_.Exception.Message)"
    exit 1
}

$publicCsp = Get-HeaderValue -Headers $publicHeaders -Name "Content-Security-Policy"
$publicXfo = Get-HeaderValue -Headers $publicHeaders -Name "X-Frame-Options"

$hasFrameAncestors = $false
if ($publicCsp) {
    $hasFrameAncestors = $publicCsp -match "frame-ancestors"
}

Write-CheckResult -Label "public-board CSP includes frame-ancestors" -Passed:$hasFrameAncestors -Details:(Display-Value -Value $publicCsp)
if (-not $hasFrameAncestors) {
    $failures += 1
}

$publicXfoMissing = [string]::IsNullOrWhiteSpace($publicXfo)
if ($publicXfoMissing) {
    $publicXfoDetails = "(missing as expected)"
} else {
    $publicXfoDetails = $publicXfo
}
Write-CheckResult -Label "public-board omits X-Frame-Options" -Passed:$publicXfoMissing -Details:$publicXfoDetails
if (-not $publicXfoMissing) {
    $failures += 1
}

foreach ($origin in $ExpectedAllowedOrigins) {
    $trimmed = $origin.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        continue
    }

    $originIncluded = $false
    if ($publicCsp) {
        $originIncluded = $publicCsp.Contains($trimmed)
    }

    Write-CheckResult -Label "public-board CSP contains allowlisted origin $trimmed" -Passed:$originIncluded -Details:(Display-Value -Value $publicCsp)
    if (-not $originIncluded) {
        $failures += 1
    }
}

try {
    $boardHeaders = Get-ResponseHeaders -Url "$base/board.html"
} catch {
    Write-Host "FAIL: Could not fetch $base/board.html - $($_.Exception.Message)"
    exit 1
}

$boardXfo = Get-HeaderValue -Headers $boardHeaders -Name "X-Frame-Options"
$boardHasSameOrigin = -not [string]::IsNullOrWhiteSpace($boardXfo) -and ($boardXfo -match "SAMEORIGIN")

Write-CheckResult -Label "board.html keeps SAMEORIGIN framing protection" -Passed:$boardHasSameOrigin -Details:(Display-Value -Value $boardXfo)
if (-not $boardHasSameOrigin) {
    $failures += 1
}

if ($failures -gt 0) {
    Write-Host ""
    Write-Host "Embed policy checks failed: $failures"
    exit 1
}

Write-Host ""
Write-Host "All embed policy checks passed."
