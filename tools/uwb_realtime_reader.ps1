param(
    [string]$PortName = "COM7",
    [int]$BaudRate = 115200,
    [int]$WindowSize = 20,
    [string]$CsvPath = ""
)

$ErrorActionPreference = "Stop"

function Get-Stats {
    param([int[]]$Values)

    if ($Values.Count -eq 0) {
        return $null
    }

    $avg = ($Values | Measure-Object -Average).Average
    $min = ($Values | Measure-Object -Minimum).Minimum
    $max = ($Values | Measure-Object -Maximum).Maximum
    $sumSq = 0.0

    foreach ($v in $Values) {
        $sumSq += [math]::Pow($v - $avg, 2)
    }

    [pscustomobject]@{
        Average = $avg
        Minimum = $min
        Maximum = $max
        StdDev = [math]::Sqrt($sumSq / $Values.Count)
    }
}

$serial = New-Object System.IO.Ports.SerialPort $PortName, $BaudRate, 'None', 8, 'One'
$serial.NewLine = "`n"
$serial.ReadTimeout = 1000

$window = New-Object System.Collections.Generic.Queue[int]
$sampleCount = 0

if ($CsvPath -ne "") {
    $dir = Split-Path -Parent $CsvPath
    if ($dir -ne "" -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
    "pc_time,type,seq,d0_cm,d1_cm,d2_cm,d3_cm,status_hex,pc_ms,rxpwr0_cdbm,fppwr0_cdbm,gap0_cdb,fpidx0_q6,rxpacc0,rxpwr1_cdbm,fppwr1_cdbm,gap1_cdb,fpidx1_q6,rxpacc1,rxpwr2_cdbm,fppwr2_cdbm,gap2_cdb,fpidx2_q6,rxpacc2,rxpwr3_cdbm,fppwr3_cdbm,gap3_cdb,fpidx3_q6,rxpacc3,corrected_cm,raw_cm" | Set-Content -Path $CsvPath -Encoding UTF8
}

try {
    $serial.Open()
    Write-Host "Listening on $PortName @ $BaudRate. Press Ctrl+C to stop."
    Write-Host "Expected firmware line: RANGE4D,seq,d0_cm,d1_cm,d2_cm,d3_cm,status_hex,pc_ms,diagnostics..."

    while ($true) {
        $line = $serial.ReadLine().Trim()

        if ($line -match '^RANGE4D,') {
            $parts = $line.Split(',')
            if ($parts.Count -lt 28) {
                Write-Host $line
                continue
            }

            $seq = [int]$parts[1]
            $d0 = [int]$parts[2]
            $d1 = [int]$parts[3]
            $d2 = [int]$parts[4]
            $d3 = [int]$parts[5]
            $status = $parts[6]
            $pcMs = [int]$parts[7]
            $sampleCount++

            if ($d0 -ge 0) {
                $window.Enqueue($d0)
                while ($window.Count -gt $WindowSize) {
                    [void]$window.Dequeue()
                }
            }

            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
            $avgText = "n/a"
            if ($window.Count -gt 0) {
                $stats = Get-Stats -Values ([int[]]$window.ToArray())
                $avgText = ("{0:N2} cm min={1} max={2} std={3:N2}" -f $stats.Average, $stats.Minimum, $stats.Maximum, $stats.StdDev)
            }

            $gap0Db = ([int]$parts[10]) / 100.0
            $gap1Db = ([int]$parts[15]) / 100.0
            $gap2Db = ([int]$parts[20]) / 100.0
            $gap3Db = ([int]$parts[25]) / 100.0

            Write-Host ("{0} seq={1,4} A0={2,5}cm A1={3,5}cm A2={4,5}cm A3={5,5}cm status={6} pc_ms={7} gap_db=[{8:N1},{9:N1},{10:N1},{11:N1}] A0_avg{12}={13}" -f `
                $timestamp, $seq, $d0, $d1, $d2, $d3, $status, $pcMs, $gap0Db, $gap1Db, $gap2Db, $gap3Db, $WindowSize, $avgText)

            if ($CsvPath -ne "") {
                "$timestamp,$line,," | Add-Content -Path $CsvPath -Encoding UTF8
            }
        }
        elseif ($line -match '^RANGE4,(\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+),(0x[0-9A-Fa-f]+),(\d+)') {
            $seq = [int]$Matches[1]
            $d0 = [int]$Matches[2]
            $d1 = [int]$Matches[3]
            $d2 = [int]$Matches[4]
            $d3 = [int]$Matches[5]
            $status = $Matches[6]
            $pcMs = [int]$Matches[7]
            $sampleCount++

            if ($d0 -ge 0) {
                $window.Enqueue($d0)
                while ($window.Count -gt $WindowSize) {
                    [void]$window.Dequeue()
                }
            }

            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
            $avgText = "n/a"
            if ($window.Count -gt 0) {
                $stats = Get-Stats -Values ([int[]]$window.ToArray())
                $avgText = ("{0:N2} cm min={1} max={2} std={3:N2}" -f $stats.Average, $stats.Minimum, $stats.Maximum, $stats.StdDev)
            }

            Write-Host ("{0} seq={1,4} A0={2,5}cm A1={3,5}cm A2={4,5}cm A3={5,5}cm status={6} pc_ms={7} A0_avg{8}={9}" -f `
                $timestamp, $seq, $d0, $d1, $d2, $d3, $status, $pcMs, $WindowSize, $avgText)

            if ($CsvPath -ne "") {
                "$timestamp,RANGE4,$seq,$d0,$d1,$d2,$d3,$status,$pcMs,,,,,,,,,,,,,,,,,,,," | Add-Content -Path $CsvPath -Encoding UTF8
            }
        }
        elseif ($line -match '^RANGE,(\d+),(-?\d+),(-?\d+),(0x[0-9A-Fa-f]+)') {
            $seq = [int]$Matches[1]
            $corrected = [int]$Matches[2]
            $raw = [int]$Matches[3]
            $status = $Matches[4]
            $sampleCount++

            $window.Enqueue($corrected)
            while ($window.Count -gt $WindowSize) {
                [void]$window.Dequeue()
            }

            $stats = Get-Stats -Values ([int[]]$window.ToArray())
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"

            Write-Host ("{0} seq={1,4} distance={2,5} cm raw={3,5} cm avg{4}={5,6:N2} cm min={6,4} max={7,4} std={8,5:N2} status={9}" -f `
                $timestamp, $seq, $corrected, $raw, $WindowSize, $stats.Average, $stats.Minimum, $stats.Maximum, $stats.StdDev, $status)

            if ($CsvPath -ne "") {
                "$timestamp,RANGE,$seq,,,,,$status,,,,,,,,,,,,,,,,,,,,,$corrected,$raw" | Add-Content -Path $CsvPath -Encoding UTF8
            }
        }
        elseif ($line -ne "") {
            Write-Host $line
        }
    }
}
finally {
    if ($serial.IsOpen) {
        $serial.Close()
    }
}
