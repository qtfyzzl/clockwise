#requires -Version 5.1
<#
.SYNOPSIS
    Clockwise 固件生产烧录脚本（PowerShell 5.1+）

.DESCRIPTION
    默认按 4 个地址分段烧录（bootloader / 分区表 / otadata / app），
    这样不会覆盖 NVS 区（0x9000-0xDFFF），WiFi、时区、亮度等设置得以保留。

    针对本机这台 CH340 成品板：RTS 接 EN、DTR 未接 IO0，
    无法自动进下载模式，脚本会提示操作员按住 BOOT 并自动重试。

.PARAMETER Port
    串口号，如 COM8。不填则自动枚举本机串口并交互式选择。

.PARAMETER Erase
    烧录前整片擦除（会清空 NVS，WiFi 需重配）。

.PARAMETER Merged
    改用单文件合并镜像烧到 0x0。注意：合并镜像以 0xFF 连续填充，
    会连带清掉 NVS 区，相当于每次都重置配置。救砖或量产才需要。

.PARAMETER Baud
    波特率，默认 460800；线材差可降到 115200。

.PARAMETER TimeoutSec
    每个阶段等待芯片响应的最长时间，默认 180 秒。

.EXAMPLE
    .\flash.ps1

.EXAMPLE
    .\flash.ps1 -Port COM8        # 指定串口，跳过选择

.EXAMPLE
    .\flash.ps1 -Erase          # 首次量产：整片擦除（需重配 WiFi）

.EXAMPLE
    .\flash.ps1 -Merged         # 救砖：单文件烧到 0x0
#>
param(
    [string]$Port    = "",
    [switch]$Erase,
    [switch]$Merged,
    [int]$Baud       = 460800,
    [int]$TimeoutSec = 180
)

# 原生程序（esptool）往 stderr 写错误时会触发 NativeCommandError，
# 若用 "Stop" 会直接中断脚本。统一用 Continue，靠输出内容和 $LASTEXITCODE 判断。
$ErrorActionPreference = "Continue"

# ---------- 串口自动枚举与选择 ----------
# 未通过 -Port 指定时，枚举本机串口让操作员挑一个。换电脑后 CH340 可能变成
# COM3/COM4/COM5/COM8 等，写死默认值会在别的机器上直接烧错端口。
function Get-SerialPorts {
    # 优先用 WMI（PS5.1 无 Get-PnpDevice 的稳定串口过滤），列出名称含常见 USB 转串芯片
    $ports = @()
    try {
        $ports = Get-CimInstance Win32_PnPEntity -ErrorAction Stop |
            Where-Object { $_.Name -match '\(COM(\d+)\)' } |
            ForEach-Object {
                if ($_.Name -match '\(COM(\d+)\)') {
                    [PSCustomObject]@{
                        Port        = $Matches[1]
                        DeviceName  = $_.Name
                        IsUsbSerial = $_.Name -match 'CH34|CP210|FTDI|FT232|USB-SERIAL|USB Serial|Silicon Labs|CH910'
                    }
                }
            }
    } catch {
        # 降级：用 .NET 枚举（仅能得到 COM 号，拿不到设备名）
        try {
            $ports = [System.IO.Ports.SerialPort]::GetPortNames() |
                ForEach-Object {
                    [PSCustomObject]@{ Port = ($_ -replace '[^\d]', ''); DeviceName = "未知设备 ($_)"; IsUsbSerial = $true }
                }
        } catch { }
    }
    return $ports | Sort-Object { [int]$_.Port }
}

