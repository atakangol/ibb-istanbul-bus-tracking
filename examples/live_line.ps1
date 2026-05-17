# Live buses on one line (no Python required)
param(
    [string]$Line = "15B"
)

$body = @"
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tns="http://tempuri.org/">
  <soap:Body>
    <tns:GetHatOtoKonum_json>
      <tns:HatKodu>$Line</tns:HatKodu>
    </tns:GetHatOtoKonum_json>
  </soap:Body>
</soap:Envelope>
"@

$tmp = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tmp, $body, [System.Text.UTF8Encoding]::new($false))

$response = curl.exe -s -m 30 -X POST "https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx" `
    -H "Content-Type: text/xml; charset=utf-8" `
    -H "SOAPAction: http://tempuri.org/GetHatOtoKonum_json" `
    --data-binary "@$tmp"

Remove-Item $tmp -Force

if ($response -match '<GetHatOtoKonum_jsonResult>(?<json>.*?)</GetHatOtoKonum_jsonResult>') {
    $buses = $Matches.json | ConvertFrom-Json
    Write-Host "Line $Line : $($buses.Count) vehicles`n"
    $buses | Select-Object -First 5 kapino, boylam, enlem, son_konum_zamani, yon | Format-Table -AutoSize
} else {
    Write-Host $response
}
