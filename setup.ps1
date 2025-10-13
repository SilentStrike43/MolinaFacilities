# ===============================
# Molina Facilities App - Setup
# ===============================

Write-Host "`n=== Initializing Molina Facilities App Environment ===`n" -ForegroundColor Cyan

# Move to the project root (same as this script)
Set-Location $PSScriptRoot

# Ensure Python virtual environment exists
if (-not (Test-Path ".\venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
} else {
    Write-Host "Virtual environment already exists." -ForegroundColor Green
}

# Activate virtual environment
Write-Host "Activating venv..."
& ".\venv\Scripts\Activate.ps1"

# Ensure required folders exist
$folders = @(
    "app",
    "app\common",
    "app\modules",
    "app\templates"
)
foreach ($folder in $folders) {
    if (-not (Test-Path $folder)) {
        New-Item -ItemType Directory -Path $folder | Out-Null
        Write-Host "Created folder: $folder" -ForegroundColor Yellow
    }
}

# Create required __init__.py files
$initFiles = @(
    "app\__init__.py",
    "app\common\__init__.py",
    "app\modules\__init__.py"
)
foreach ($file in $initFiles) {
    if (-not (Test-Path $file)) {
        New-Item -ItemType File -Path $file | Out-Null
        Write-Host "Created $file" -ForegroundColor Green
    }
}

# Install dependencies
Write-Host "`nInstalling dependencies..." -ForegroundColor Cyan
pip install flask openpyxl --quiet

# Run the app
Write-Host "`nStarting Molina Facilities App..." -ForegroundColor Cyan
python -m app.app