if ([string]::IsNullOrWhiteSpace($Port)) {
    $all = @(Get-SerialPorts)
    if ($all.Count -eq 0) {
        Write-Host "[!!] 未找到任何串口。" -ForegroundColor Red
        Write-Host "     请确认开发板已插好 USB 数据线并安装了驱动。"
        Write-Host "     也可手动指定： .\flash.ps1 -Port COM8"
        exit 1
    }

    $usb = @($all | Where-Object { $_.IsUsbSerial })
    if ($usb.Count -eq 1) {
        # 只有一个 USB 转串口，直接选中
        $Port = "COM$($usb[0].Port)"
        Write-Host "[串口] 自动选中唯一 USB 串口：$Port（$($usb[0].DeviceName)）" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "请选择烧录用的串口（输入序号后回车）：" -ForegroundColor Yellow
        $list = if ($usb.Count -gt 0) { $usb } else { $all }
        for ($i = 0; $i -lt $list.Count; $i++) {
            $mark = if ($list[$i].IsUsbSerial) { "  <-- USB 转串口" } else { "" }
            Write-Host ("  [{0}]  COM{1}  {2}{3}" -f ($i + 1), $list[$i].Port, $list[$i].DeviceName, $mark)
        }
        Write-Host ("  [{0}]  取消" -f ($list.Count + 1))

        $choice = Read-Host "序号"
        $idx = 0
        if ([int]::TryParse($choice, [ref]$idx) -and $idx -ge 1 -and $idx -le $list.Count) {
            $Port = "COM$($list[$idx - 1].Port)"
        } else {
            Write-Host "[!!] 已取消或输入无效。" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host ""
}

$dist     = $PSScriptRoot
$esptool  = Join-Path $env:USERPROFILE ".platformio\packages\tool-esptool\esptool.exe"
$mergedBin = Join-Path $dist "clockwise-v1.4.4-mario-merged.bin"
$fBoot    = Join-Path $dist "bootloader.bin"
$fParts   = Join-Path $dist "partitions.bin"
$fOta     = Join-Path $dist "boot_app0.bin"
$fApp     = Join-Path $dist "firmware.bin"

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Err($m)  { Write-Host "[!!] $m" -ForegroundColor Red }

# ---------- 前置检查 ----------
if (-not (Test-Path $esptool)) {
    Write-Err "找不到 esptool: $esptool"
    Write-Host "请先安装 PlatformIO，或修改脚本里的 `$esptool 路径。"
    exit 1
}

# 决定用哪种烧录方式
$useMerged = $Merged.IsPresent
if (-not $useMerged) {
    $missing = @($fBoot, $fParts, $fOta, $fApp) | Where-Object { -not (Test-Path $_) }
    if ($missing.Count -gt 0) {
        Write-Host "分段文件缺失，回退到合并镜像模式："
        $missing | ForEach-Object { Write-Host "  缺少 $(Split-Path $_ -Leaf)" }
        $useMerged = $true
    }
}
if ($useMerged -and -not (Test-Path $mergedBin)) {
    Write-Err "找不到合并镜像: $mergedBin"
    exit 1
}

# ---------- 摘要 ----------
Write-Step "端口     : $Port"
if ($useMerged) {
    $mb = [math]::Round((Get-Item $mergedBin).Length / 1MB, 2)
    Write-Step "方式     : 合并镜像 -> 0x0  ($mb MB)  [会清空 NVS]"
} else {
    Write-Step "方式     : 分段烧录（保留 NVS 配置）"
    Write-Step "  bootloader.bin -> 0x1000"
    Write-Step "  partitions.bin -> 0x8000"
    Write-Step "  boot_app0.bin  -> 0xe000"
    Write-Step "  firmware.bin   -> 0x10000"
}
Write-Step "波特率   : $Baud"
if ($Erase) { Write-Step "整片擦除 : 是（NVS/WiFi 会被清空）" } else { Write-Step "整片擦除 : 否" }
Write-Host ""

Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "  现在开始按住 BOOT 键，全程不要松手，直到提示烧录完成" -ForegroundColor Yellow
Write-Host "  本板 DTR 未接 IO0，无法自动进下载模式，必须手动按住" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host ""

# ---------- 通用重试执行 ----------
function Invoke-WithRetry {
    param(
        [string]$Label,
        [string[]]$ExtraArgs,
        [string]$SuccessPattern
    )
    Write-Host "$Label " -NoNewline
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $n = 0
    $out = ""
    while ((Get-Date) -lt $deadline) {
        $n++
        Write-Host "." -NoNewline
        $esptoolArgs = @("--chip", "esp32", "--port", $Port, "--connect-attempts", "1") + $ExtraArgs
        # 逐项转字符串再拼接：直接 Out-String 会把 ErrorRecord 渲染成
        # 带 "所在位置/CategoryInfo" 的冗长段落。
        $out = ((& $esptool @esptoolArgs 2>&1) | ForEach-Object { "$_" }) -join "`n"
        if ($out -match $SuccessPattern) {
            Write-Host ""
            Write-Ok "$Label 成功（第 $n 次尝试）"
            return $out
        }
    }
    Write-Host ""
    Write-Err "$Label 超时（$TimeoutSec 秒）"
    Write-Host "最后输出："
    Write-Host $out
    return $null
}

# ---------- 可选擦除 ----------
if ($Erase) {
    $r = Invoke-WithRetry -Label "整片擦除" -ExtraArgs @("erase-flash") `
                          -SuccessPattern "Chip erase completed successfully"
    if (-not $r) { exit 1 }
    Start-Sleep -Milliseconds 500
}

# ---------- 烧录 ----------
if ($useMerged) {
    $flashArgs = @("--baud", "$Baud", "write-flash", "-z", "0x0", $mergedBin)
} else {
    $flashArgs = @("--baud", "$Baud", "write-flash", "-z",
                   "0x1000", $fBoot,
                   "0x8000", $fParts,
                   "0xe000", $fOta,
                   "0x10000", $fApp)
}
$r = Invoke-WithRetry -Label "写入固件" -ExtraArgs $flashArgs -SuccessPattern "Hash of data verified"
if (-not $r) {
    Write-Host ""
    Write-Host "排查顺序："
    Write-Host "  1. 确认 BOOT 一直按住没有松开"
    Write-Host "  2. 关闭占用串口的程序（串口监视器 / Arduino IDE）"
    Write-Host "  3. 换一根数据线（不是纯充电线）"
    Write-Host "  4. 降速重试：.\flash.ps1 -Baud 115200"
    Write-Host "  5. 确认板子已上电（5V）"
    exit 1
}

# ---------- 回读校验（尽力而为） ----------
# write-flash 本身已经逐区做过 hash 校验（输出里的 "Hash of data verified"）。
# 这里的 verify-flash 需要重新进一次下载模式，若操作员已松开 BOOT 就连不上，
# 不能让这种情况把「已经烧成功」误判成失败。
Write-Step "回读校验..."
if ($useMerged) {
    $verifyArgs = @("--chip","esp32","--port",$Port,"--baud","$Baud","verify-flash","0x0",$mergedBin)
} else {
    $verifyArgs = @("--chip","esp32","--port",$Port,"--baud","$Baud","verify-flash",
                    "0x1000", $fBoot, "0x8000", $fParts, "0xe000", $fOta, "0x10000", $fApp)
}

$verifyOk = $false
$verifyOut = ""
for ($i = 0; $i -lt 5 -and -not $verifyOk; $i++) {
    $verifyOut = ((& $esptool @verifyArgs 2>&1) | ForEach-Object { "$_" }) -join "`n"
    if ($verifyOut -match "Verification successful|digest matched") {
        $verifyOk = $true
    } else {
        Start-Sleep -Milliseconds 800
    }
}

if ($verifyOk) {
    Write-Ok "回读校验通过"
} else {
    Write-Host ""
    Write-Host "[提示] 额外回读校验未能连回芯片（通常是因为已松开 BOOT）" -ForegroundColor Yellow
    Write-Host "       写入阶段已由 esptool 完成逐区 hash 校验，固件应已生效。" -ForegroundColor Yellow
    Write-Host "       可以用串口日志或设备设置页确认真实状态。" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  烧录完成，芯片已自动重启，现在可以松开 BOOT" -ForegroundColor Green
if (-not $useMerged -and -not $Erase) {
    Write-Host "  NVS 已保留：WiFi / 时区 / 亮度设置都不需要重配" -ForegroundColor Green
}
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "查看启动日志："
Write-Host "  & `"$env:USERPROFILE\.platformio\penv\Scripts\pio.exe`" device monitor --port $Port --baud 115200"
exit 0
