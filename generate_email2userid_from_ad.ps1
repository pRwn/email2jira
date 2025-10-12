#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Generate email2userid.csv from Active Directory

.DESCRIPTION
    This script queries Active Directory for all users and creates a CSV file
    mapping email addresses to user IDs (samAccountName).

    For each user, it extracts:
    - Primary email from the 'mail' attribute
    - All SMTP addresses from 'proxyAddresses' attribute

    The output CSV has columns: email,userid

.PARAMETER OutputPath
    Path to the output CSV file. Default: email2userid.csv in the script directory

.PARAMETER SearchBase
    LDAP search base for AD query. If not specified, searches entire domain.

.EXAMPLE
    .\generate_email2userid_from_ad.ps1

.EXAMPLE
    .\generate_email2userid_from_ad.ps1 -OutputPath "C:\data\email_mapping.csv"

.EXAMPLE
    .\generate_email2userid_from_ad.ps1 -SearchBase "OU=Users,DC=company,DC=com"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$OutputPath = (Join-Path $PSScriptRoot "email2userid.csv"),

    [Parameter(Mandatory=$false)]
    [string]$SearchBase = $null
)

# Ensure the Active Directory module is available
try {
    Import-Module ActiveDirectory -ErrorAction Stop
    Write-Host "Active Directory module loaded successfully" -ForegroundColor Green
} catch {
    Write-Error "Failed to load Active Directory module. Please ensure RSAT-AD-PowerShell is installed."
    exit 1
}

# Build the Get-ADUser parameters
$adParams = @{
    Filter = '*'
    Properties = 'mail', 'proxyAddresses', 'samAccountName', 'enabled'
}

if ($SearchBase) {
    $adParams['SearchBase'] = $SearchBase
    Write-Host "Searching for users in: $SearchBase" -ForegroundColor Cyan
} else {
    Write-Host "Searching for users in entire domain" -ForegroundColor Cyan
}

# Query Active Directory
Write-Host "Querying Active Directory for users..." -ForegroundColor Cyan
try {
    $users = Get-ADUser @adParams
    Write-Host "Found $($users.Count) users in Active Directory" -ForegroundColor Green
} catch {
    Write-Error "Failed to query Active Directory: $_"
    exit 1
}

# Create a list to store email-to-userid mappings
$emailMappings = [System.Collections.Generic.List[PSCustomObject]]::new()

# Process each user
$processedCount = 0
$skippedCount = 0

foreach ($user in $users) {
    $samAccountName = $user.samAccountName

    # Skip if no samAccountName
    if ([string]::IsNullOrWhiteSpace($samAccountName)) {
        Write-Warning "Skipping user without samAccountName: $($user.DistinguishedName)"
        $skippedCount++
        continue
    }

    # Skip disabled users
    if (-not $user.Enabled) {
        Write-Verbose "Skipping disabled user: $samAccountName"
        $skippedCount++
        continue
    }

    # Collect all email addresses for this user
    $emailAddresses = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

    # Add primary email from 'mail' attribute
    if (-not [string]::IsNullOrWhiteSpace($user.mail)) {
        [void]$emailAddresses.Add($user.mail.ToLower())
    }

    # Add all SMTP addresses from proxyAddresses
    if ($user.proxyAddresses) {
        foreach ($proxyAddress in $user.proxyAddresses) {
            # proxyAddresses format: "SMTP:primary@domain.com" or "smtp:alias@domain.com"
            # We want both SMTP (primary) and smtp (alias) addresses
            if ($proxyAddress -match '^smtp:(.+)$') {
                $emailAddr = $matches[1].ToLower()
                [void]$emailAddresses.Add($emailAddr)
            }
        }
    }

    # Create a mapping entry for each email address
    if ($emailAddresses.Count -gt 0) {
        foreach ($email in $emailAddresses) {
            $emailMappings.Add([PSCustomObject]@{
                email = $email
                userid = $samAccountName
            })
        }
        $processedCount++
    } else {
        Write-Verbose "No email addresses found for user: $samAccountName"
        $skippedCount++
    }
}

# Sort by email address for easier lookup
$emailMappings = $emailMappings | Sort-Object -Property email

# Export to CSV
Write-Host "Exporting $($emailMappings.Count) email mappings to: $OutputPath" -ForegroundColor Cyan
try {
    $emailMappings | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding UTF8
    Write-Host "Successfully created email2userid.csv" -ForegroundColor Green
    Write-Host "  - Total users processed: $processedCount" -ForegroundColor Green
    Write-Host "  - Total email mappings: $($emailMappings.Count)" -ForegroundColor Green
    Write-Host "  - Users skipped: $skippedCount" -ForegroundColor Yellow
} catch {
    Write-Error "Failed to export CSV: $_"
    exit 1
}

# Display sample of the output
Write-Host "`nSample of generated mappings (first 10):" -ForegroundColor Cyan
$emailMappings | Select-Object -First 10 | Format-Table -AutoSize

Write-Host "`nDone!" -ForegroundColor Green
