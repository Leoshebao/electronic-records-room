<#
.SYNOPSIS
    为内网 HTTPS 生成自签证书（必须包含 IP SAN）。

.DESCRIPTION
    产出三件文件，均落在 -OutDir：
      server.crt  PEM 证书（Nginx ssl_certificate）
      server.key  PEM PKCS#8 私钥（Nginx ssl_certificate_key）
      server.pfx  客户端导入包，装进"受信任的根证书颁发机构"后浏览器不再告警

    生成方式按环境自动降级：
      1) 有 openssl              -> openssl req -x509 -addext
      2) 无 openssl（纯内网常见） -> .NET CertificateRequest 直接签发 PEM
    两种方式都不需要管理员权限，也不依赖 Docker 或联网。

.PARAMETER ServerIP
    服务端内网 IP。留空则自动探测本机第一个可用 IPv4。

.PARAMETER OutDir
    输出目录，默认脚本所在目录。

.PARAMETER Days
    有效期天数，默认 365。

.PARAMETER PfxPassword
    导出的 pfx 密码，客户端导入时需要。

.EXAMPLE
    .\gen-cert.ps1 -ServerIP 192.168.1.100
#>
param(
    [string]$ServerIP = "",
    [string]$OutDir = $PSScriptRoot,
    [int]$Days = 365,
    [string]$PfxPassword = "erecords"
)

$ErrorActionPreference = "Stop"

# ---- 1. 解析服务端 IP ----
if (-not $ServerIP) {
    $ServerIP = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object {
            $_.IPAddress -ne "127.0.0.1" -and
            $_.PrefixOrigin -ne "WellKnown" -and
            $_.IPAddress -notlike "169.254.*"
        } |
        Sort-Object -Property InterfaceIndex |
        Select-Object -First 1).IPAddress
}
if (-not $ServerIP) {
    throw "未能自动探测本机内网 IP，请用 -ServerIP 参数显式指定，例如 -ServerIP 192.168.1.100"
}
Write-Host "[1/4] 服务端 IP: $ServerIP" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$crtPath = Join-Path $OutDir "server.crt"
$keyPath = Join-Path $OutDir "server.key"
$pfxPath = Join-Path $OutDir "server.pfx"

function ConvertTo-Pem([byte[]]$Bytes, [string]$Label) {
    $b64 = [Convert]::ToBase64String($Bytes, [System.Base64FormattingOptions]::InsertLineBreaks)
    "-----BEGIN $Label-----`r`n$b64`r`n-----END $Label-----`r`n"
}

$openssl = Get-Command openssl -ErrorAction SilentlyContinue

