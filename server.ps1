# Portal NF — Servidor de Rede Interna (PowerShell puro, sem instalar nada)
# Execute como Administrador para funcionar na rede

param([int]$Port = 8080)

$BASE_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ALLOWED  = @('/base.json', '/users.json', '/mapeamento.json', '/cfg.json')

# Descobre o IP local
$IP = (Get-NetIPAddress -AddressFamily IPv4 |
       Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
       Sort-Object InterfaceMetric |
       Select-Object -First 1).IPAddress
if (-not $IP) { $IP = 'localhost' }

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://+:${Port}/")

try {
    $listener.Start()
} catch {
    Write-Host ""
    Write-Host "  [ERRO] Nao foi possivel iniciar o servidor." -ForegroundColor Red
    Write-Host "  Execute este arquivo como Administrador:" -ForegroundColor Yellow
    Write-Host "  Clique com o botao direito no .bat -> 'Executar como administrador'" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Pressione Enter para sair"
    exit 1
}

Write-Host ""
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host "       Portal NF - Rede Interna" -ForegroundColor Cyan
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host "  Local :  http://localhost:${Port}" -ForegroundColor White
Write-Host "  Rede  :  http://${IP}:${Port}" -ForegroundColor Green
Write-Host ""
Write-Host "  Compartilhe o endereco 'Rede' com os colegas." -ForegroundColor White
Write-Host "  Para parar: feche esta janela (Ctrl+C)" -ForegroundColor Gray
Write-Host "  =============================================" -ForegroundColor Cyan
Write-Host ""

function Send-Response {
    param($ctx, $statusCode, $contentType, $body)
    $ctx.Response.StatusCode = $statusCode
    $ctx.Response.ContentType = $contentType
    $ctx.Response.Headers.Add("Access-Control-Allow-Origin", "*")
    $ctx.Response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    $ctx.Response.Headers.Add("Access-Control-Allow-Headers", "Content-Type")
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    $ctx.Response.ContentLength64 = $bytes.Length
    $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $ctx.Response.OutputStream.Close()
}

function Send-File {
    param($ctx, $filePath, $contentType)
    $ctx.Response.ContentType = $contentType
    $ctx.Response.Headers.Add("Access-Control-Allow-Origin", "*")
    $bytes = [System.IO.File]::ReadAllBytes($filePath)
    $ctx.Response.ContentLength64 = $bytes.Length
    $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $ctx.Response.OutputStream.Close()
}

while ($listener.IsListening) {
    $ctx     = $listener.GetContext()
    $method  = $ctx.Request.HttpMethod
    $urlPath = $ctx.Request.Url.AbsolutePath
    $hora    = Get-Date -Format 'HH:mm:ss'

    try {
        if ($method -eq 'OPTIONS') {
            Send-Response $ctx 200 'text/plain' ''
            continue
        }

        if ($method -eq 'GET') {
            $filePath = if ($urlPath -eq '/') {
                Join-Path $BASE_DIR 'index.html'
            } elseif ($ALLOWED -contains $urlPath) {
                Join-Path $BASE_DIR ($urlPath.TrimStart('/'))
            } else { $null }

            if ($filePath -and (Test-Path $filePath)) {
                $ctype = if ($urlPath -eq '/') { 'text/html; charset=utf-8' } else { 'application/json; charset=utf-8' }
                Send-File $ctx $filePath $ctype
                Write-Host "  $hora  200  GET  $urlPath" -ForegroundColor DarkGray
            } elseif ($ALLOWED -contains $urlPath) {
                Send-Response $ctx 200 'application/json' 'null'
                Write-Host "  $hora  200  GET  $urlPath (vazio)" -ForegroundColor DarkGray
            } else {
                Send-Response $ctx 404 'text/plain' 'Not Found'
            }
            continue
        }

        if ($method -eq 'POST' -and $ALLOWED -contains $urlPath) {
            $reader  = New-Object System.IO.StreamReader($ctx.Request.InputStream, [System.Text.Encoding]::UTF8)
            $body    = $reader.ReadToEnd()
            $reader.Close()
            $fPath   = Join-Path $BASE_DIR ($urlPath.TrimStart('/'))
            [System.IO.File]::WriteAllText($fPath, $body, [System.Text.Encoding]::UTF8)
            Send-Response $ctx 200 'application/json' '{"ok":true}'
            Write-Host "  $hora  200  POST $urlPath ($($body.Length) bytes)" -ForegroundColor DarkGray
            continue
        }

        Send-Response $ctx 403 'text/plain' 'Forbidden'

    } catch {
        try { $ctx.Response.Abort() } catch {}
        Write-Host "  [ERRO] $_" -ForegroundColor Red
    }
}
