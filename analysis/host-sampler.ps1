# Muestrea el consumo del anfitrión (Windows) mientras corren los experimentos.
#   powershell -ExecutionPolicy Bypass -File analysis\host-sampler.ps1 -Out experiments\results\real\host.csv
# Cortar con Ctrl+C. Columnas: hora, CPU total (%), RAM libre (MB),
# CPU de los procesos de VirtualBox (% de un núcleo) y su memoria (MB).
param(
    [string]$Out = "experiments\results\real\host.csv",
    [int]$Interval = 5
)

$cores = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
if (-not (Test-Path $Out)) {
    "timestamp,host_cpu_pct,host_free_mb,vbox_cpu_pct,vbox_mem_mb,other_cpu_pct" | Out-File -Encoding ascii $Out
}
$prev = @{}
while ($true) {
    $cpu = (Get-Counter '\Processor(_Total)\% Processor Time').CounterSamples[0].CookedValue
    $free = (Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue
    $now = Get-Date
    $vbCpu = 0.0; $vbMem = 0.0
    foreach ($p in Get-Process -Name VBoxHeadless, VirtualBoxVM, VBoxSVC -ErrorAction SilentlyContinue) {
        $vbMem += $p.WorkingSet64 / 1MB
        if ($prev.ContainsKey($p.Id)) {
            $dt = ($now - $prev[$p.Id].t).TotalSeconds
            if ($dt -gt 0) { $vbCpu += 100 * ($p.TotalProcessorTime - $prev[$p.Id].cpu).TotalSeconds / $dt }
        }
        $prev[$p.Id] = @{ t = $now; cpu = $p.TotalProcessorTime }
    }
    # CPU del resto del anfitrión (juegos, navegador...) en % del total de núcleos
    $other = [math]::Max(0, $cpu - $vbCpu / $cores)
    "{0},{1:F1},{2:F0},{3:F1},{4:F0},{5:F1}" -f $now.ToString("s"), $cpu, $free, $vbCpu, $vbMem, $other |
        Out-File -Encoding ascii -Append $Out
    Start-Sleep -Seconds $Interval
}