if ($openssl) {
    # ---- 2a. openssl 路径 ----
    $san = "subjectAltName=IP:$ServerIP,IP:127.0.0.1,DNS:localhost"
    Write-Host "[2/4] 使用 openssl 生成（SAN: $san）" -ForegroundColor Cyan
    Push-Location $OutDir
    try {
        & openssl req -x509 -newkey rsa:2048 -sha256 -days $Days -nodes `
            -keyout "server.key" -out "server.crt" `
            -subj "/C=CN/ST=Guangdong/L=Guangzhou/O=Intranet/OU=IT/CN=$ServerIP" `
            -addext $san `
            -addext "keyUsage=critical,digitalSignature,keyEncipherment" `
            -addext "extendedKeyUsage=serverAuth" `
            -addext "basicConstraints=critical,CA:TRUE"
        if ($LASTEXITCODE -ne 0) { throw "openssl 生成证书失败" }
        & openssl pkcs12 -export -out "server.pfx" -inkey "server.key" -in "server.crt" -passout "pass:$PfxPassword"
    }
    finally {
        Pop-Location
    }
}
else {
    # ---- 2b. 纯 .NET 路径：不需要 openssl / docker / 管理员权限 ----
    Write-Host "[2/4] 未找到 openssl，改用 .NET CertificateRequest 生成" -ForegroundColor Yellow

    $rsa = [System.Security.Cryptography.RSA]::Create(2048)
    $req = New-Object System.Security.Cryptography.X509Certificates.CertificateRequest(
        "CN=$ServerIP",
        $rsa,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256,
        [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
    )

    # SAN 同时写入内网 IP / 127.0.0.1 / localhost，否则浏览器仍报证书无效
    $sanBuilder = New-Object System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder
    $sanBuilder.AddIpAddress([System.Net.IPAddress]::Parse($ServerIP))
    $sanBuilder.AddIpAddress([System.Net.IPAddress]::Parse("127.0.0.1"))
    $sanBuilder.AddDnsName("localhost")
    $req.CertificateExtensions.Add($sanBuilder.Build())

    $req.CertificateExtensions.Add(
        (New-Object System.Security.Cryptography.X509Certificates.X509KeyUsageExtension(
            ([System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature -bor
             [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyEncipherment), $true)))

    $eku = New-Object System.Security.Cryptography.OidCollection
    [void]$eku.Add((New-Object System.Security.Cryptography.Oid("1.3.6.1.5.5.7.3.1")))
    $req.CertificateExtensions.Add(
        (New-Object System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension($eku, $false)))
    $req.CertificateExtensions.Add(
        (New-Object System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension($true, $false, 0, $true)))

    $cert = $req.CreateSelfSigned((Get-Date).AddDays(-1), (Get-Date).AddDays($Days))

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $der = $cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
    [System.IO.File]::WriteAllText($crtPath, (ConvertTo-Pem $der "CERTIFICATE"), $utf8)
    # .NET Framework 4.8 的 RSACng 没有 ExportPkcs8PrivateKey，需走 CngKey 通道
    $keyBlob = $null
    if ($rsa.PSObject.Methods.Name -contains "ExportPkcs8PrivateKey") {
        $keyBlob = $rsa.ExportPkcs8PrivateKey()
    }
    elseif ($rsa.PSObject.Properties.Name -contains "Key") {
        $keyBlob = $rsa.Key.Export([System.Security.Cryptography.CngKeyBlobFormat]::Pkcs8PrivateBlob)
    }
    if (-not $keyBlob) { throw "当前 .NET 运行时无法导出 PKCS#8 私钥，请安装 openssl 后重试" }
    [System.IO.File]::WriteAllText($keyPath, (ConvertTo-Pem $keyBlob "PRIVATE KEY"), $utf8)

    $securePwd = ConvertTo-SecureString -String $PfxPassword -Force -AsPlainText
    Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $securePwd | Out-Null

    $rsa.Dispose()
    $cert.Dispose()
}

Write-Host "[3/4] 证书已写入: $crtPath" -ForegroundColor Cyan

# ---- 4. 校验 SAN 与关键扩展 ----
Write-Host "[4/4] 校验证书" -ForegroundColor Cyan
$x509 = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($crtPath)
Write-Host "      Subject : $($x509.Subject)"
Write-Host "        NotAfter: $($x509.NotAfter.ToString('yyyy-MM-dd'))"
$x509.Extensions | ForEach-Object {
    if ($_.Oid.Value -eq "2.5.29.17") {
        Write-Host "        SAN     : $($_.Format($false))"
    }
}
$x509.Dispose()

if (-not (Test-Path $keyPath)) {
    throw "未生成 server.key，Nginx 无法完成 TLS 握手"
}

Write-Host ""
Write-Host "==== 完成 ====" -ForegroundColor Green
Write-Host "证书: $crtPath"
Write-Host "私钥: $keyPath"
Write-Host "客户端导入包: $pfxPath （密码: $PfxPassword）"
Write-Host ""
Write-Host "客户端信任步骤（每台终端执行一次）："
Write-Host "  1. 双击 server.pfx"
Write-Host "  2. 安装证书 -> 本地计算机 -> 下一步"
Write-Host "  3. 选择【受信任的根证书颁发机构】-> 下一步 -> 完成"
Write-Host "  4. 重启浏览器，访问 https://$ServerIP:8443"
Write-Host ""
$expireDate = (Get-Date).AddDays($Days).ToString('yyyy-MM-dd')
Write-Host "到期提醒：有效期 $Days 天，请在 $expireDate 前重新生成。" -ForegroundColor Yellow
